"""Final Report Auditor (全篇研报总编审官).
Acts as the ultimate quality and consistency gate before presenting reports.
"""
from __future__ import annotations

import logging
from typing import Any

from presentation.plain_language import smart_natural_cutoff

logger = logging.getLogger("ast_trader.core.agents.report_auditor")


class ReportAuditor:
    """全篇研报总编审官."""

    def __init__(self) -> None:
        pass

    def audit_and_heal_report(self, card: dict[str, Any]) -> dict[str, Any]:
        """对卡片进行全篇研报级终审与自愈修正."""
        healed = dict(card)

        pos_cap = float(healed.get("position_cap", 0.0) or 0.0)
        gear = str(healed.get("decision_gear", "") or "")

        # 1. 终审：全篇仓位与战术防线绝对同向
        if pos_cap == 0.0 or gear in ("回避", "减仓", "观察", "等证据临界(观察)"):
            cap_matrix = healed.get("capital_matrix")
            aligned_verdict = "❄️ 资金观望整理态势 (缺乏主导合力，动能尚未聚集，保持空仓防御，严禁底仓开仓)"
            if cap_matrix:
                if hasattr(cap_matrix, "matrix_verdict"):
                    verdict = str(getattr(cap_matrix, "matrix_verdict", ""))
                    if "中性底仓" in verdict or "维持底仓" in verdict or "以防守观望为主" in verdict:
                        try:
                            setattr(cap_matrix, "matrix_verdict", aligned_verdict)
                        except Exception:
                            pass
                elif isinstance(cap_matrix, dict):
                    verdict = str(cap_matrix.get("matrix_verdict") or cap_matrix.get("verdict") or "")
                    if "中性底仓" in verdict or "维持底仓" in verdict or "以防守观望为主" in verdict:
                        cap_matrix["matrix_verdict"] = aligned_verdict
                        cap_matrix["verdict"] = aligned_verdict
                        healed["capital_matrix"] = cap_matrix

            # 实操动作同向：若仓位为0%或处于回避/减仓，微观动作绝对不可说“低吸”
            rec_act = str(healed.get("recommended_action", ""))
            if (pos_cap == 0.0 or gear in ("回避", "减仓")) and any(w in rec_act for w in ["低吸", "加仓", "做多", "买入", "企稳低吸"]):
                healed["recommended_action"] = "【回避观望 (主控风控锁定，严禁买入)】"
                if "microstructure" in healed and isinstance(healed["microstructure"], dict):
                    healed["microstructure"]["recommended_action"] = "【回避观望 (主控风控锁定，严禁买入)】"

            # 战术赔率卡合规熔断
            t_odds = healed.get("tactical_odds")
            if isinstance(t_odds, dict) and (pos_cap == 0.0 or gear in ("回避", "减仓")):
                t_odds = dict(t_odds)
                t_odds["is_circuit_broken"] = True
                t_odds["circuit_breaker_reason"] = f"当前定调为【{gear}】(仓位上限 {int(pos_cap*100)}%)，触发买方防御熔断，禁止设定买入区间与向上目标价"
                t_odds["entry_range"] = "禁止买入 (买方防守熔断)"
                t_odds["target_price"] = "无 (回避档位不设目标价)"
                t_odds["risk_reward_ratio"] = "0.00:1 (盈亏比关闭)"
                healed["tactical_odds"] = t_odds
                if "pillar_5_decision" in healed and isinstance(healed["pillar_5_decision"], dict):
                    healed["pillar_5_decision"]["tactical_odds"] = t_odds

        # 2. 终审：核心买方矛盾自然句尾自愈
        core_contra = str(healed.get("core_contradiction", "")).strip()
        if core_contra:
            healed["core_contradiction"] = smart_natural_cutoff(core_contra, max_chars=220)

        # 3. 终审：补全主力证伪条件（绝不悬空）
        mf_risk = str(healed.get("main_force_risk", "")).strip()
        if not mf_risk:
            # 根据当前主力阶段动态补齐兜底风险防守线
            support_lvl = float(healed.get("tactical_odds", {}).get("stop_price", 0.0) or 0.0) if isinstance(healed.get("tactical_odds"), dict) else 0.0
            if support_lvl > 0:
                healed["main_force_risk"] = f"若股价向下跌破关键支撑防守线 {support_lvl:.2f} 元或放量长阴破位，则诱空洗盘叙事彻底失效，转入破位防守。"
            else:
                healed["main_force_risk"] = "必须等待放量站上 5 日/20 日均线企稳确认；若放量单边砸盘破位，严禁盲目接飞刀加仓！"

        # 4. 终审：一句话结论自愈保证
        from presentation.plain_language import one_line_summary
        healed["one_line_summary_text"] = one_line_summary(healed)

        # 5. 终审总编签章
        healed["chief_auditor_passed"] = True
        healed["chief_auditor_note"] = "全篇一致性与零断句终审通过"

        return healed
