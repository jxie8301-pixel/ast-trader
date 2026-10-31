"""Five-node judgment chain synthesizer for AST-Trader.
Strictly absorbing Ashare-researchreport core methodology:
  - 首页「赚不赚钱」数据看板 (3-5 指标 + Sparkline 序列 + 障眼法警示)
  - 支柱 ❶ 是不是好公司？(质地五问 · 铁门筛选 · 筛选信号不进乘法)
  - 支柱 ❷ 在变好吗？(状态跃迁 λ + 实锤/回声分级 + 全链唯一「该等什么」)
  - 支柱 ❸ 贵不贵？(P=F+N 叙事溢价拆解 + 反向DCF市场隐含赌注 + [SOTP, DCF]双锚区间)
  - 支柱 ❹ 主力行为与路径承载 (结合 Main Force Engine 7阶段状态机 + 微观盘口反欺诈 + 筹码沉淀)
  - 支柱 ❺ 实战双轨决断与执行战术 (六档行动档位 + 持币/持股双轨战术 + 9:25竞价与T+1防线)
"""
from __future__ import annotations

import logging
from datetime import date as _date
from typing import Any
import pandas as pd

import config
from core.capital_matrix import CapitalMatrixRadar
from core.derived_metrics import DerivedMetricsCalculator
from core.derivation import (
    check as check_derivation,
    generate_standard_derivation,
    render_sotp_table,
    render_dcf_table,
    render_discount_rate_table,
)
from core.execution_playbook import PlaybookBuilder
from lint.validator import LintValidator
from .red_flags import LEVEL_FATAL, RedFlagItem, get_top3_risks, has_fatal_red_flags
from core.types import (
    DecisionVerdict,
    OddsVerdict,
    PathVerdict,
    QualityVerdict,
    SingleStockContext,
    StateVerdict,
)
from core.pillars import (
    build_pillar_1_quality,
    build_pillar_2_state,
    build_pillar_3_odds,
    build_pillar_4_path,
    build_pillar_5_decision,
    assemble_and_lint_card,
)


logger = logging.getLogger("ast_trader.core.judgment_chain")


# =============================================================================
# 判定结论语义映射 (严禁使用中文子串匹配做控制流)
#
# 背景: 决断卡的中文结论串之间存在包含关系 —— 质地判定的 "不好" 包含 "好"，
# 若用 `'好' in quality_verdict` 判定"是不是好公司"，会把"不好"误判为"是"。
# 实测 10 只种子标的中有 5 只命中该缺陷。此处改为**显式集合白名单**，
# 让取值域与语义绑定，避免同类缺陷复发。
# =============================================================================

#: 质地判定 → "好公司?" 成立。取值域 {"好", "部分好", "不好"}，注意 "不好" 不在其中。
QUALITY_VERDICT_GOOD: frozenset[str] = frozenset({"好", "部分好"})

#: 赔率判定 → "好价格?" 成立。取值域含 "未核验(财务缺失)"/"买完完美未来" 等否定态。
ODDS_VERDICT_GOOD: frozenset[str] = frozenset({"便宜(有余地)", "合理"})

#: 行动档位 → AVOID 分支。取值域含 "等证据临界(观察)"，其含 "观察" 但不属于 AVOID。
DECISION_GEAR_AVOID: frozenset[str] = frozenset({"回避", "减仓"})

# ─── 物种分流轨道 (classify_stock_track 取值域) ────────────────────────────
#: A 轨：短线题材与接力博弈（连板梯队 / 题材龙头 / 小市值高换手）
TRACK_A_THEME = "TRACK_A_THEME"
#: B 轨：机构趋势与产业中军（须真实命中市值门槛，不得作为兜底）
TRACK_B_INSTITUTIONAL = "TRACK_B_INSTITUTIONAL"
#: 未核验轨：物种未定 —— 既不属题材接力也不达中军门槛时的**唯一合法兜底**
TRACK_UNVERIFIED = "TRACK_UNVERIFIED"

#: 弱市(情绪冰点)下需走「情绪防守」分支的轨道。
#: ★ B 轨刻意不在其中：中军标的享有弱市豁免；
#: ★ 未核验轨**必须**在内 —— 既未证明是题材票也未达中军门槛，
#:   弱市中不得享受中军豁免去拿核心仓档位（这是旧实现把永安行判成中军的直接危害）。
TRACK_DEFENSIVE_ON_ICE: frozenset[str] = frozenset({TRACK_A_THEME, TRACK_UNVERIFIED})


def is_good_company(quality_verdict: str | None) -> bool:
    """质地判定是否为"好公司"。显式白名单，杜绝「不好」被子串匹配误判为「好」。"""
    return (quality_verdict or "") in QUALITY_VERDICT_GOOD


def is_good_price(odds_verdict: str | None) -> bool:
    """赔率判定是否为"好价格"。"""
    return (odds_verdict or "") in ODDS_VERDICT_GOOD


def is_avoid_gear(decision_gear: str | None) -> bool:
    """行动档位是否属于回避类。"""
    return (decision_gear or "") in DECISION_GEAR_AVOID


def format_three_part_conclusion(
    quality_verdict: str | None,
    position_cap: float,
    odds_verdict: str | None,
    suffix: str = "",
) -> str:
    """生成三分结论串 — 全系统唯一出口，保证 Lint 纠偏分支与主分支文案同源。

    Args:
        quality_verdict: ❶支柱质地判定。
        position_cap: 最终仓位上限。
        odds_verdict: ❸支柱赔率判定。
        suffix: 附加说明（如 "机检未通过"）。
    """
    good_company = "是" if is_good_company(quality_verdict) else "否/存疑"
    good_bet = "是" if position_cap > 0 else "否"
    good_price = "是" if is_good_price(odds_verdict) else "否"
    tail = f" ({suffix})" if suffix else ""
    return f"好公司? 【{good_company}】 · 好下注? 【{good_bet}】 · 好价格? 【{good_price}】{tail}"


def _left_tail_depth_pct(depth_to_sotp: float | None) -> float | None:
    """把 `depth_to_sotp` 归一为「左尾深度」百分比正值。

    `_build_pillar_4_path` 的计算式为 ``(price - sotp_ps) / price * -100``：
    现价高于 SOTP 底座时结果为负，其**绝对值**才是"跌回估值底座"的下跌空间（左尾）；
    现价已低于底座时该值为正，此时不存在向下的左尾空间，返回 ``None`` 交由规则弃权。

    量纲说明：``config.LEFT_TAIL_WARN_THRESHOLD`` 为小数 0.25，而本函数与
    ``depth_to_sotp`` 均为百分比，比较前须 ``/100``（已在 `_resolve_position_cap` 内处理）。
    """
    if depth_to_sotp is None or depth_to_sotp >= 0:
        return None
    return abs(depth_to_sotp)


