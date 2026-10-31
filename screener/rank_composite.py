"""Tier 3: Authentic UZI-Skill composite ranking, persona matching, and action decider."""
from __future__ import annotations

import concurrent.futures
import logging
from typing import Any

import config
from core.execution_playbook import PlaybookBuilder
from core.youzi_personas import evaluate_youzi_personas, extract_tape_features
from data.eltdx_collector import EltdxCollector

logger = logging.getLogger("ast_trader.screener.rank")
playbook_builder = PlaybookBuilder()


def _opt_float(value: Any) -> float | None:
    """转 float；None / 不可解析一律返回 ``None``（**不是** 0.0）。"""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _is_limit_up(pct: float, board_kind: str | None) -> bool:
    """是否达到封板涨幅（主板 9.5% / 双创 19.5%）。"""
    if board_kind == "growth":
        return pct >= 19.5
    return pct >= 9.5


def rank_composite(
    candidates: list[dict[str, Any]],
    collector: EltdxCollector,
    top_n: int = 10,
    max_workers: int = 5,
) -> list[dict[str, Any]]:
    """Tier 3: 严格对齐 UZI ranker.py 算法 —— 盘口评分 + 24 游资战法匹配 + 四态行动决断。"""

    def _process_candidate(c: dict[str, Any]) -> dict[str, Any]:
        code_num = c["code"]
        amount = c.get("amount", 0.0)
        pct_chg = c.get("pct_chg", 0.0)
        seal_amt = c.get("seal_amt", 0.0)
        bl = c.get("board_level") or 1
        name = c.get("name", "")

        # 1. 资金流与真实快照拉取
        real_quote = {}
        try:
            real_quote = collector.get_realtime_quote(code_num)
        except Exception as e:
            logger.debug(f"获取快照异常: {e}")

        try:
            mf = collector.get_money_flow(code_num)
            c["main_net_wan"] = mf.get("main_net_wan", 0.0)
            c["main_ratio"] = mf.get("main_ratio", 0.0)
        except Exception as e:
            logger.debug(f"获取主力资金流异常 {code_num}: {e}")
            c["main_net_wan"] = None
            c["main_ratio"] = None
            c["money_flow_degraded"] = True

        close_val = real_quote.get("close", c.get("close", 0.0))
        pct_val = real_quote.get("pct_chg", pct_chg)
        amount_val = real_quote.get("amount", amount)
        turnover_val = real_quote.get("turnover_ratio", 0.0)
        # 市值优先取 L1 画像的真实总市值（Tier 3 的 get_realtime_quote 是单只重调用，
        # 且其 finance_batch 失败时会算出 0.0 —— 那会让所有市值档位判据失真）
        total_mv_val = float(c.get("total_mv") or 0.0) or float(real_quote.get("total_mv", 0.0) or 0.0)
        if total_mv_val <= 0:
            c["market_cap_unverified"] = True

        # 2. UZI 原生盘口微观打分 (ranker.py preselect score)
        # liquidity (0~4分) + strength (-3~10分) * 2 + activity (0~3分) + 连板动量 (上限 10分)
        liquidity_score = min(amount_val / 10e8, 4.0)
        strength_score = max(-3.0, min(pct_val, 10.0))
        activity_score = min(turnover_val / 3.0, 3.0) if turnover_val > 0 else min(amount_val / 1e8, 2.0)
        # 修正 R11: 连板权重由 bl * 10.0 调整为均衡的 min(bl * 2.5, 10.0)，防止板数过度碾压流动性与防守纪律
        board_score = min(bl * 2.5, 10.0)
        tape_score = strength_score * 2.0 + liquidity_score + activity_score + board_score
        # 修正 R3: 接入 money_flow_degraded 惩罚与标记
        if c.get("money_flow_degraded", False):
            tape_score -= 5.0
            c["degraded_reason"] = "资金流缺失降级"
        c["rank_score"] = round(tape_score, 1)

        # 3. 提取微观特征并运行 24 大一线游资战法匹配
        quote_proxy = {
            "close": close_val,
            "pct_chg": pct_val,
            "amount": amount_val,
            "high": real_quote.get("high", close_val),
            "open": real_quote.get("open", close_val),
            "pre_close": real_quote.get("pre_close", close_val),
            "turnover_ratio": turnover_val,
        }
        # ★ P1-3：此处原为 ``"volume_ratio": 1.5`` —— 一个**凭空捏造、恒为定值**的
        #   量比，既无数据源也无推导过程，与 `derivation.py` 硬编码 16.5 属同类数据
        #   纪律问题。它让 24 个游资画像里所有依赖 ``active`` 的判据长期按同一个
        #   假量比打分，是「连板股也匹配不到画像 → wait_reseal → 0 仓位」的帮凶。
        #   现改为：有真实量比就用，没有就传 ``None``（由 extract_tape_features 弃权）。
        volume_ratio_val = _opt_float(c.get("volume_ratio"))
        # ★ 20261029 审计 P0-3（契约测试发现）：此处原有
        #   ``real_quote.get("volume_ratio")`` 兜底 —— 但 get_realtime_quote 的返回键里
        #   **根本没有 volume_ratio**（只有 vol/amount/turnover_ratio），该兜底恒返回 None，
        #   是一行"看起来有数据源、实际永远拿不到"的死读取。按缺值纪律删除，
        #   量比取不到就如实标记 UNVERIFIED，由 extract_tape_features 弃权。
        if volume_ratio_val is None:
            c["volume_ratio_unverified"] = True
        momentum_proxy = {
            "volume_ratio": volume_ratio_val,
            "is_bullish_ma": pct_val > 0,
        }
        concepts = c.get("concepts") or [c.get("limit_reason", "")]
        # ★ 20261029 审计 P1-8：原为 ``leader_rank = 1 if bl >= 2 else 3``（凭空自封龙头位）
        #   与 ``breadth_pct = 75.0 / 50.0``（凭空自封题材热度）—— 24 个游资画像里所有
        #   依赖 leader / theme_hot / breadth 的判据因此长期按**编造的**热度打分。
        #   天梯上下文（ladder_analyzer 的 stock_context_map）里本来就有真实龙头位，
        #   取得到就用，取不到就是 None（弃权），**绝不造数**。
        _theme_ctx = c.get("theme_info") or {}
        theme_proxy = {
            "concepts": concepts,
            "leader_rank": _theme_ctx.get("leader_rank"),
            "breadth_pct": _theme_ctx.get("breadth_pct"),
            "has_theme": bool(concepts),
        }

        # ★ 治理风险改由 Tier 2 排雷的真实违规计数驱动（原硬编码 False，恒不生效）
        governance_risk_val = int(c.get("recent_violation_count") or 0) > 0 or int(c.get("violation_count") or 0) > 0

        tape_features = extract_tape_features(
            quote=quote_proxy,
            momentum=momentum_proxy,
            market_cap=total_mv_val,
            theme_info=theme_proxy,
            governance_risk=governance_risk_val,
            # ★ 原硬编码 True。硬事件应指"确有题材催化"，无概念时不应凭空成立。
            hard_event=bool(concepts),
        )

        matched_personas = evaluate_youzi_personas(tape_features)
        c["matched_personas"] = matched_personas

        # 4. 五态决策状态流转 (使用实时 pct_val 保证数据时效一致性)
        # ★ 解开「首板死锁」：原实现 ``if pct_val >= 7.0 and not leader: wait_pullback``
        #   会把**所有首板涨停**（今日占涨停池 88.7%）一律判成"追高"并把仓位清零。
        #   而 Tier 0 又规定非涨停不得入池 —— 于是"非涨停不选、涨停了又不让买"，
        #   整个精选池恒为 0% 仓位看戏。
        #   现拆成两支：已封板的首板走 AUCTION（次日竞价条件单，给试错仓），
        #   未封板却已大涨的才走 wait_pullback（那才是真正的日内追高）。
        leader = bl >= 2
        board_kind = c.get("board_kind")
        limit_up = _is_limit_up(pct_val, board_kind)

        if leader and pct_val >= 3.0 and matched_personas:
            action = "buyable"
            action_desc = "主升进场/回踩低吸"
        elif leader:
            action = "wait_reseal"
            action_desc = "梯队龙头等待回封"
        elif pct_val >= 7.0 and limit_up:
            action = "wait_auction"
            action_desc = (
                f"首板已封板，次日 9:25 竞价确认 (高开≥{config.AUCTION_MIN_OPEN_PCT:.1f}% "
                f"且竞价量≥昨日全天 {config.AUCTION_MIN_VOLUME_RATIO*100:.0f}%) 方可试错介入"
            )
        elif pct_val >= 7.0:
            action = "wait_pullback"
            action_desc = "等待回踩确认 (未封板但短时涨幅偏大，追高风险高)"
        else:
            action = "watch_only"
            action_desc = "观望/仅列入观察池"

        c["action"] = action
        c["action_desc"] = action_desc

        # 构建实盘执行剧本战术卡 (Execution Playbook)
        if action == "buyable":
            act_key = "BUY"
        elif action == "wait_auction":
            act_key = "AUCTION"
        else:
            act_key = "WAIT"
        pb = playbook_builder.build(
            quote=real_quote or {"close": close_val, "pre_close": close_val},
            momentum={"support_level": round(close_val * 0.95, 2), "resistance_level": round(close_val * 1.05, 2)},
            matched_personas=[p["youzi_name"] for p in matched_personas],
            action=act_key,
            ladder_info=c.get("theme_info") or {"is_leader": leader, "board_level": bl},
            fatal_flag=False,
        )
        c["playbook"] = pb

        # 5. 装配进场条件与唯一失效退出线 (完全由游资战法推导)
        if matched_personas:
            top_p = matched_personas[0]
            supporters = "、".join(p["youzi_name"] for p in matched_personas[:3])
            c["supporters"] = supporters
            c["plan_high_open"] = f"{pb.entry_tactic} (挂单区间: {pb.entry_price_range})"
            c["plan_stop_loss"] = pb.invalidation_rule
        else:
            c["supporters"] = "普通游资/散户资金"
            c["plan_high_open"] = f"{pb.entry_tactic} (挂单区间: {pb.entry_price_range})"
            c["plan_stop_loss"] = pb.invalidation_rule

        return c

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        scored_list = list(executor.map(_process_candidate, candidates))

    ranked = sorted(scored_list, key=lambda x: x.get("rank_score", 0.0), reverse=True)
    return ranked[:top_n]
