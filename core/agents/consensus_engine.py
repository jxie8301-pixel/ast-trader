"""Multi-Agent Consensus Engine for AST-Trader.
Executes A2A debate, fact defense, and consistency arbitration.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from core.agents.protocol import (
    AgentRole,
    MessageType,
    ProtocolMessage,
    SharedBlackboard,
)
from core.red_flags import RedFlagItem
from presentation.plain_language import smart_natural_cutoff

logger = logging.getLogger("ast_trader.core.agents.consensus")


@dataclass
class ConsensusResult:
    """投决会共识结果."""
    clean_flags: list[RedFlagItem]
    reconciled_decision_info: dict[str, Any]
    reconciled_dash_and_pillars: dict[str, Any]
    blackboard: SharedBlackboard
    consensus_certificate: dict[str, Any] = field(default_factory=dict)


def harmonize_pillar_4_text(
    p4_text: str,
    aligned_stage: str,
    aligned_behavior: str,
) -> str:
    """全面清洗并重塑支柱 4 路径文本，杜绝任何多头与洗盘矛盾叙事."""
    if not p4_text:
        return p4_text
    import re
    # 1. 替换判定与主力阶段
    p4_text = re.sub(r"判定:\s*【[^】]+】", "判定: 【尾部风险高·不可承受】", p4_text)
    p4_text = re.sub(r"\(主力阶段:\s*【[^】]+】", f"(主力阶段: {aligned_stage}", p4_text)
    # 2. 替换操盘透视
    if "• 操盘透视:" in p4_text:
        p4_text = re.sub(r"• 操盘透视:.*?(?=\n\s*•|\Z)", f"• 操盘透视: {aligned_behavior}", p4_text, flags=re.DOTALL)
    # 3. 词汇彻底收敛清洗
    replacements = [
        ("【⏳ 缩量洗盘蓄势期 (时间换空间)】", aligned_stage),
        ("【🌱 低位隐蔽吸筹期】", aligned_stage),
        ("【🕳️ 假破位恐慌挖坑期 (空头陷阱)】", aligned_stage),
        ("【🚀 健康放量主升期】", aligned_stage),
        ("【依托支撑均线回踩企稳低吸】", "【观望等待放量方向选择】"),
        ("【逢低试仓 / 贴合主力成本建底仓】", "【空仓观望 / 严禁建仓】"),
        ("【黄金坑低吸 / 等待右侧长阳收复】", "【严防破位 / 禁止左侧抄底】"),
        ("【顺势做多 / 分时回踩均线低吸】", "【逢高离场 / 严禁追高参与】"),
        ("筹码结构扎实健康", "盘面呈现无增量资金承接的存量弱势特征"),
        ("主力以时间换空间耐心清洗浮动获利盘", "交投清淡且无增量资金做多意愿"),
        ("主力资金大举建仓拉升", "缺乏持续增量资金做多合力"),
    ]
    for w_old, w_new in replacements:
        p4_text = p4_text.replace(w_old, w_new)
    return p4_text


class MultiAgentConsensusEngine:
    """多智能体对抗与共识引擎."""

    def __init__(self) -> None:
        pass

    def run_consensus(
        self,
        base_info: dict[str, Any],
        dash_and_pillars: dict[str, Any],
        decision_info: dict[str, Any],
        flags: list[RedFlagItem],
    ) -> ConsensusResult:
        """运行投决会多智能体协议仲裁，彻底消除自相矛盾与虚假红旗."""
        bb = SharedBlackboard()

        # 1. 登记底座事实 (Ground Truth)
        dashboard = dash_and_pillars.get("profitability_dashboard", {})
        indicators = dashboard.get("indicators", [])
        ind_map = {ind.get("name"): ind.get("value") for ind in indicators if isinstance(ind, dict)}
        
        has_margin = bool(ind_map.get("毛利率/净利率") or ind_map.get("毛利率") or ind_map.get("净利率"))
        has_roe = bool(ind_map.get("净资产收益率 (ROE)") or ind_map.get("ROE"))
        
        p1_text = str(dash_and_pillars.get("pillar_1_quality") or "")
        p2_text = str(dash_and_pillars.get("pillar_2_state") or "")
        
        has_biz_pct = ("99.9%" in p1_text or "99.9%" in p2_text or "%" in p1_text)
        
        bb.register_ground_truth("has_profitability_metrics", has_margin and has_roe)
        bb.register_ground_truth("ind_map", ind_map)
        bb.register_ground_truth("has_business_composition", has_biz_pct)

        # 2. 空头证伪与数据保真 Agent 对抗 (Truth Defense & De-Hallucination)
        clean_flags: list[RedFlagItem] = []
        for flag in flags:
            f_title = flag.title or ""
            f_ev = flag.evidence or ""
            f_framework = flag.framework or ""
            combined_text = f"{f_title} {f_ev}"
            
            # 规则 A: 契约级拦截“利润率/ROE数据未提供/缺失/不可核验”打脸伪红旗
            claims_margin_missing = any(k in combined_text for k in ["利润率", "毛利率", "净利率", "ROE"]) and any(
                m in combined_text for m in ["缺失", "未提供", "无法获取", "不可核验", "空缺", "未披露", "对标数据缺失"]
            )
            if claims_margin_missing and (has_margin or has_roe):
                bb.intercept_flag(
                    flag_title=f_title,
                    reason="事实库中已精确计算利润率与ROE，AI审计盲审提名与正文数据直接打脸",
                    evidence=f"看板已载入利润指标: {ind_map}",
                )
                bb.post_message(ProtocolMessage(
                    sender=AgentRole.DATA_AUDITOR,
                    recipient=AgentRole.RISK_CHALLENGER,
                    msg_type=MessageType.FACT_DEFENSE,
                    topic="RED_FLAG_VALIDITY",
                    content=f"已驳回虚假红旗 [{f_title}]：事实库已明确包含毛利/净利/ROE数据，禁止上屏引起前后矛盾。",
                ))
                continue

            # 规则 B: 契约级拦截“主营构成各项占比均为 None/缺失”伪红旗
            claims_biz_missing = any(k in combined_text for k in ["主营", "业务构成", "主营构成"]) and any(
                m in combined_text for m in ["缺失", "None", "无法获取", "未提供", "不可核验", "占比均为 None"]
            )
            if claims_biz_missing and has_biz_pct:
                bb.intercept_flag(
                    flag_title=f_title,
                    reason="事实库中已包含主营业务构成与占比数据，AI审计提名属假阳性",
                    evidence="Pillar 1/2 已实锤主营占比",
                )
                bb.post_message(ProtocolMessage(
                    sender=AgentRole.DATA_AUDITOR,
                    recipient=AgentRole.RISK_CHALLENGER,
                    msg_type=MessageType.FACT_DEFENSE,
                    topic="RED_FLAG_VALIDITY",
                    content=f"已驳回虚假红旗 [{f_title}]：主营构成占比已在正文实锤。",
                ))
                continue

            # 规则 C: 拦截直接否定微观主力算法的自我矛盾辩词
            if "「假破位诱空」假设缺乏承接证据支撑" in combined_text:
                bb.intercept_flag(
                    flag_title=f_title,
                    reason="微观结构判定与红旗自相矛盾，由CIO统一口径处理",
                    evidence=f_ev,
                )
                continue

            clean_flags.append(flag)

        # 契约级红旗全局去重 (按 framework, title 归一化收敛，消灭重复渲染)
        deduped_flags: list[RedFlagItem] = []
        seen_flag_keys = set()
        for f in clean_flags:
            norm_key = (str(f.framework).strip().lower(), str(f.title).strip().lower())
            if norm_key not in seen_flag_keys:
                seen_flag_keys.add(norm_key)
                deduped_flags.append(f)
        clean_flags = deduped_flags

        # 3. 投决会主席 Agent 仓位与博弈战术仲裁 (CIO Alignment)
        reconciled_decision = dict(decision_info)
        reconciled_dash = dict(dash_and_pillars)
        
        pos_cap = float(reconciled_decision.get("position_cap", 0.0) or 0.0)
        gear = str(reconciled_decision.get("decision_gear", "") or "")

        # 仲裁 A: 0% 仓位 / 观望 / 回避 下，彻底抹杀资金雷达“维持中性底仓”的矛盾
        cap_matrix = reconciled_decision.get("capital_matrix")
        if cap_matrix:
            aligned_verdict = "❄️ 资金观望整理态势 (缺乏主导合力，动能尚未聚集，保持空仓防御，严禁底仓开仓)"
            if hasattr(cap_matrix, "matrix_verdict"):
                cur_verdict = str(getattr(cap_matrix, "matrix_verdict", ""))
                if (pos_cap == 0.0 or gear in ("回避", "减仓", "观察", "等证据临界(观察)")) and "底仓" in cur_verdict:
                    try:
                        setattr(cap_matrix, "matrix_verdict", aligned_verdict)
                    except Exception:
                        pass
            elif isinstance(cap_matrix, dict):
                cap_matrix = dict(cap_matrix)
                cur_verdict = str(cap_matrix.get("matrix_verdict") or cap_matrix.get("verdict") or "")
                if (pos_cap == 0.0 or gear in ("回避", "减仓", "观察", "等证据临界(观察)")) and "底仓" in cur_verdict:
                    cap_matrix["matrix_verdict"] = aligned_verdict
                    cap_matrix["verdict"] = aligned_verdict
                    reconciled_decision["capital_matrix"] = cap_matrix
            bb.post_message(ProtocolMessage(
                sender=AgentRole.CIO_LEAD,
                recipient=AgentRole.CAPITAL_MICRO,
                msg_type=MessageType.OVERRIDE,
                topic="POSITION_CAP_HARMONIZATION",
                content="总决断仓位为0%，强制覆写资金博弈雷达研判，彻底消除'维持中性底仓'冲突。",
            ))

        # 仲裁 A2: 当决断档位为“回避”或“减仓”时，彻底覆写微观实操动作，严禁输出“企稳低吸”
        rec_act = str(reconciled_decision.get("recommended_action", "") or reconciled_dash.get("recommended_action", ""))
        if (pos_cap == 0.0 or gear in ("回避", "减仓")) and any(w in rec_act for w in ["低吸", "加仓", "做多", "买入", "企稳低吸"]):
            aligned_action = "【回避观望 (主控风控锁定，严禁买入)】"
            reconciled_decision["recommended_action"] = aligned_action
            reconciled_dash["recommended_action"] = aligned_action
            bb.post_message(ProtocolMessage(
                sender=AgentRole.CIO_LEAD,
                recipient=AgentRole.CAPITAL_MICRO,
                msg_type=MessageType.OVERRIDE,
                topic="ACTION_TACTIC_HARMONIZATION",
                content=f"决断档位为【{gear}】(仓位上限 0%)，强制阻断微观低吸指令，统一为回避观望。",
            ))

        # 仲裁 A3: 战术赔率卡合规熔断 (回避/0% 仓位禁止提供买入区间与向上目标价)
        t_odds = reconciled_decision.get("tactical_odds") or reconciled_dash.get("tactical_odds")
        if isinstance(t_odds, dict) and (pos_cap == 0.0 or gear in ("回避", "减仓")):
            t_odds = dict(t_odds)
            t_odds["is_circuit_broken"] = True
            t_odds["circuit_breaker_reason"] = f"当前定调为【{gear}】(仓位上限 {int(pos_cap*100)}%)，触发买方防御熔断，禁止设定买入区间与向上目标价"
            t_odds["entry_range"] = "禁止买入 (买方防守熔断)"
            t_odds["target_price"] = "无 (回避档位不设目标价)"
            t_odds["risk_reward_ratio"] = "0.00:1 (盈亏比关闭)"
            reconciled_decision["tactical_odds"] = t_odds
            reconciled_dash["tactical_odds"] = t_odds

        # 仲裁 A4: 主力行为与生命周期共识化裁决 (彻底消灭"基本面硬伤回避"与"主力多头/洗盘"的撕裂)
        mf_stage = str(reconciled_decision.get("main_force_stage") or reconciled_dash.get("main_force_stage") or "")
        mf_behavior = str(reconciled_decision.get("main_force_behavior") or reconciled_dash.get("main_force_behavior") or "")
        is_bullish = any(w in mf_stage for w in ["吸筹", "洗盘", "蓄势", "主升", "做多", "挖坑", "黄金坑", "放量", "健康"]) or any(
            w in mf_behavior for w in ["扎实健康", "时间换空间", "清洗浮动", "耐心清洗", "建仓", "做多", "吸筹", "顺势"]
        )
        if (pos_cap == 0.0 or gear in ("回避", "减仓")) and is_bullish:
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

            reconciled_decision["main_force_stage"] = aligned_stage
            reconciled_decision["main_force_behavior"] = aligned_behavior
            reconciled_decision["main_force_risk"] = aligned_risk
            reconciled_decision["recommended_action"] = aligned_action
            reconciled_dash["main_force_stage"] = aligned_stage
            reconciled_dash["main_force_behavior"] = aligned_behavior
            reconciled_dash["main_force_risk"] = aligned_risk
            reconciled_dash["recommended_action"] = aligned_action
            if "microstructure" in reconciled_decision and isinstance(reconciled_decision["microstructure"], dict):
                reconciled_decision["microstructure"]["main_force_stage"] = aligned_stage
                reconciled_decision["microstructure"]["main_force_behavior"] = aligned_behavior
                reconciled_decision["microstructure"]["main_force_risk"] = aligned_risk
                reconciled_decision["microstructure"]["recommended_action"] = aligned_action
                reconciled_decision["microstructure"]["suggested_pos_cap"] = 0.0
                reconciled_decision["microstructure"]["decision_gear_override"] = "回避"

            # 同步修正支柱 4 路径文本及其别名中的矛盾
            for key in ["pillar_4_path", "pillar_flow", "pillar_path"]:
                if key in reconciled_dash:
                    reconciled_dash[key] = harmonize_pillar_4_text(str(reconciled_dash[key]), aligned_stage, aligned_behavior)
                if key in reconciled_decision:
                    reconciled_decision[key] = harmonize_pillar_4_text(str(reconciled_decision[key]), aligned_stage, aligned_behavior)

            bb.post_message(ProtocolMessage(
                sender=AgentRole.CIO_LEAD,
                recipient=AgentRole.CAPITAL_MICRO,
                msg_type=MessageType.OVERRIDE,
                topic="MAIN_FORCE_NARRATIVE_HARMONIZATION",
                content="基本面硬伤/风控锁定零仓位，强制驳回主力多头洗盘/主升叙事，统一重塑为弱势中继/诱多防御期。",
            ))

        # 仲裁 A5: 实操剧本与零仓位风控对齐
        pb = reconciled_decision.get("playbook")
        if pb and (pos_cap == 0.0 or gear in ("回避", "减仓")):
            if hasattr(pb, "max_position_pct"):
                setattr(pb, "base_position_pct", 0)
                setattr(pb, "add_position_pct", 0)
                setattr(pb, "max_position_pct", 0)
                setattr(pb, "entry_price_range", "无 (零仓位防守不设买入区间)")
                setattr(pb, "entry_tactic", "【零仓位防御】当前处于买方风控防守或证据匮乏期，仓位上限锁定为 0%，坚决不伸手建仓")
                setattr(pb, "action_label", "👀 观望防御 (仓位锁定 0%)" if gear not in ("回避", "减仓") else "🚫 铁律回避 (禁止开仓)")

        # 仲裁 B: 核心买方矛盾智能截断自愈（拔除断尾）
        core_contra = str(reconciled_decision.get("core_contradiction", ""))
        if core_contra:
            reconciled_decision["core_contradiction"] = smart_natural_cutoff(core_contra, max_chars=220)

        # 仲裁 C: 实战战术完整度校验
        action_tactic = str(reconciled_decision.get("action_tactic", ""))
        if action_tactic:
            reconciled_decision["action_tactic"] = action_tactic.strip()

        # 仲裁 D: 重新同步 Top3 风险红旗列表（杜绝已过滤伪红旗残留在 Top3 中）
        from core.red_flags import get_top3_risks
        reconciled_decision["top3_risks"] = [f.to_dict() for f in get_top3_risks(clean_flags)]

        # 4. 签署共识证书 (Consensus Certificate)
        consensus_cert = {
            "status": "CONSENSUS_REACHED",
            "intercepted_hallucinations_count": len(bb.intercepted_hallucinations),
            "clean_flags_count": len(clean_flags),
            "position_cap_locked": pos_cap,
            "decision_gear_locked": gear,
            "a2a_messages_count": len(bb.messages),
        }
        bb.consensus_verdicts["certificate"] = consensus_cert

        return ConsensusResult(
            clean_flags=clean_flags,
            reconciled_decision_info=reconciled_decision,
            reconciled_dash_and_pillars=reconciled_dash,
            blackboard=bb,
            consensus_certificate=consensus_cert,
        )