def _resolve_position_cap(
    mf_cap: float | None,
    mf_confidence: float | None,
    left_tail_depth_pct: float | None = None,
    *,
    small_track: bool = False,
) -> float:
    """按主力引擎置信度在「常规档 / 极端档」之间裁决单票仓位上限 (E-1)，并对左尾风险腰斩 (E-2)。

    替代原先散落在 ``_decide_gear`` 中的裸数字 ``0.25 / 0.20 / 0.10 / 0.08``，
    全部阈值收敛至 ``config``，业务侧不再出现硬编码上限。

    Args:
        mf_cap: 主力引擎给出的建议仓位（小数，取值域 {0.0, 0.10, 0.15, 0.20}）。
        mf_confidence: 主力引擎阶段置信度（百分制，0~100）。
        left_tail_depth_pct: 左尾深度（**百分比正值**，表示现价距 SOTP 保守底座的下跌空间）。
        small_track: 是否为「期权仓(小)」轻仓试错轨道。

    Returns:
        仓位上限小数。降级与异常入参一律返回 0.0。
    """
    halved_cap = config.MAX_SINGLE_POSITION / 2.0  # 腰斩档 = 10%

    if small_track:
        # 期权仓(小)：上限常规档的一半，主力未给建议时取上限的 80%
        base = mf_cap if mf_cap is not None else halved_cap * 0.8
        cap = min(halved_cap, base)
    elif (
        mf_cap is not None
        and mf_cap >= config.POSITION_EXTREME_MIN_STAGE_CAP
        and (mf_confidence or 0.0) >= config.POSITION_EXTREME_MIN_CONFIDENCE
    ):
        # 极端档：主力已给满档建议且阶段置信度极高 —— 直接取极端上限
        cap = config.MAX_SINGLE_POSITION_EXTREME
    else:
        base = mf_cap if mf_cap is not None else config.MAX_SINGLE_POSITION
        cap = min(config.MAX_SINGLE_POSITION, base)

    # E-2 左尾腰斩：现价距估值底座的下跌空间超过阈值时，仓位强制腰斩
    if left_tail_depth_pct is not None and left_tail_depth_pct / 100.0 > config.LEFT_TAIL_WARN_THRESHOLD:
        cap = min(cap, halved_cap)

    return round(max(0.0, cap), 6)


def _build_valuation_assumption_note(deriv: dict[str, Any], anchor: dict[str, Any]) -> str:
    """F-1 / F-3：把估值区间的**假设前提、口径差异、排除项**显式写出来。

    ★ 起因（第三方评审）：报告把 DCF/SOTP 算出的区间冠以「合理价」之名，
      隐含地宣称市场价格"错误"，却没有把支撑该区间的假设、以及该区间
      **不含什么**告诉读者 —— 评审称之为「框架傲慢」。

      核查后发现问题不在方法论（系统已有 P=F+N 叙事拆解与反向 DCF 承认
      市场预期的存在），而在于：支撑假设是**裸魔数**（`derivation.py:293`
      的 `base_pe`、`:336-338` 的 `cagr`），而唯一的口径说明
      `divergence_note`（`derivation.py:391`）**生成后从未被渲染**。

    ★ 本函数**不做任何计算**，只把 `derivation` 里已有的元数据串成要点。
      缺失字段一律输出「未核验」，严禁伪造默认值（沿用 NFR 数据纪律）。

    ★ 渲染约束（C-2）：`html_renderer.py` 以 `white-space: pre-wrap`
      渲染支柱文本，**不解析 Markdown**，故此处只能用 `• xxx` 纯文本，
      不得用表格语法，否则读者会看到裸管道符。
    """
    sotp = deriv.get("sotp") or {}
    dcf = deriv.get("dcf") or {}
    pfn = deriv.get("p_f_n") or {}

    parts: list[str] = []
    fact_basis = pfn.get("fact_basis")
    if fact_basis:
        parts.append(fact_basis)
    dr_total = (dcf.get("discount_rate") or {}).get("total")
    if dr_total is not None:
        parts.append(f"折现率 {dr_total:.1f}%")
    net_debt = sotp.get("net_debt")
    if net_debt is not None:
        parts.append(f"净负债按 {net_debt:.1f} 亿计")
    segments = sotp.get("segments") or []
    for seg in segments[:1]:
        mult = seg.get("multiple")
        basis = seg.get("basis")
        if mult is not None:
            parts.append(f"分部估值倍数 {mult:.0f}x（{basis or '对标同业'}）")
    scenarios = dcf.get("scenarios") or []
    if scenarios:
        cagr_txt = " / ".join(
            f"{sc.get('cagr', 0.0):.0f}%" for sc in scenarios if sc.get("cagr") is not None
        )
        if cagr_txt:
            parts.append(f"三情景 5 年收入增速 {cagr_txt}")

    lines = [
        "  • 估值假设前提: " + ("；".join(parts) if parts else "未核验(估值元数据缺失)")
    ]

    div_note = anchor.get("divergence_note")
    if div_note:
        lines.append(f"  • 两端口径差异: {div_note}")

    # ★ 核心：显式声明本估值**不含**什么 —— 直接回应「框架傲慢」
    lines.append(
        "  • ⚠️ 本估值不含: 未并表/未盈利新业务的期权价值（第二增长曲线）。"
        "市场价高于本区间时，差额即为市场对该部分的定价，属另一套假设，"
        "并不代表市场错误"
    )
    return "\n".join(lines)


def _build_signal_freshness_banner(
    is_micro_degraded: bool, mf_conf: float, is_stale: bool = False
) -> str:
    """F-4：时效性声明**恒非空**。

    ★ 起因（第三方评审）：微观资金面结论（主力阶段/聪明钱成本/筹码分布）
      是**日内横截面切片**（`microstructure.py:130` 的 `smart_vwap` 由当日
      5 分钟 K 线加权得出），生命周期极短。但系统的不确定性提示只在
      **数据降级时**才出现，导致 96% 置信度的「无抵抗阴跌出清期」
      在报告里是**裸断言** —— 置信度越高，反而越不提示。

      评审的原话：把阶段性状态当成持续趋势，用「不可承受」的定性
      关闭了修正的可能性。

    ★ 修正：非降级场景同样输出时效声明，明确其日内有效、跨日须复核。
    """
    if is_micro_degraded:
        return "⚠️ 【微观数据降级】高频分时与委托队列数据缺失，防伪审计未核验，风控严禁建仓！\n"
    # ★ 文案自洽：卡片跨日时不得再说「当日」，否则与 F-9 的「距今 N 天」自相矛盾。
    day_word = "生成日" if is_stale else "当日"
    return (
        f"⏱️ 【信号时效】本判定基于**{day_word}盘中微观切片**（主力阶段/聪明钱成本/筹码分布"
        f"均为日内横截面口径，非跨日沉淀成本），仅对{day_word}有效；"
        f"下一交易日须以新数据重新复核，不得跨日沿用（当前置信度 {mf_conf:.1f}%）\n"
    )


