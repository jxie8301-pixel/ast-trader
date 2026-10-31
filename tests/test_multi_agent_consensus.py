"""Unit tests for Multi-Agent Consensus Protocol & Engine."""
from __future__ import annotations

from core.agents.consensus_engine import MultiAgentConsensusEngine
from core.agents.protocol import AgentRole, MessageType
from core.red_flags import RedFlagItem


def test_truth_defense_intercepts_margin_hallucination():
    """测试数据保真 Agent 成功拦截与事实打脸的虚假毛利率红旗."""
    engine = MultiAgentConsensusEngine()
    
    dash = {
        "profitability_dashboard": {
            "indicators": [
                {"name": "毛利率/净利率", "value": "21.8%"},
                {"name": "净资产收益率 (ROE)", "value": "13.4%"},
            ]
        },
        "pillar_1_quality": "毛利率 21.8% / 净利率 10.8%，核心主业金属结构制造业 占比 99.9%",
        "pillar_2_state": "营收增速加速",
    }
    decision = {
        "position_cap": 0.0,
        "decision_gear": "等证据临界(观察)",
        "capital_matrix": {"verdict": "❄️ 资金观望整理态势 (缺乏主导合力，动能尚未聚集，维持中性底仓)"},
    }
    
    # 构造两条典型的 AI 盲审虚假红旗
    hallucination_flag_1 = RedFlagItem(
        id="AI_MARGIN_MISSING",
        framework="AI 语义提名",
        level="🟠",
        title="利润率对标数据缺失，无法验证优于同行业标杆",
        value=None,
        threshold="—",
        evidence="输入中毛利率、净利率、ROE 均未提供，判据第 1 条在证据层面无法成立。",
        node="quality",
    )
    hallucination_flag_2 = RedFlagItem(
        id="AI_BIZ_MISSING",
        framework="AI 语义提名",
        level="🟡",
        title="主营构成多项占比缺失，存在小分部壁垒外溢风险",
        value=None,
        threshold="—",
        evidence="主营构成中各项占比均为 None，无法排除以单一分部壁垒为全公司背书的可能。",
        node="quality",
    )
    real_flag = RedFlagItem(
        id="REAL_CASH_WEAK",
        framework="硬指标排雷",
        level="🟡",
        title="自由现金流承压",
        value="-0.1%",
        threshold="<0",
        evidence="最新TTM自由现金流为负",
        node="quality",
    )
    
    result = engine.run_consensus(
        base_info={"ticker": "002850", "name": "科达利"},
        dash_and_pillars=dash,
        decision_info=decision,
        flags=[hallucination_flag_1, hallucination_flag_2, real_flag],
    )
    
    # 校验：两条虚假红旗被成功拦截销毁，只有真实红旗保留
    assert len(result.clean_flags) == 1
    assert result.clean_flags[0].id == "REAL_CASH_WEAK"
    assert len(result.blackboard.intercepted_hallucinations) == 2
    
    # 校验：资金雷达维持底仓被覆写为绝对同向空仓防御
    assert "维持中性底仓" not in result.reconciled_decision_info["capital_matrix"]["verdict"]
    assert "保持空仓防御，严禁底仓开仓" in result.reconciled_decision_info["capital_matrix"]["verdict"]
    
    # 校验共识证书
    assert result.consensus_certificate["status"] == "CONSENSUS_REACHED"
    assert result.consensus_certificate["intercepted_hallucinations_count"] == 2


def test_consensus_overrides_all_bullish_stages_under_avoid():
    """测试投决会共识裁决引擎：在回避/0%仓位下，无论微观此前误判为何种多头阶段，全篇必须深度调和统一."""
    engine = MultiAgentConsensusEngine()

    test_stages = [
        ("【🌱 低位隐蔽吸筹期】", "主力低位算法吸筹收集", "【逢低试仓 / 贴合主力成本建底仓】"),
        ("【🕳️ 假破位恐慌挖坑期 (空头陷阱)】", "主力刻意砸坑洗盘的假破位空头陷阱", "【黄金坑低吸 / 等待右侧长阳收复】"),
        ("【⏳ 缩量洗盘蓄势期 (时间换空间)】", "主力以时间换空间耐心清洗浮动获利盘，筹码结构扎实健康", "【依托支撑均线回踩企稳低吸】"),
        ("【🚀 健康放量主升期】", "主力放量拉升突破", "【顺势做多 / 分时回踩均线低吸】"),
    ]

    for stage, beh, act in test_stages:
        dash = {
            "pillar_4_path": f"判定: 【可承受】 (主力阶段: {stage}，置信度 85.0%)\n  • 操盘透视: {beh}",
            "pillar_flow": f"判定: 【可承受】 (主力阶段: {stage}，置信度 85.0%)\n  • 操盘透视: {beh}",
            "pillar_path": f"判定: 【可承受】 (主力阶段: {stage}，置信度 85.0%)\n  • 操盘透视: {beh}",
        }
        decision = {
            "position_cap": 0.0,
            "decision_gear": "回避",
            "main_force_stage": stage,
            "main_force_behavior": beh,
            "recommended_action": act,
            "microstructure": {
                "main_force_stage": stage,
                "main_force_behavior": beh,
                "recommended_action": act,
            },
        }

        res = engine.run_consensus(base_info={}, dash_and_pillars=dash, decision_info=decision, flags=[])
        reconciled_dec = res.reconciled_decision_info
        reconciled_dash = res.reconciled_dash_and_pillars

        # 决断层阶段必须被调和为弱势中继或派发诱多，绝不能残留原多头阶段名
        assert stage not in reconciled_dec["main_force_stage"]
        assert "洗盘" not in reconciled_dec["main_force_stage"]
        assert "吸筹" not in reconciled_dec["main_force_stage"]
        assert "主升" not in reconciled_dec["main_force_stage"]
        assert "低吸" not in reconciled_dec["recommended_action"]
        assert "做多" not in reconciled_dec["recommended_action"]

        # 支柱 4 及所有别名文本中必须彻底清除多头词汇与可承受判定
        for key in ["pillar_4_path", "pillar_flow", "pillar_path"]:
            p4_text = reconciled_dash[key]
            assert "判定: 【高尾险·不可承受】" in p4_text or "判定: 【尾部风险高·不可承受】" in p4_text
            assert stage not in p4_text
            assert "扎实健康" not in p4_text
            assert "清洗浮动获利盘" not in p4_text


def test_coaching_harmonized_under_avoid():
    """测试买方白话点拨条：在回避档位下，即使公司与价格技术性满足「好」，也坚决输出回避指令."""
    from presentation.plain_language import generate_plain_triad_coaching

    # 构造好公司+好价格但在风控下回避的场景
    card = {
        "decision_gear": "回避",
        "position_cap": 0.0,
        "three_part_conclusion": "好公司? 【是】 · 好下注? 【否】 · 好价格? 【是】",
        "all_flags": [{"severity": "FATAL", "title": "立案调查"}],
    }
    coaching = generate_plain_triad_coaching(card)
    assert "回避不碰" in coaching or "空仓回避" in coaching
    assert "建议先加入自选观察" not in coaching
    assert "吸筹洗盘" not in coaching

