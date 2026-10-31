"""全市场链路的宏观闸门 —— 把大盘 regime 翻译成「今日是否交易 / 单票上限」。

★ 20261029 审计 P0-1：单股链路（`judgment_chain` → `pillar5_decision`）早已把宏观
  regime 接进决断卡（``is_market_ice`` → 情绪防守分支、仓位归零），而全市场链路
  只把 ``sentiment_overview`` 原样塞进结果体的 ``overview`` 字段 —— **从未据其
  约束任何输出**。大盘冰点/退潮时照样输出一屏「buyable」标的，两条链路风控口径
  不一致：同一天，单股报告说「严禁开仓」，全市场报告说「主升进场」。

闸门纪律（与单股链路对齐）：
  · 闸门关闭（退潮/冰点/极端背离）→ **今日不交易**：所有 buyable 动作改写为等待态，
    单票上限 0%，不输出进场剧本；
  · 闸门放行但处于投机期 → 单票上限减半；
  · 闸门**未核验**（macro_result 缺失）→ 不做约束，但**严禁视为已放行**，
    状态标 UNVERIFIED 并由调用方显式呈现（NFR-02：缺值不兜底）。
"""
from __future__ import annotations

import logging
from typing import Any, Iterable

import config

logger = logging.getLogger("ast_trader.screener.gate")

__all__ = [
    "SPECULATIVE_HALVE_REGIMES", "GATE_BLOCKED_ACTION", "GATE_BLOCKED_DESC",
    "single_name_cap_pct", "apply_macro_gate",
]

#: 投机期（单票上限减半）的短线生态标签 —— 与 `MacroRegimeEngine` 的
#: `SpeculativeMetrics.speculative_regime` 取值一一对应（core/macro_regime.py）。
SPECULATIVE_HALVE_REGIMES: frozenset[str] = frozenset({
    "弱市妖股逆势抱团 (流动性避险博傻)",
    "高位共振放量分歧 (筹码集中派发)",
})

#: 闸门收紧时，"可买"动作被改写成的新等待态（**不复用** wait_reseal 等既有态 ——
#:  那是"标的层面"的等待，这是"市场层面"的等待，混用会让归因无法区分）。
GATE_BLOCKED_ACTION = "wait_macro_gate"
GATE_BLOCKED_DESC = "大盘情绪闸门收紧 · 今日不交易（等待大盘企稳放行后再评估）"


def single_name_cap_pct(macro_result: Any | None) -> float | None:
    """单票仓位上限（百分数，如 20.0 表示 20%）。

    · 闸门关闭 → 0.0（今日不交易）；
    · 投机期 → 常规档的一半（``config.MAX_SINGLE_POSITION / 2``）；
    · 其余放行态 → 常规档；
    · 闸门未核验 → 0.0（★ Fail-Closed 安全兜底：大盘未核验时不给开仓额度，
      单票上限收紧为 0%，绝不冒进放行）。
    """
    if macro_result is None:
        return None

    base = float(config.MAX_SINGLE_POSITION) * 100.0
    if not getattr(macro_result, "is_gate_open", False):
        return 0.0
    if str(getattr(macro_result, "speculative_regime", "") or "") in SPECULATIVE_HALVE_REGIMES:
        return round(base / 2.0, 2)
    return round(base, 2)


def apply_macro_gate(
    picks: Iterable[dict[str, Any]],
    macro_result: Any | None,
) -> dict[str, Any]:
    """把宏观闸门落到**每一只入选标的**上，并返回闸门描述。

    就地改写 `picks`（与漏斗其余阶段的"打标"惯例一致）：
      · ``macro_gate_status``: OPEN / CLOSED / UNVERIFIED
      · ``macro_single_name_cap_pct``: 单票上限（未核验时不写）
      · 闸门关闭时：`action` 由 buyable → wait_macro_gate，`playbook` 置空
        （★ 剧本是"可买前提下怎么买"的方案，闸门收紧时输出挂单区间等于自相矛盾）
    """
    cap = single_name_cap_pct(macro_result)

    if macro_result is None:
        status = "UNVERIFIED"
        market_note = (
            "宏观闸门未核验（大盘 regime 缺失）：本次结果**未做**市场级约束，"
            "严禁视为『已放行』—— 请以单股链路的决断卡与人工研判为准。"
        )
        logger.warning("宏观闸门未核验：大盘 regime 缺失，全市场输出不做闸门约束（状态 UNVERIFIED）")
    elif not getattr(macro_result, "is_gate_open", False):
        status = "CLOSED"
        market_note = (
            f"【今日不交易】市场处于{macro_result.macro_regime_label}"
            f"（综合评分 {macro_result.composite_score:.0f}/100）："
            f"大盘情绪闸门收紧，全市场精选池仅作观察，禁止新建仓位。"
        )
        logger.warning(
            "宏观闸门收紧（%s / %s）：全部 buyable 动作改写为等待态",
            macro_result.macro_regime_label, macro_result.resonance_type,
        )
    else:
        status = "OPEN"
        market_note = (
            f"宏观闸门放行：市场处于{macro_result.macro_regime_label}"
            f"（综合评分 {macro_result.composite_score:.0f}/100）。"
        )

    blocked = status in ("CLOSED", "UNVERIFIED")
    rewritten = 0
    for p in picks:
        p["macro_gate_status"] = status
        if cap is not None:
            p["macro_single_name_cap_pct"] = cap
        if blocked:
            p["macro_gate_blocked"] = True
            if p.get("action") == "buyable":
                p["action"] = GATE_BLOCKED_ACTION
                p["action_desc"] = (
                    GATE_BLOCKED_DESC if status == "CLOSED" else
                    "大盘情绪闸门未核验 · 安全起见今日不新建仓位（等待大盘数据就绪后再评估）"
                )
                p["playbook"] = None
                rewritten += 1
            elif p.get("playbook") is not None:
                p["playbook"] = None
                if status == "CLOSED":
                    p["action_desc"] = GATE_BLOCKED_DESC
        elif cap is not None and p.get("playbook") is not None:
            pbk = p["playbook"]
            if isinstance(getattr(pbk, "max_position_pct", None), (int, float)) and pbk.max_position_pct > cap:
                pbk.max_position_pct = int(cap)
            if isinstance(getattr(pbk, "base_position_pct", None), (int, float)) and pbk.base_position_pct > cap:
                pbk.base_position_pct = int(cap)

    return {
        "status": status,
        "is_gate_open": None if macro_result is None else bool(macro_result.is_gate_open),
        "regime_label": None if macro_result is None else macro_result.macro_regime_label,
        "resonance_type": None if macro_result is None else macro_result.resonance_type,
        "composite_score": None if macro_result is None else macro_result.composite_score,
        "suggested_total_position_pct": (
            None if macro_result is None else macro_result.suggested_position_cap_pct
        ),
        "single_name_cap_pct": cap,
        "buyable_rewritten": rewritten,
        "gate_description": None if macro_result is None else macro_result.gate_description,
        "risk_warnings": [] if macro_result is None else list(macro_result.risk_warnings or []),
        "market_note": market_note,
    }