def _build_signal_staleness_note(trade_date: str | None) -> str:
    """F-9：信号 TTL —— 决断卡数据与当前日期跨日时，**微观结论显式降权**。

    ★ 微观资金面（主力阶段 / 聪明钱成本 / 筹码分布）是**日内横截面切片**，
      生命周期只有一个交易日。系统此前**完全没有**时效字段（四个核心文件
      检索 ``as_of`` / ``snapshot_time`` 命中数为 0），因此昨天的报告
      今天再看，仍是"无抵抗阴跌出清 → 坚决回避"的裸断言，没有任何提示
      告诉读者"这份已经过期了"。

    ★ 实现取舍：不引入交易日历（避免新增网络依赖与失败模式），仅比较
      自然日。跨 1 日即提示复核；跨 3 日及以上升级为"已失效"。
      基本面（财务/估值）**不受影响** —— 它本来就是低频数据。
    """
    if not trade_date:
        return ""
    today = _date.today()
    try:
        card_date = _date.fromisoformat(str(trade_date)[:10])
    except (TypeError, ValueError):
        return ""                                   # 日期不可解析 ⇒ 不臆断时效
    age_days = (today - card_date).days
    if age_days <= 0:
        return ""                                   # 当日数据，无需提示
    if age_days >= 3:
        return (
            f"🕒 【信号已失效】本卡基于 {card_date.isoformat()} 数据，距今 {age_days} 天；"
            f"主力阶段/聪明钱成本/筹码分布等微观结论**已过期失效**，"
            f"严禁据此交易，须以最新数据重跑（基本面与估值结论不受影响）\n"
        )
    return (
        f"🕒 【信号待复核】本卡基于 {card_date.isoformat()} 数据，距今 {age_days} 天；"
        f"微观资金面结论为日内切片，跨日后须以最新数据重新确认\n"
    )


def _normalize_pledge_pct(value: Any) -> float | None:
    """把质押率归一化为**百分数**；``None`` 表示未核验，原样返回 ``None``。

    ★ P1-3：严禁把未核验兜成 ``0.0`` —— 那会让质地五问 Q4 断言
      「质押率 0.0% 处于安全线内」，把「通道不可得」伪装成「确认无质押」，
      与采集层 ``eltdx_collector.get_f10_governance_and_concept`` 的
      None 纪律及 ``filter_audit`` 的 ``pledge_verified`` 口径直接冲突。

    ★ 口径说明：eltdx F10 **无股权质押通道**，当前恒为 ``None``。若未来接入，
      分数制（0.70）与百分数制（70.0）都可能出现；``0 < v <= 1`` 视为分数制，
      乘 100 归一。判据方向是保守的（只会多标风险，不会漏标）。
    """
    if value is None:
        return None
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    return v * 100.0 if 0.0 < v <= 1.0 else v


