"""Assembler: 聚合全维决断卡，执行多 Agent 协议共识、Lint 机检与最终全篇研报总编审."""
from __future__ import annotations

import logging
from typing import Any
from core.red_flags import RedFlagItem, has_fatal_red_flags
from core.pillars.pillar5_decision import format_three_part_conclusion
from core.agents.consensus_engine import MultiAgentConsensusEngine
from core.agents.report_auditor import ReportAuditor
from lint.validator import LintValidator

logger = logging.getLogger("ast_trader.core.pillars.assembler")


def assemble_and_lint_card(
    base_info: dict[str, Any],
    dash_and_pillars: dict[str, Any],
    decision_info: dict[str, Any],
    flags: list[RedFlagItem],
    validator: LintValidator | None = None,
) -> dict[str, Any]:
    """聚合全维决断卡，经投决会 A2A 协议仲裁、Lint 质量机检与全篇总编审终审交付."""
    validator = validator or LintValidator()

    # 1. 投决会多智能体对抗共识 (彻底消灭虚假红旗与仓位矛盾)
    consensus_engine = MultiAgentConsensusEngine()
    consensus_res = consensus_engine.run_consensus(
        base_info=base_info,
        dash_and_pillars=dash_and_pillars,
        decision_info=decision_info,
        flags=flags,
    )
    clean_flags = consensus_res.clean_flags
    reconciled_dash = consensus_res.reconciled_dash_and_pillars
    reconciled_decision = consensus_res.reconciled_decision_info

    # 组装初始卡片
    card = {**base_info, **reconciled_dash, **reconciled_decision}
    card["all_flags"] = [f.to_dict() for f in clean_flags]
    card["consensus_certificate"] = consensus_res.consensus_certificate

    # 2. 机检校验与封顶硬锁死 (严格门控，非致命失败亦必须降级观察并清零仓位)
    ok, findings = validator.validate(card, clean_flags)
    card["lint_ok"] = ok
    card["lint_findings"] = findings
    if not ok:
        logger.warning(f"决断卡未通过 Lint 质量机检: {findings}")
        if has_fatal_red_flags(clean_flags):
            card["decision_gear"] = "回避"
            card["decision_title"] = "【🚫 致命排雷一票否决 (强制回避)】"
            card["position_cap"] = 0.0
        else:
            card["decision_gear"] = "等证据临界(观察)"
            card["decision_title"] = "【⚠️ 机检门控未通过 (强制观察)】"
            card["position_cap"] = 0.0
        if "pillar_5_decision" in card and isinstance(card["pillar_5_decision"], dict):
            card["pillar_5_decision"]["decision_gear"] = card["decision_gear"]
            card["pillar_5_decision"]["decision_title"] = card["decision_title"]
            card["pillar_5_decision"]["position_cap"] = card["position_cap"]
            card["pillar_5_decision"]["action_tactic"] = (
                f"• 机检拦截告警: 未通过 Lint 质量机检 ({'; '.join(findings)})，强制锁定零仓位观察防御！\n"
                + card["pillar_5_decision"].get("action_tactic", "")
            )
            card["pillar_5_decision"]["three_part_conclusion"] = format_three_part_conclusion(
                card.get("quality_verdict"),
                card["position_cap"],
                card.get("odds_verdict"),
                suffix="机检未通过",
            )

    # 3. 最终全篇研报总编审 (Report Auditor 终审与自然截断自愈)
    auditor = ReportAuditor()
    final_card = auditor.audit_and_heal_report(card)

    # 4. 股票分析假说自动登记归档 (Thesis Tracking)
    try:
        from core.evolution.thesis_tracker import ThesisTracker
        tracker = ThesisTracker()
        tracker.record_thesis(final_card)
    except Exception as exc:
        logger.debug(f"假说归档跳过: {exc}")

    return final_card
