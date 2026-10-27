"""Unit tests for Enhanced Five-Pillar Judgment Chain & Profitability Dashboard."""
from __future__ import annotations

import pandas as pd
import pytest

from core.derived_metrics import DerivedMetricsCalculator
from core.derivation import (
    check as check_derivation,
    generate_standard_derivation,
    render_sotp_table,
    render_dcf_table,
    render_discount_rate_table,
)
from core.judgment_chain import JudgmentChainRunner


def test_profitability_dashboard_and_sparkline():
    """验证首页「赚不赚钱」数据看板：生成 3-5 个核心指标，包含 trend 与 sparkline 序列。"""
    calc = DerivedMetricsCalculator()
    
    # 构造多期财务报表
    inc_df = pd.DataFrame([
        {"end_date": "20231231", "revenue": 10e8, "oper_cost": 7e8, "n_income_attr_p": 1.0e8, "operate_profit": 1.2e8},
        {"end_date": "20241231", "revenue": 13e8, "oper_cost": 8.5e8, "n_income_attr_p": 1.4e8, "operate_profit": 1.6e8},
        {"end_date": "20251231", "revenue": 17e8, "oper_cost": 10e8, "n_income_attr_p": 2.0e8, "operate_profit": 2.3e8},
    ])
    bs_df = pd.DataFrame([
        {"end_date": "20231231", "total_assets": 15e8, "total_liab": 6e8, "total_cur_assets": 8e8, "total_cur_liab": 4e8},
        {"end_date": "20241231", "total_assets": 18e8, "total_liab": 7e8, "total_cur_assets": 10e8, "total_cur_liab": 5e8},
        {"end_date": "20251231", "total_assets": 22e8, "total_liab": 8e8, "total_cur_assets": 12e8, "total_cur_liab": 5e8},
    ])
    cf_df = pd.DataFrame([
        {"end_date": "20231231", "n_cashflow_act": 1.2e8, "c_pay_acq_const_fiolta": 0.4e8, "net_profit": 1.0e8, "depr_fa_coga_dpba": 0.3e8},
        {"end_date": "20241231", "n_cashflow_act": 1.6e8, "c_pay_acq_const_fiolta": 0.5e8, "net_profit": 1.4e8, "depr_fa_coga_dpba": 0.4e8},
        {"end_date": "20251231", "n_cashflow_act": 2.4e8, "c_pay_acq_const_fiolta": 0.6e8, "net_profit": 2.0e8, "depr_fa_coga_dpba": 0.5e8},
    ])

    metrics = calc.compute_metrics(
        income_df=inc_df,
        balance_df=bs_df,
        cashflow_df=cf_df,
        quote={"total_mv": 50e8, "close": 20.0},
    )
    assert "gross_margin_latest" in metrics["profitability"]
    assert "roe_latest" in metrics["profitability"]

    dashboard = calc.build_profitability_dashboard(metrics, industry_name="电子制造")
    indicators = dashboard.get("indicators", [])
    assert 3 <= len(indicators) <= 5

    names = [i["name"] for i in indicators]
    assert any("毛利率" in n for n in names)
    assert any("现金含量" in n for n in names)
    assert any("ROE" in n for n in names)

    # 验证 sparkline 序列
    gm_ind = next(i for i in indicators if "毛利率" in i["name"])
    assert gm_ind["series"] is not None
    assert len(gm_ind["series"]["points"]) >= 3


def test_derivation_arithmetic_ten_checks():
    """验证赔率推导：P=F+N、SOTP 与 DCF 算术闭合机检全部通过。"""
    res = generate_standard_derivation(
        current_price=15.0,
        total_shares_yi=4.0,
        net_income_latest_yi=2.5,
        main_business=[{"name": "主业A", "ratio": 70.0}, {"name": "主业B", "ratio": 30.0}],
        is_growth=True,
    )
    derivation = res["derivation"]
    anchor_range = res["anchor_range"]
    current_price = res["current_price"]

    # 运行十条算术闭合机检
    errors = check_derivation(derivation, current_price=current_price, anchor_range=anchor_range)
    assert errors == [], f"算术闭合校验存在错误: {errors}"

    # 验证渲染表格函数
    sotp_tbl = render_sotp_table(derivation["sotp"])
    assert "主业A" in sotp_tbl
    assert "EV:" in sotp_tbl

    dcf_tbl = render_dcf_table(derivation["dcf"])
    assert "基准情景" in dcf_tbl
    assert "加权汇总" in dcf_tbl


