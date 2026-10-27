"""Unit tests for Enhanced Pillars 2, 3, 4, 5 and Dual-Track Execution Playbook."""
from __future__ import annotations

import pandas as pd
import pytest

from core.judgment_chain import JudgmentChainRunner


def test_enhanced_pillar2_business_purity_and_catalyst():
    """验证支柱 ❷：能够穿透提取主营营收占比、催化溯源归因与梯队身位。"""
    runner = JudgmentChainRunner()
    card = runner.run(
        ticker="600838.SH",
        name="上海九百",
        trade_date="20261027",
        quote={"close": 13.31, "pct_chg": 10.0, "amount": 3.9e8, "circ_mv": 53.4e8, "total_mv": 53.4e8},
        momentum={"is_bullish_ma": True, "ma5": 12.0, "ma20": 10.5, "overhead_chip_pct": 0.5},
        flags=[],
        matched_youzi=[],
        trap_warnings=[],
        concepts=["商业连锁", "上海国企改革", "上海自贸区"],
        ladder_info={"theme_name": "零售", "board_level": 5, "leader_rank": 1, "theme_zt_count": 3, "seal_amount": 1.5e8, "limit_time": "09:30:15"},
        governance_info={"main_business": [{"name": "商业零售与物业租赁", "ratio": 85.2}]},
    )

    p2 = card.get("pillar_business", "")
    assert "核心主营" in p2
    assert "商业零售与物业租赁" in p2
    assert "85.2%" in p2
    assert "催化溯源" in p2
    assert "国企改革" in p2 or "重组" in p2
    assert "梯队身位" in p2
    assert "5板" in p2


def test_enhanced_pillar3_tape_and_sealing_quality():
    """验证支柱 ❸：能够量化封成比、盘封比、首封时效及筹码获利盘结构。"""
    runner = JudgmentChainRunner()
    card = runner.run(
        ticker="600838.SH",
        name="上海九百",
        trade_date="20261027",
        quote={"close": 13.31, "pct_chg": 10.0, "amount": 3.9e8, "circ_mv": 53.4e8, "total_mv": 53.4e8},
        momentum={"is_bullish_ma": True, "overhead_chip_pct": 0.6},
        flags=[],
        matched_youzi=[],
        trap_warnings=[],
        ladder_info={"theme_name": "零售", "board_level": 5, "leader_rank": 1, "seal_amount": 1.5e8, "limit_time": "09:30:15", "broken_count": 0},
    )

    p3 = card.get("pillar_tape", "")
    assert "封成比" in p3
    assert "占流通盘" in p3
    assert "09:30:15 秒封" in p3
    assert "获利盘高达 99.4%" in p3 or "全市场获利盘" in p3


def test_enhanced_pillar4_regulatory_margin_and_anti_spoofing_consistency():
    """验证支柱 ❹：精准测算 10 日严重异常波动监管余量，并屏蔽高位赶顶期出现的低吸字眼。"""
    # 构造 10 日暴涨数据
    closes = [8.0, 8.5, 9.35, 10.28, 11.31, 12.44, 13.31]
    rows = []
    for idx, c in enumerate(reversed(closes)):
        rows.append({"close": c, "amount": 3.5e8, "pct_chg": 10.0, "trade_date": f"202610{28-idx:02d}"})
    mock_daily = pd.DataFrame(rows)

    runner = JudgmentChainRunner()
    card = runner.run(
        ticker="600838.SH",
        name="上海九百",
        trade_date="20261027",
        quote={"close": 13.31, "pct_chg": 10.0, "amount": 3.9e8, "circ_mv": 53.4e8, "total_mv": 53.4e8},
        momentum={"is_bullish_ma": True, "overhead_chip_pct": 0.6},
        flags=[],
        matched_youzi=[],
        trap_warnings=[],
        ladder_info={"theme_name": "零售", "board_level": 5, "leader_rank": 1, "seal_amount": 1.5e8},
        microstructure={
            "stage_code": "STAGE_5_EXHAUSTION_ACCELERATION",
            "main_force_stage": "【🚀 缩量加速赶顶期 (主升锁仓/严禁追高)】",
            "smart_q": 0.930,
            "smart_vwap": 9.33,
            "anti_spoofing_summary": ["微观高频 Q 因子穿透表面中小单假象，识别主力正以算法拆单进行【主动低吸收集】"],
        },
        daily_df=mock_daily,
    )

    p4 = card.get("pillar_flow", "")
    assert "严重异常波动" in p4 or "监管红线" in p4
    # 验证上下文冲突已被清洗修正
    assert "主动低吸收集" not in p4
    assert "高位封单锁仓" in p4 or "大单扫货" in p4


def test_enhanced_pillar5_dual_red_flags():
    """验证支柱 ❺：严格排查在途减持计划、大股东质押率及估值纯度风险。"""
    runner = JudgmentChainRunner()
    card = runner.run(
        ticker="600838.SH",
        name="上海九百",
        trade_date="20261027",
        quote={"close": 13.31, "pct_chg": 10.0, "pe": 116.0, "amount": 3.9e8, "circ_mv": 53.4e8},
        momentum={"is_bullish_ma": True},
        flags=[],
        matched_youzi=[],
        trap_warnings=[],
        governance_info={"has_reduction_plan": True, "pledge_ratio": 0.0},
    )

    p5 = card.get("pillar_audit", "")
    assert "减持计划" in p5
    assert "质押率" in p5
    assert "估值风险" in p5 or "市盈率 PE(TTM) 116.0x" in p5


def test_enhanced_decision_dual_track_tactic_and_invalidation_line():
    """验证最终决断：输出双轨指引 (持币者 vs 持股者)，且 T+1 防线具备明确数值与分时触发条件。"""
    runner = JudgmentChainRunner()
    card = runner.run(
        ticker="600838.SH",
        name="上海九百",
        trade_date="20261027",
        quote={"close": 13.31, "pct_chg": 10.0, "pe": 116.0, "amount": 3.9e8, "circ_mv": 53.4e8},
        momentum={"is_bullish_ma": True, "ma5": 12.0, "overhead_chip_pct": 0.6},
        flags=[],
        matched_youzi=[],
        trap_warnings=[],
        ladder_info={"theme_name": "零售", "board_level": 5, "leader_rank": 1},
        microstructure={
            "stage_code": "STAGE_5_EXHAUSTION_ACCELERATION",
            "main_force_stage": "【🚀 缩量加速赶顶期 (主升锁仓/严禁追高)】",
            "smart_vwap": 9.33,
        },
    )

    tactic = card.get("action_tactic", "")
    inv = card.get("invalidation_line", "")

    # 验证双轨分流
    assert "持币者" in tactic
    assert "持股者" in tactic
    assert "9:25" in tactic or "竞价" in tactic
    assert "市价" in tactic or "清仓" in tactic

    # 验证非口号式的具体价格与分时防线
    assert "生命线" in inv or "退出线" in inv
    assert "元" in inv
    assert "分时" in inv or "跌破" in inv
