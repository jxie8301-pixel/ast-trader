"""Tier 3: Authentic UZI-Skill composite ranking, persona matching, and action decider."""
from __future__ import annotations

import concurrent.futures
import logging
from typing import Any

from core.execution_playbook import PlaybookBuilder
from core.youzi_personas import evaluate_youzi_personas, extract_tape_features
from data.eltdx_collector import EltdxCollector

logger = logging.getLogger("ast_trader.screener.rank")
playbook_builder = PlaybookBuilder()


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
        except Exception:
            c["main_net_wan"] = round(seal_amt / 10000.0, 1) if seal_amt else 0.0
            c["main_ratio"] = 0.0

        close_val = real_quote.get("close", c.get("close", 0.0))
        pct_val = real_quote.get("pct_chg", pct_chg)
        amount_val = real_quote.get("amount", amount)
        turnover_val = real_quote.get("turnover_ratio", 0.0)
        total_mv_val = real_quote.get("total_mv", 0.0)

        # 2. UZI 原生盘口微观打分 (ranker.py preselect score)
        # liquidity (0~4分) + strength (-3~10分) * 2 + activity (0~3分)
        liquidity_score = min(amount_val / 10e8, 4.0)
        strength_score = max(-3.0, min(pct_val, 10.0))
        activity_score = min(turnover_val / 3.0, 3.0) if turnover_val > 0 else min(amount_val / 1e8, 2.0)
        tape_score = round(strength_score * 2.0 + liquidity_score + activity_score + bl * 10.0, 1)
        c["rank_score"] = tape_score

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
        momentum_proxy = {
            "volume_ratio": 1.5,
            "is_bullish_ma": pct_val > 0,
        }
        theme_proxy = {
            "concepts": c.get("concepts", [c.get("limit_reason", "")]),
            "leader_rank": 1 if bl >= 2 else 3,
            "breadth_pct": 75.0 if bl >= 2 else 50.0,
        }

        tape_features = extract_tape_features(
            quote=quote_proxy,
            momentum=momentum_proxy,
            market_cap=total_mv_val,
            theme_info=theme_proxy,
            governance_risk=False,
            hard_event=True,
        )

        matched_personas = evaluate_youzi_personas(tape_features)
        c["matched_personas"] = matched_personas

        # 4. UZI 四态决策状态流转 (ranker.py lines 79-88)
        leader = bl >= 2
        if pct_chg >= 7.0 and not leader:
            action = "wait_pullback"
            action_desc = "等待回踩确认 (短时涨幅偏大，追高风险高)"
        elif leader and pct_chg >= 3.0 and matched_personas:
            action = "buyable"
            action_desc = "主升进场/回踩低吸"
        elif leader:
            action = "wait_reseal"
            action_desc = "梯队龙头等待回封"
        else:
            action = "watch_only"
            action_desc = "观望/仅列入观察池"

        c["action"] = action
        c["action_desc"] = action_desc

        # 构建实盘执行剧本战术卡 (Execution Playbook)
        act_key = "BUY" if action == "buyable" else ("WAIT" if action in ("wait_pullback", "wait_reseal") else "WAIT")
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