def test_enhanced_pillar1_quality_five_questions():
    """验证支柱 ❶ 是不是好公司：质地五问契约、三态表与筛选信号。"""
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
        concepts=["商业连锁", "上海国企改革"],
        ladder_info={"theme_name": "零售", "board_level": 5, "leader_rank": 1},
        governance_info={"main_business": [{"name": "商业零售与物业租赁", "ratio": 85.2}]},
    )

    p1 = card.get("pillar_1_quality", "")
    assert "判定: 【" in p1
    assert "生意模式赚钱吗" in p1
    assert "赚钱质量真吗" in p1
    assert "护城河存在吗" in p1
    assert "管理层可信吗" in p1
    assert "财务底子稳吗" in p1
    assert "筛选信号，不进估值乘法" in p1


def test_enhanced_pillar2_state_lambda_and_critical_wait():
    """验证支柱 ❷ 在变好吗：λ 变好引擎、实锤/回声分级及全链唯一「该等什么」。"""
    runner = JudgmentChainRunner()
    card = runner.run(
        ticker="600838.SH",
        name="上海九百",
        trade_date="20261027",
        quote={"close": 13.31, "pct_chg": 10.0, "amount": 3.9e8, "circ_mv": 53.4e8, "total_mv": 53.4e8},
        momentum={"is_bullish_ma": True, "ma5": 12.0, "ma20": 10.5},
        flags=[],
        matched_youzi=[],
        trap_warnings=[],
        concepts=["商业连锁", "国企改革", "重组"],
        ladder_info={"theme_name": "零售", "board_level": 5, "leader_rank": 1},
        governance_info={"main_business": [{"name": "商业零售", "ratio": 85.2}]},
    )

    p2 = card.get("pillar_2_state", "")
    assert "变好引擎 λ" in p2
    assert "身份定位" in p2
    assert "证据分级" in p2
    assert "无记忆性警示" in p2
    assert "全链唯一「该等什么」" in p2


def test_enhanced_pillar3_odds_p_f_n_and_reverse_dcf():
    """验证支柱 ❸ 贵不贵：P=F+N 叙事溢价拆解、反向 DCF 市场预期与 [SOTP, DCF] 双锚。"""
    runner = JudgmentChainRunner()
    card = runner.run(
        ticker="600838.SH",
        name="上海九百",
        trade_date="20261027",
        quote={"close": 13.31, "pct_chg": 10.0, "amount": 3.9e8, "circ_mv": 53.4e8, "total_mv": 53.4e8},
        momentum={"is_bullish_ma": True},
        flags=[],
        matched_youzi=[],
        trap_warnings=[],
    )

    p3 = card.get("pillar_3_odds", "")
    assert "P=F+N 叙事拆解" in p3
    assert "反向 DCF" in p3
    assert "合理价区间 [SOTP, DCF]" in p3
    assert "SOTP=" in p3
    assert "DCF=" in p3


def test_enhanced_pillar4_path_and_pillar5_decision():
    """验证支柱 ❹ 与 ❺：主力生命周期 7 阶段微观穿透、持币/持股双轨战术与 T+1 防线。"""
    runner = JudgmentChainRunner()
    card = runner.run(
        ticker="600838.SH",
        name="上海九百",
        trade_date="20261027",
        quote={"close": 13.31, "pct_chg": 10.0, "amount": 3.9e8, "circ_mv": 53.4e8, "total_mv": 53.4e8},
        momentum={"is_bullish_ma": True, "ma5": 12.0, "overhead_chip_pct": 0.6},
        flags=[],
        matched_youzi=[],
        trap_warnings=[],
        ladder_info={"theme_name": "零售", "board_level": 5, "leader_rank": 1},
        microstructure={
            "stage_code": "STAGE_5_EXHAUSTION_ACCELERATION",
            "main_force_stage": "【🚀 缩量加速赶顶期 (主升锁仓/严禁追高)】",
            "smart_vwap": 9.33,
            "smart_q": 0.88,
        },
    )

    p4 = card.get("pillar_4_path", "")
    assert "主力阶段" in p4
    assert "微观盘口防伪" in p4
    assert "筹码沉淀承载" in p4

    p5 = card.get("pillar_5_decision", {})
    tactic = p5.get("action_tactic", "")
    inv = p5.get("invalidation_line", "")

    assert "持币者" in tactic
    assert "持股者" in tactic
    assert "9:25" in tactic or "竞价" in tactic
    assert "生命线" in inv or "防线" in inv or "止损" in inv