class JudgmentChainRunner:
    """A股实战因果作战决断引擎 (吸收 Ashare 严密判断链 + 本土微观主力与双轨实战决断)."""

    def __init__(self) -> None:
        self.validator = LintValidator()
        self.matrix_radar = CapitalMatrixRadar()
        self.playbook_builder = PlaybookBuilder()
        self.derived_calc = DerivedMetricsCalculator()

    def classify_stock_track(
        self,
        quote: dict[str, Any],
        ladder_info: dict[str, Any] | None,
        concepts: list[str],
    ) -> tuple[str, str]:
        """A股标的物种分流：超短题材连板 / 机构趋势中军 / 未核验(物种未定)。

        ★ P1-2 修复：兜底**不再**返回 B 轨「机构趋势与产业中军」。
          旧实现在这里无条件兜底成中军，导致 58.7 亿市值的永安行、甚至十几亿
          市值的边缘微盘股，只要缩量震荡就会被冠以「产业中军」头衔 ——
          而 B 轨在弱市享有「情绪防守」豁免，等于给无基本面支撑的小票
          开了拿到核心仓档位的后门。现改为显式 `TRACK_UNVERIFIED`。

        判定顺序（命中即返回，未命中即未核验）：
          1. 连板梯队 >= 2 板，或小市值题材龙头        -> A 轨
          2. 流通市值 >= 200 亿 或 总市值 >= 300 亿    -> B 轨
          3. 流通市值 < 150 亿 且 换手 >= 6% 或有概念   -> A 轨
          4. 其余（含 150~200 亿中盘但缩量无概念）      -> 未核验轨
        """
        circ_mv = quote.get("circ_mv", 0.0)
        total_mv = quote.get("total_mv", 0.0)
        is_leader = ladder_info.get("is_leader", False) if ladder_info else False
        board_level = ladder_info.get("board_level", 0) if ladder_info else 0
        turnover = quote.get("turnover_ratio", 0.0)

        # 1. 连板梯队 >= 2板，或者市值不大且是题材龙头 -> 短线题材接力
        if board_level >= 2 or (is_leader and circ_mv < 250e8):
            return TRACK_A_THEME, "短线题材与接力博弈"

        # 2. 流通市值 >= 200 亿，或总市值 >= 300 亿 -> 机构趋势与产业中军
        if circ_mv >= 200e8 or total_mv >= 300e8:
            return TRACK_B_INSTITUTIONAL, "机构趋势与产业中军"

        # 3. 市值偏小且高换手活跃
        if circ_mv < 150e8 and (turnover >= 6.0 or len(concepts) > 0):
            return TRACK_A_THEME, "短线题材与接力博弈"

        # 4. 兜底：既不属题材接力、又未达中军市值门槛 —— 判未核验，严禁冒充中军
        return TRACK_UNVERIFIED, "未核验(物种未定)"

    # =========================================================================
    # 模块化支柱构建方法 (委托至 core/pillars 独立构建器包)
    # =========================================================================

    def _build_pillar_1_quality(
        self,
        derived_data: dict[str, Any],
        flags: list[RedFlagItem],
        governance_info: dict[str, Any] | None,
        concept_list: list[str],
        is_fatal: bool,
        fatal_flags: list[RedFlagItem],
        data_health: dict[str, Any] | None,
        ai: dict[str, Any] | None = None,
        nodes: dict[str, Any] | None = None,
    ) -> tuple[str, str, list[dict[str, str]]]:
        ctx = SingleStockContext(
            ticker="", name="", trade_date="",
            flags=flags, governance_info=governance_info or {}, concepts=concept_list,
        )
        verdict = build_pillar_1_quality(
            ctx=ctx,
            derived_data=derived_data,
            flags=flags,
            governance_info=governance_info,
            concept_list=concept_list,
            is_fatal=is_fatal,
            fatal_flags=fatal_flags,
            data_health=data_health,
            ai=ai,
            nodes=nodes,
        )
        return verdict.pillar_text, verdict.verdict, verdict.sub_verdicts

    def _build_pillar_2_state(
        self,
        derived_data: dict[str, Any],
        concept_list: list[str],
        ladder_info: dict[str, Any] | None,
        mainbz_list: list[dict[str, Any]],
        ai: dict[str, Any] | None = None,
        nodes: dict[str, Any] | None = None,
    ) -> tuple[str, str, str, bool]:
        ctx = SingleStockContext(
            ticker="", name="", trade_date="",
            concepts=concept_list, ladder_info=ladder_info,
        )
        verdict = build_pillar_2_state(
            ctx=ctx,
            derived_data=derived_data,
            concept_list=concept_list,
            ladder_info=ladder_info,
            mainbz_list=mainbz_list,
            ai=ai,
            nodes=nodes,
        )
        return verdict.pillar_text, verdict.verdict, verdict.critical_wait, verdict.is_tech

    def _build_pillar_3_odds(
        self,
        price: float,
        total_shares_yi: float,
        pe_val: float,
        total_mv: float,
        derived_data: dict[str, Any],
        is_tech: bool,
        mainbz_list: list[dict[str, Any]],
        nodes: dict[str, Any] | None = None,
        industry_valuation: dict[str, Any] | None = None,
        is_fatal: bool = False,
    ) -> tuple[str, str, float, float, Any, Any, Any, bool]:
        ctx = SingleStockContext(
            ticker="", name="", trade_date="", industry_valuation=industry_valuation
        )
        ind_pe_median = (
            float(industry_valuation.get("pe_median"))
            if industry_valuation and industry_valuation.get("pe_median") is not None
            else None
        )
        verdict = build_pillar_3_odds(
            ctx=ctx,
            price=price,
            total_shares_yi=total_shares_yi,
            pe_val=pe_val,
            total_mv=total_mv,
            derived_data=derived_data,
            is_tech=is_tech,
            mainbz_list=mainbz_list,
            nodes=nodes,
            industry_pe_median=ind_pe_median,
            is_fatal=is_fatal,
        )
        return (
            verdict.pillar_text,
            verdict.verdict,
            verdict.sotp_ps,
            verdict.dcf_ps,
            verdict.derivation,
            verdict.anchor_range,
            verdict.reverse_dcf,
            verdict.ni_is_verified,
        )

    def _build_pillar_4_path(
        self,
        price: float,
        overhead_chips: float,
        sotp_ps: float,
        microstructure: dict[str, Any] | None,
        is_fatal: bool,
        trade_date: str | None = None,
        nodes: dict[str, Any] | None = None,
    ) -> tuple[str, str, bool, str, str, str, str | None, float, float, bool, float | None, float]:
        ctx = SingleStockContext(
            ticker="", name="", trade_date=trade_date or "",
            microstructure=microstructure or {},
        )
        verdict = build_pillar_4_path(
            ctx=ctx,
            price=price,
            overhead_chips=overhead_chips,
            sotp_ps=sotp_ps,
            microstructure=microstructure,
            is_fatal=is_fatal,
            trade_date=trade_date,
            nodes=nodes,
        )
        return (
            verdict.pillar_text,
            verdict.verdict,
            verdict.is_micro_degraded,
            verdict.mf_stage_code,
            verdict.mf_stage,
            verdict.mf_behavior,
            verdict.mf_override,
            verdict.mf_cap,
            verdict.mf_conf,
            verdict.is_trans,
            verdict.depth_to_sotp,
            verdict.profit_chip_pct,
        )

    def _decide_gear(
        self,
        price: float,
        state_verdict: str,
        odds_verdict: str,
        path_verdict: str,
        quality_verdict: str,
        is_fatal: bool,
        is_market_ice: bool,
        stock_track: str,
        macro_res: Any | None,
        mf_stage_code: str,
        mf_override: str | None,
        is_micro_degraded: bool,
        mf_cap: float | None,
        mf_confidence: float | None,
        left_tail_depth_pct: float | None,
        ni_is_verified: bool,
        fatal_flags: list[RedFlagItem],
        ladder_info: dict[str, Any] | None,
        ret_10d: float,
        is_gem_star: bool,
        is_bse: bool,
        overhead_chips: float,
        sotp_ps: float,
        ma5: float,
        ma20: float,
        support_lvl: float,
        resistance_lvl: float,
        critical_wait: str,
        microstructure: dict[str, Any] | None = None,
        nodes: dict[str, Any] | None = None,
        dcf_ps: float = 0.0,
    ) -> tuple[str, str, float, str, str, str, str]:
        ctx = SingleStockContext(
            ticker="", name="", trade_date="",
            quote={"close": price},
            ladder_info=ladder_info,
            microstructure=microstructure or {},
        )
        q_verdict = QualityVerdict(verdict=quality_verdict, pillar_text="", sub_verdicts=[], fatal_flags=fatal_flags, is_fatal=is_fatal)
        s_verdict = StateVerdict(verdict=state_verdict, pillar_text="", critical_wait=critical_wait, is_tech=False)
        o_verdict = OddsVerdict(verdict=odds_verdict, pillar_text="", sotp_ps=sotp_ps, dcf_ps=dcf_ps, derivation={}, anchor_range={}, reverse_dcf={}, ni_is_verified=ni_is_verified)
        p_verdict = PathVerdict(
            verdict=path_verdict, pillar_text="", is_micro_degraded=is_micro_degraded,
            mf_stage_code=mf_stage_code, mf_stage="", mf_behavior="", mf_override=mf_override,
            mf_cap=mf_cap, mf_conf=mf_confidence or 0.0, is_trans=False, depth_to_sotp=-(left_tail_depth_pct or 0.0),
            profit_chip_pct=0.0,
        )
        verdict = build_pillar_5_decision(
            ctx=ctx,
            q_verdict=q_verdict,
            s_verdict=s_verdict,
            o_verdict=o_verdict,
            p_verdict=p_verdict,
            stock_track=stock_track,
            is_market_ice=is_market_ice,
            macro_res=macro_res,
            ret_10d=ret_10d,
            is_gem_star=is_gem_star,
            is_bse=is_bse,
            overhead_chips=overhead_chips,
            ma5=ma5,
            ma20=ma20,
            support_lvl=support_lvl,
            resistance_lvl=resistance_lvl,
            nodes=nodes,
        )
        self._last_tactical_odds = verdict.tactical_odds
        return (
            verdict.decision_gear,
            verdict.decision_title,
            verdict.position_cap,
            verdict.core_contradiction,
            verdict.action_tactic,
            verdict.invalidation_line,
            verdict.regulatory_status,
        )

    def _assemble_and_lint_card(
        self,
        base_info: dict[str, Any],
        dash_and_pillars: dict[str, Any],
        decision_info: dict[str, Any],
        flags: list[RedFlagItem],
    ) -> dict[str, Any]:
        return assemble_and_lint_card(
            base_info=base_info,
            dash_and_pillars=dash_and_pillars,
            decision_info=decision_info,
            flags=flags,
            validator=self.validator,
        )

    # =========================================================================
    # 主流程编排器 (run) 降至 ~120 行高内聚装配
    # =========================================================================

    # ---------------------------------------------------------------- AI 判断层
    def _ai_enrich(
        self,
        ticker: str,
        name: str,
        derived_data: dict[str, Any],
        concept_list: list[str],
        mainbz_list: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """构建 AI 语义增强结果。**AI 未启用时返回空字典**，零开销、零副作用。

        ★ 只在 `analyze` 单股路径有意义 —— `screen` 全市场不得调用
          （会破坏 ≤15s 验收）。因此这里不并发，且受 `AI_TOTAL_BUDGET` 熔断。
        ★ 语料来自证据层公告池；取不到就给空证据，让 AI 依「无证据即弃权」自行弃权，
          **不伪造语料**。
        """
        import config as _cfg

        if not _cfg.AI_ENABLED:
            return {}

        from core.ai_coprocessor import enrich_many
        from core.ai_coprocessor.context import build_context

        # 上下文口径统一由 `ai_coprocessor.context` 负责：
        # cli.py 的 governance / theme_purity 用同一个 builder，
        # 否则两只模块会看到不同批公告，结论互相打脸却无从排查。
        ctx = build_context(
            ticker, name,
            concepts=concept_list,
            mainbz_list=mainbz_list,
            derived_data=derived_data,
        )
        result = enrich_many(ctx, ("moat", "catalyst"))
        return {k: v for k, v in result.items() if v is not None}

    # ═══════════════════════════════════════════════════════════════════
    # 判断链五节点：由**模型**产出判定（★ 与上面旧模块的纪律相反，勿混用）
    # ═══════════════════════════════════════════════════════════════════
    #
    # ★ 两套纪律并存，改动前先确认自己动的是哪一套：
    #   · `_ai_enrich` / `_ai_mainforce`（moat / catalyst / mainforce）：
    #     **AI 只能降级不能升级** —— AI 是**否决者**，
    #     最严重的后果仍由脚本红旗掌握（防一次幻觉毁掉整张卡）。
    #   · `_ai_nodes`（判断链 ①②③④⑤）：
    #     **AI 产出判定**，规则判定退为 fallback —— AI 是**分析师**。
    #
    # 两者共用同一套开关、机检与取值域闸门，但语义相反。
    # ═══════════════════════════════════════════════════════════════════

    @staticmethod
    def _kline_summary(daily_df: Any, price: float, ma5: float, ma20: float) -> str:
        """把日线压成一行位置摘要喂给模型（均线取自 momentum；日线按日期降序）。

        取不到就如实返回「（未提供）」—— 绝不伪造行情位置。
        """
        if daily_df is None or ma5 is None or ma20 is None:
            return "（未提供）"
        try:
            closes = daily_df.iloc[::-1]["close"].tolist()
            if not closes:
                return "（未提供）"
            lo, hi = min(closes), max(closes)
            pos = (price - lo) / (hi - lo) * 100.0 if hi > lo else 50.0
            return (
                f"现价 {price:.2f} / MA5 {ma5:.2f} / MA20 {ma20:.2f}；"
                f"区间 {lo:.2f}~{hi:.2f}，区间位置 {pos:.0f}%"
            )
        except Exception:                                    # noqa: BLE001
            return "（未提供）"

    def _ai_nodes(
        self,
        ticker: str,
        name: str,
        derived_data: dict[str, Any],
        quote: dict[str, Any],
        microstructure: dict[str, Any] | None,
        mainbz_list: list[dict[str, Any]] | None,
        flags: list[RedFlagItem],
        price: float,
        ma5: float,
        ma20: float,
        daily_df: Any | None = None,
        budget: float | None = None,
        evidence_package: Any | None = None,
        contradiction_inquiries: Any | None = None,
    ) -> dict[str, Any]:
        """判断链五节点判定层 —— ①②③④⑤ 的 verdict 由**模型**分析得出。

        ## 与 `_ai_enrich` 的根本差别

        `_ai_enrich` 让 AI 当**否决者**（只能降级）；这里让 AI 当**分析师**：
        模型读自己那份判据手册（`prompts/node_*.md`）与完整数据面板，
        自行拆解数据后给出 verdict **与推导过程**，规则判定**只作 fallback**。

        ## 失败语义

        AI 未启用 / 调用失败 / 节点弃权 → 返回空 dict 或该节点为 None，
        规则判定**原样生效**，输出与历史逐字一致。
        """
        import config as _cfg

        if not _cfg.AI_ENABLED:
            return {}
        try:
            from core.ai_coprocessor.context import build_node_context
            from core.ai_coprocessor.nodes import run_nodes
        except Exception as exc:                            # noqa: BLE001
            logger.warning("判断链节点模块不可用，回退规则判定: %s", exc)
            return {}

        extra_node_ctx: dict[str, Any] = {}
        if evidence_package is not None and hasattr(evidence_package, "format_for_prompt"):
            extra_node_ctx["evidence_package_text"] = evidence_package.format_for_prompt()
            extra_node_ctx["evidence_citations"] = "、".join(evidence_package.get_citation_tags())
        if contradiction_inquiries:
            extra_node_ctx["contradiction_inquiries_text"] = "\n".join(
                f"- {getattr(inq, 'id', '')} [{getattr(inq, 'category', '')}]: {getattr(inq, 'core_question', '')}"
                for inq in contradiction_inquiries
            )

        ctx = build_node_context(
            ticker, name,
            derived_data=derived_data,
            quote=quote,
            microstructure=microstructure or {},
            mainbz_list=mainbz_list or [],
            script_flags=flags,
            kline_summary=self._kline_summary(daily_df, price, ma5, ma20),
            peers=None,
            **extra_node_ctx,
        )
        try:
            res = run_nodes(ctx, budget=budget)
        except Exception as exc:                            # noqa: BLE001
            logger.warning("判断链节点调用失败，回退规则判定: %s", exc)
            return {}
        return {
            m: r for m, r in (res or {}).items()
            if r is not None and not r.abstained
        }

    @staticmethod
    def _node_verdict(nodes: dict[str, Any] | None, module: str) -> str | None:
        """取节点模型判定的 verdict；节点不可用/弃权/未启用时返回 None。"""
        if not nodes:
            return None
        r = nodes.get(module)
        if r is None:
            return None
        return getattr(r, "verdict", None) or None

    @staticmethod
    def _node_analysis(nodes: dict[str, Any] | None) -> dict[str, Any]:
        """汇总五节点的**推导产物**，上报告以证明「模型真的在分析」。

        这是可审计性的落点：估值推导 / 左尾清单 / 证伪清单 / 子判定 /
        封顶检查 / 裁决理由都在这里，而不是只留一个判定词。
        """
        out: dict[str, Any] = {}
        for m, r in (nodes or {}).items():
            if r is None:
                continue
            a = getattr(r, "analysis", None) or {}
            if a:
                out[m] = a
        return out

    @staticmethod
    def _merge_ai_nominations(flags: list[RedFlagItem], ai_map: dict[str, Any]) -> None:
        """把 AI 提名并入红旗池 —— **单向阀**：只能加风险。

        ★ 提名级别已被 `guard` 封顶（默认 🟠），因此 AI 永远无法直接触发
          致命封顶与清零仓位；最严重的后果仍由脚本红旗掌握。
        """
        from core.ai_coprocessor.guard import nominations_to_flags

        flags.extend(nominations_to_flags(ai_map))

    def _ai_mainforce(
        self,
        ticker: str,
        name: str,
        microstructure: dict[str, Any] | None,
        price: float,
        quote: dict[str, Any],
        ma5: float,
        ma20: float,
        overhead_chips: float,
    ) -> dict[str, Any]:
        """★ 主力阶段定性的**自洽性校验** —— 交给 AI 判断层（模块 `mainforce`）。

        ## 为什么不用硬编码规则

        阶段定性是否成立，取决于「其定义特征是否被当日证据否定」，
        而这必须结合**标的自身的基线**来权衡：
            15 亿成交额 —— 对 400 亿中盘股是明显放量，
                           对 2 万亿巨头则是极度萎缩；
            +7.44% 涨幅 —— 对日均振幅 2% 的大盘股是极端事件，
                           对日均振幅 8% 的小盘股只是日常噪音。
        绝对阈值在这类判断上**跨市值、跨波动特性不可比**，
        这正是上游「脚本算数值、LLM 做定性判断」分工里交给 LLM 的部分。

        ## 判据在哪

        写在 `core/ai_coprocessor/prompts/mainforce.md` —— 独立业务资产，
        与代码分离。本函数**不含任何判据**，只组装上下文并处理回退。

        ## 严守上游三条硬边界（见 `ai_coprocessor/guard.py`）

        1. AI 只能通过 `nominations`（红旗提名）影响结论 —— 单向阀，只加风险；
        2. AI 结论必须绑定具体指标作证据，**无引用即弃权**；
        3. 未启用 / 调用失败 / 弃权 → 返回 `{}`，规则判定原样生效（逐字一致）。
        """
        import config as _cfg

        if not _cfg.AI_ENABLED:
            return {}

        from core.ai_coprocessor import enrich
        from core.ai_coprocessor.context import build_context

        micro = microstructure or {}
        if not micro.get("main_force_stage"):
            return {}                      # 微观未核验时无从校验，直接弃权

        def _num(v: Any) -> str:
            return "（未提供）" if v in (None, "") else str(v)

        if price > max(ma5, ma20):
            ma_pos = "现价在双均线上方"
        elif price < min(ma5, ma20):
            ma_pos = "现价在双均线下方"
        else:
            ma_pos = "现价介于两均线之间"
        ma_relation = f"MA5 {ma5:.2f} / MA20 {ma20:.2f} / 现价 {price:.2f} —— {ma_pos}"

        ctx = build_context(
            ticker, name,
            stage_name=micro.get("main_force_stage"),
            confidence=_num(micro.get("main_force_confidence")),
            pct_chg=_num(quote.get("pct_chg")),
            price=f"{price:.2f}",
            smart_vwap=_num(micro.get("smart_vwap")),
            smart_buy_ratio=_num(micro.get("smart_buy_ratio")),
            smart_sell_ratio=_num(micro.get("smart_sell_ratio")),
            vol_ratio=_num(micro.get("vol_ratio_20d")),          # 相对自身均量
            avg_amplitude_5d=_num(micro.get("avg_amplitude_5d")),  # 自身波动基线
            price_position_60d=_num(micro.get("price_position_60d")),
            overhead_chips=_num(overhead_chips),
            ma_relation=ma_relation,
        )
        result = enrich("mainforce", ctx)
        return {"mainforce": result} if result is not None else {}

    def _ai_tactic(
        self,
        ticker: str,
        name: str,
        gear: str,
        seats: list[str],
        market_regime: str,
    ) -> dict[str, Any]:
        """情景战术的 AI 增强。**AI 未启用时返回空字典**。

        与 `moat` / `catalyst` 分开调用：情景研判发生在档位与游资画像确定
        **之后**，必须把 `gear` / `seats` / `market_regime` 一起喂进去。
        ★ 证据预算刻意更小 —— 情景分支看的是席位属性与大盘水温，不是长篇公告。
        """
        import config as _cfg

        if not _cfg.AI_ENABLED:
            return {}

        from core.ai_coprocessor import enrich
        from core.ai_coprocessor.context import build_context

        ctx = build_context(
            ticker, name,
            gear=gear,
            seats="、".join(seats or []) or "（未提供）",
            market_regime=market_regime or "（未提供）",
            evidence_limit=3,
        )
        result = enrich("tactic", ctx)
        return {"tactic": result} if result is not None else {}

    def run(
        self,
        ticker: str,
        name: str,
        trade_date: str,
        quote: dict[str, Any],
        momentum: dict[str, Any],
        flags: list[RedFlagItem],
        matched_youzi: list[dict[str, Any]],
        trap_warnings: list[str],
        matched_personas: list[dict[str, Any]] | None = None,
        concepts: list[str] | None = None,
        ladder_info: dict[str, Any] | None = None,
        sentiment_overview: Any | None = None,
        money_flow: dict[str, Any] | None = None,
        lhb_records: list[dict[str, Any]] | None = None,
        governance_info: dict[str, Any] | None = None,
        microstructure: dict[str, Any] | None = None,
        daily_df: Any | None = None,
        financial_reports: dict[str, Any] | None = None,
        data_health: dict[str, Any] | None = None,
        industry_valuation: dict[str, Any] | None = None,
        contradiction_inquiries: Any | None = None,
        evidence_package: Any | None = None,
    ) -> dict[str, Any]:
        """合成兼具 Ashare 深度投研严谨性与 A 股盘口微观实战性的全维决断卡。"""
        price = quote.get("close", 0.0)
        pct_chg = quote.get("pct_chg", 0.0)
        turnover = quote.get("turnover_ratio", 0.0)
        total_mv = quote.get("total_mv", 0.0)
        circ_mv = quote.get("circ_mv", 0.0)
        pe_val = quote.get("pe", 0.0)
        pb_val = quote.get("pb", 0.0)
        total_shares_yi = (
            quote.get("total_share", 0.0)
            or ((quote.get("total_mv") or quote.get("circ_mv") or 1e8) / price if price > 0 else 1e8)
        ) / 1e8
        if total_shares_yi <= 0:
            total_shares_yi = 1.0

        ma5 = momentum.get("ma5", price)
        ma20 = momentum.get("ma20", price)
        overhead_chips = momentum.get("overhead_chip_pct", 0.0)
        support_lvl = momentum.get("support_level", round(price * 0.95, 2))
        resistance_lvl = momentum.get("resistance_level", round(price * 1.05, 2))
        concept_list = concepts or []

        # ★ 20261029 审计 P1-12：原表漏了深市 302 与沪市 689 两个真实存在的代码段
        #   （与 screener/universe.board_class 的兜底前缀表保持一致）。
        is_gem_star = ticker.startswith(("300", "301", "302", "688", "689"))
        is_bse = ticker.startswith(("8", "4", "920"))
        board_name = "双创板 (20%涨跌停)" if is_gem_star else ("北交所 (30%涨跌停)" if is_bse else "主板 (10%涨跌停)")
        stock_track, track_name = self.classify_stock_track(quote, ladder_info, concept_list)

        ret_10d = 0.0
        if daily_df is not None and hasattr(daily_df, "empty") and not daily_df.empty and len(daily_df) >= 2:
            closes_asc = daily_df.iloc[::-1]["close"].reset_index(drop=True)
            c_latest = float(closes_asc.iloc[-1])
            c_10_ago = float(closes_asc.iloc[-min(10, len(closes_asc))])
            if c_10_ago > 0:
                ret_10d = round((c_latest - c_10_ago) / c_10_ago * 100.0, 1)

        fatal_flags = [f for f in flags if f.level == LEVEL_FATAL]
        is_fatal = len(fatal_flags) > 0

        is_market_ice = False
        p_gate = "未接入大盘连板情绪"
        macro_res = getattr(sentiment_overview, "macro_regime_result", None) if sentiment_overview else None
        if macro_res is not None:
            is_market_ice = not macro_res.is_gate_open
            p_gate = macro_res.gate_description
        elif sentiment_overview is not None:
            phase = getattr(sentiment_overview, "sentiment_phase", "未知")
            space = getattr(sentiment_overview, "space_board_level", 0)
            tickers = "、".join(getattr(sentiment_overview, "space_board_tickers", [])[:2]) or "无"
            zt_count = getattr(sentiment_overview, "total_limit_up_count", 0)
            dt_count = getattr(sentiment_overview, "total_limit_down_count", 0)
            bk_count = getattr(sentiment_overview, "total_broken_count", 0)
            bk_rate = getattr(sentiment_overview, "broken_rate_pct", 0.0)
            stats_str = f"涨停 {zt_count}家 / 跌停 {dt_count}家 / 炸板 {bk_count}家 (炸板率 {bk_rate:.1f}%)"
            if dt_count >= 15 or bk_rate >= 35.0 or phase in ("混沌冰点期", "退潮分歧期", "高位分歧期"):
                is_market_ice = True
                p_gate = f"⚠️ 情绪闸门收紧 (市场处于【{phase}】，空间板 {space}板 [{tickers}]，{stats_str}，后排亏钱效应扩散，短线防守控仓)"
            else:
                p_gate = f"✓ 情绪闸门放行 (市场处于【{phase}】，空间板 {space}板 [{tickers}]，{stats_str}，短线情绪具备赚钱效应)"

        # 0. 数据看板计算
        f_rep = financial_reports or {"income": pd.DataFrame(), "balance": pd.DataFrame(), "cashflow": pd.DataFrame()}
        mainbz_list = (governance_info or {}).get("main_business", [])
        derived_data = self.derived_calc.compute_metrics(
            income_df=f_rep.get("income", pd.DataFrame()),
            balance_df=f_rep.get("balance", pd.DataFrame()),
            cashflow_df=f_rep.get("cashflow", pd.DataFrame()),
            quote=quote,
            mainbz=mainbz_list,
        )
        dashboard = self.derived_calc.build_profitability_dashboard(derived_data, industry_name=track_name)

        # ─── AI 判断层接入点（默认关闭；关闭时零开销、输出与历史逐字一致）───
        # 放在 fatal_flags 之后：AI 提名已被封顶为非致命，绝不会改变回避判定。
        ai_map = self._ai_enrich(ticker, name, derived_data, concept_list, mainbz_list)
        # ★ 主力阶段定性的自洽性校验：须在阶段算出之后才能校验是否与证据矛盾。
        #   判据由 AI 读手册判断（prompts/mainforce.md），此处不含任何阈值。
        ai_map.update(self._ai_mainforce(
            ticker, name, microstructure, price, quote, ma5, ma20, overhead_chips))
        # ★ 判断链五节点：必须在 AI 提名并回 flags **之前**调用 ——
        #   这样喂给模型的 `script_flags` 是纯脚本机算红旗，AI 不会引用到自己的输出。
        node_map = self._ai_nodes(
            ticker, name, derived_data, quote, microstructure, mainbz_list,
            flags, price, ma5, ma20, daily_df,
            evidence_package=evidence_package,
            contradiction_inquiries=contradiction_inquiries,
        )
        if ai_map:
            self._merge_ai_nominations(flags, ai_map)

        # 1. 支柱 ❶ 质地
        p1_summary, quality_verdict, sub_verdicts_quality = self._build_pillar_1_quality(
            derived_data=derived_data,
            flags=flags,
            governance_info=governance_info,
            concept_list=concept_list,
            is_fatal=is_fatal,
            fatal_flags=fatal_flags,
            data_health=data_health,
            ai=ai_map,
            nodes=node_map,
        )

        # 2. 支柱 ❷ 状态
        p2_summary, state_verdict, critical_wait, is_tech = self._build_pillar_2_state(
            derived_data=derived_data,
            concept_list=concept_list,
            ladder_info=ladder_info,
            mainbz_list=mainbz_list,
            ai=ai_map,
            nodes=node_map,
        )

        # 3. 支柱 ❸ 赔率
        p3_summary, odds_verdict, sotp_ps, dcf_ps, deriv, anchor, rdcf, ni_is_verified = self._build_pillar_3_odds(
            price=price,
            total_shares_yi=total_shares_yi,
            pe_val=pe_val,
            total_mv=total_mv,
            derived_data=derived_data,
            is_tech=is_tech,
            mainbz_list=mainbz_list,
            nodes=node_map,
            industry_valuation=industry_valuation,
            is_fatal=is_fatal,
        )

        # 4. 支柱 ❹ 路径
        (
            p4_summary,
            path_verdict,
            is_micro_degraded,
            mf_stage_code,
            mf_stage,
            mf_behavior,
            mf_override,
            mf_cap,
            mf_conf,
            is_trans,
            depth_to_sotp,
            profit_chip_pct,
        ) = self._build_pillar_4_path(
            price=price,
            overhead_chips=overhead_chips,
            sotp_ps=sotp_ps,
            microstructure=microstructure,
            is_fatal=is_fatal,
            trade_date=trade_date,
            nodes=node_map,
        )

        # 5. 支柱 ❺ 决断与战术
        (
            decision_gear,
            decision_title,
            position_cap,
            core_contra,
            action_tactic,
            invalidation,
            reg_status_str,
        ) = self._decide_gear(
            price=price,
            state_verdict=state_verdict,
            odds_verdict=odds_verdict,
            path_verdict=path_verdict,
            quality_verdict=quality_verdict,
            is_fatal=is_fatal,
            is_market_ice=is_market_ice,
            stock_track=stock_track,
            macro_res=macro_res,
            mf_stage_code=mf_stage_code,
            mf_override=mf_override,
            is_micro_degraded=is_micro_degraded,
            mf_cap=mf_cap,
            # E-1 极端档裁决与 E-2 左尾腰斩所需入参
            mf_confidence=mf_conf,
            left_tail_depth_pct=_left_tail_depth_pct(depth_to_sotp),
            ni_is_verified=ni_is_verified,
            fatal_flags=fatal_flags,
            ladder_info=ladder_info,
            ret_10d=ret_10d,
            is_gem_star=is_gem_star,
            is_bse=is_bse,
            overhead_chips=overhead_chips,
            sotp_ps=sotp_ps,
            ma5=ma5,
            ma20=ma20,
            support_lvl=support_lvl,
            resistance_lvl=resistance_lvl,
            critical_wait=critical_wait,
            microstructure=microstructure,
            nodes=node_map,
            dcf_ps=dcf_ps or 0.0,
        )

        persona_names = [p.get("youzi_name", "") for p in (matched_personas or []) if isinstance(p, dict)]
        capital_matrix = self.matrix_radar.evaluate(
            quote=quote,
            momentum=momentum,
            flags=flags,
            trap_warnings=trap_warnings,
            matched_personas=persona_names,
            concepts=concept_list,
            ladder_info=ladder_info,
            money_flow=money_flow,
            lhb_records=lhb_records,
            governance_info=governance_info,
        )

        act_key = "BUY" if position_cap > 0.0 else ("AVOID" if is_avoid_gear(decision_gear) else "WAIT")
        tactic_ai = self._ai_tactic(ticker, name, decision_gear, persona_names, p_gate)
        playbook = self.playbook_builder.build(
            quote=quote,
            momentum=momentum,
            matched_personas=persona_names,
            action=act_key,
            ladder_info=ladder_info,
            fatal_flag=is_fatal,
            position_cap=position_cap,
            ai=tactic_ai,
            main_force_stage=mf_stage_code,
        )

        base_info = {
            "ticker": ticker,
            "name": name,
            "trade_date": trade_date,
            "price": price,
            "pct_chg": pct_chg,
            "total_mv": total_mv,
            "circ_mv": circ_mv,
            "turnover_ratio": turnover,
            "pe": pe_val,
            "pb": pb_val,
            "board_name": board_name,
            "stock_track": stock_track,
            "track_name": track_name,
            "data_health": data_health or {},
            # ★ 财务数据期次：报告头部的「数据截至 X 期」唯一来源。
            #   缺了它，读者无法分辨 23.7% 是 2025 年报还是 2026 三季报的毛利率。
            "period_basis": derived_data.get("period_basis", {}),
        }
        dash_and_pillars = {
            "profitability_dashboard": dashboard,
            "period_basis": derived_data.get("period_basis", {}),
            "pillar_1_quality": p1_summary,
            "pillar_2_state": p2_summary,
            "pillar_3_odds": p3_summary,
            "pillar_4_path": p4_summary,
            "pillar_5_decision": {
                "decision_gear": decision_gear,
                "decision_title": decision_title,
                "position_cap": position_cap,
                "triad_verdict": f"[{state_verdict} | {odds_verdict} | {path_verdict}]",
                "three_part_conclusion": format_three_part_conclusion(
                    quality_verdict, position_cap, odds_verdict
                ),
                "core_contradiction": core_contra,
                "action_tactic": action_tactic,
                "regulatory_status": reg_status_str,
                "invalidation_line": invalidation,
                "tactical_odds": getattr(self, "_last_tactical_odds", None),
            },
            "pillar_gate": p_gate,
            "pillar_business": p2_summary,
            "pillar_state": p2_summary,
            "pillar_tape": p3_summary,
            "pillar_odds": p3_summary,
            "pillar_flow": p4_summary,
            "pillar_path": p4_summary,
            "pillar_audit": p1_summary,
            "pillar_quality": p1_summary,
        }
        decision_info = {
            "decision_gear": decision_gear,
            "decision_title": decision_title,
            "position_cap": position_cap,
            "tactical_odds": getattr(self, "_last_tactical_odds", None),
            "core_contradiction": core_contra,
            "action_tactic": action_tactic,
            "invalidation_line": invalidation,
            "quality_verdict": quality_verdict,
            "state_verdict": state_verdict,
            "odds_verdict": odds_verdict,
            "path_verdict": path_verdict,
            "critical_wait": critical_wait,
            # ★ 模型推导过程 —— 可审计性落点：证明 verdict 是模型分析出来的，
            #   而不是规则套出来的。含估值推导 / 左尾清单 / 证伪清单 /
            #   子判定 / 封顶检查 / 裁决理由；AI 未启用时为空 dict。
            "ai_analysis": self._node_analysis(node_map),
            "ai_nodes_active": bool(node_map),
            "derivation": deriv,
            "anchor_range": anchor,
            "reverse_dcf": rdcf,
            "sub_verdicts_quality": sub_verdicts_quality,
            "capital_matrix": capital_matrix,
            "playbook": playbook,
            "top3_risks": [f.to_dict() for f in get_top3_risks(flags)],
            "all_flags": [f.to_dict() for f in flags],
            "matched_youzi": matched_youzi,
            "matched_personas": matched_personas or [],
            "trap_warnings": trap_warnings,
            "ladder_info": ladder_info,
            "microstructure": microstructure or {},
            "main_force_stage": mf_stage,
            "main_force_behavior": mf_behavior,
            "main_force_confidence": mf_conf,
            "is_transitional": is_trans,
            "main_force_risk": (microstructure or {}).get("main_force_risk", ""),
            "anti_spoofing_summary": (microstructure or {}).get("anti_spoofing_summary", []),
            "recommended_action": (microstructure or {}).get("recommended_action", "观望"),
            "contradiction_inquiries": [
                inq.to_dict() if hasattr(inq, "to_dict") else inq
                for inq in (contradiction_inquiries or [])
            ],
            "evidence_package": [
                s.to_dict() if hasattr(s, "to_dict") else s
                for s in (getattr(evidence_package, "snippets", []) if evidence_package else [])
            ],
            "evidence_citations": (
                list(evidence_package.get_citation_tags())
                if evidence_package and hasattr(evidence_package, "get_citation_tags") else []
            ),
        }

        return self._assemble_and_lint_card(base_info, dash_and_pillars, decision_info, flags)
