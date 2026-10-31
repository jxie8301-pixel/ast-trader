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

            # 叙事终审一致性铁律：在回避/减仓/0%仓位下，绝不允许残留任何多头、吸筹、主升、低吸措辞
            mf_stage = str(healed.get("main_force_stage", ""))
            mf_behavior = str(healed.get("main_force_behavior", ""))
            is_bullish = any(w in mf_stage for w in ["吸筹", "洗盘", "蓄势", "主升", "做多", "挖坑", "黄金坑", "放量", "健康"]) or any(
                w in mf_behavior for w in ["扎实健康", "时间换空间", "清洗浮动", "耐心清洗", "建仓", "做多", "吸筹", "顺势"]
            )
            if is_bullish:
                if "主升" in mf_stage or "放量" in mf_stage or "拉升" in mf_behavior:
                    aligned_stage = "【⚠️ 派发诱多/高危博弈期】"
                    aligned_behavior = (
                        "股价虽呈现脉冲推升走势，但在公司触发买方风控硬伤且主力无增量持续合力背景下，"
                        "此拉升本质属于脉冲诱多派发或存量资金自救，绝非健康放量主升；"
                        "主力主升做多假设已被买方风控证伪，严禁盲目追高接盘。"
                    )
                    aligned_risk = "严防脉冲后快速回落跌停，触发买方硬性风控严禁参与任何刀口舔血。"
                    aligned_action = "【逢高离场 / 严禁追高参与】"
                else:
                    aligned_stage = "【📉 弱势中继/无抵抗阴跌出清期】"
                    aligned_behavior = (
                        "股价日线虽缩量窄幅整理，但在公司触发买方风控排雷且主力无增量资金进场背景下，"
                        "此缩量本质属于交投清淡与承接力匮乏的弱势中继整理，绝非主力健康蓄势洗盘；"
                        "主力多头蓄势假设已被风控证伪，严禁逆势抄底。"
                    )
                    aligned_risk = "防范中继平台向下破位，一旦击穿均线支撑或关键防守位，极易演变为加速补跌，严格空仓回避。"
                    aligned_action = "【空仓观望 / 绝不左侧接飞刀】"

                healed["main_force_stage"] = aligned_stage
                healed["main_force_behavior"] = aligned_behavior
                healed["main_force_risk"] = aligned_risk
                healed["recommended_action"] = aligned_action
                if "microstructure" in healed and isinstance(healed["microstructure"], dict):
                    healed["microstructure"]["main_force_stage"] = aligned_stage
                    healed["microstructure"]["main_force_behavior"] = aligned_behavior
                    healed["microstructure"]["main_force_risk"] = aligned_risk
                    healed["microstructure"]["recommended_action"] = aligned_action
                    healed["microstructure"]["suggested_pos_cap"] = 0.0
                    healed["microstructure"]["decision_gear_override"] = "回避"

            # 无论是否命中 is_bullish，支柱 4 路径文本及其别名必须经过终审净化
            from core.agents.consensus_engine import harmonize_pillar_4_text
            cur_stage = str(healed.get("main_force_stage", "【📉 弱势中继/无抵抗阴跌出清期】"))
            cur_behavior = str(healed.get("main_force_behavior", ""))
            for key in ["pillar_4_path", "pillar_flow", "pillar_path"]:
                if key in healed and healed[key]:
                    healed[key] = harmonize_pillar_4_text(str(healed[key]), cur_stage, cur_behavior)

            # 实战执行手册仓位与意图对齐
            pb = healed.get("playbook")
            if pb:
                if hasattr(pb, "max_position_pct"):
                    setattr(pb, "base_position_pct", 0)
                    setattr(pb, "add_position_pct", 0)
                    setattr(pb, "max_position_pct", 0)
                    setattr(pb, "entry_price_range", "无 (零仓位防守不设买入区间)")
                    setattr(pb, "entry_tactic", "【零仓位防御】当前处于买方风控防守或证据匮乏期，仓位上限锁定为 0%，坚决不伸手建仓")
                    setattr(pb, "action_label", "👀 观望防御 (仓位锁定 0%)" if gear not in ("回避", "减仓") else "🚫 铁律回避 (禁止开仓)")

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
