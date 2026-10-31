"""Unit tests for AST-Trader audit engine and red flag detection (strictly aligned with Ashare & UZI)."""
from __future__ import annotations

import pandas as pd
import pytest

import config
from core.audit_engine import AuditEngine
from core.red_flags import LEVEL_FATAL, LEVEL_HIGH, LEVEL_LOW, get_top3_risks
from core.trap_detector import TrapDetector, detect_trap_signals


# =============================================================================
# 典型财务造假样本（合成数据 · 强化 SRS §8.1 验收）
#
# ⚠️ 数据性质声明：以下三表为**人工构造的合成数据**，不对应任何真实上市公司，
#    也不引用康美药业等真实案例的财报数值（仓库内无真实历史财报数据）。
#    构造目标是复现 A 股财务造假的**共性结构特征**：
#      1. 营收/净利润高增，但经营现金流由正转大幅为负（纸面富贵）；
#      2. 应收账款增速远超营收增速（放宽信用、激进确认收入）；
#      3. 存货同步堆积（配合虚假销售循环）；
#      4. 应计利润畸高（利润与现金流的背离达到 Sloan 异象水平）；
#      5. 杠杆抬升 + 商誉虚增（外延并购掩盖主业失血）。
#    因此本组用例只满足 SRS §8.1 的「部分」验收 —— 真实样本验证仍待数据接入。
# =============================================================================

FRAUD_BALANCE = [
    {"total_assets": 100.0, "total_cur_assets": 55.0, "total_cur_liab": 30.0,
     "accounts_receiv": 12.0, "inventories": 15.0, "fix_assets": 35.0,
     "goodwill": 0.0, "total_liab": 50.0, "undistr_profit": 20.0, "money_cap": 20.0},
    {"total_assets": 200.0, "total_cur_assets": 140.0, "total_cur_liab": 95.0,
     "accounts_receiv": 85.0, "inventories": 45.0, "fix_assets": 40.0,
     "goodwill": 30.0, "total_liab": 140.0, "undistr_profit": 35.0, "money_cap": 60.0},
]
FRAUD_INCOME = [
    {"revenue": 100.0, "oper_cost": 60.0, "operate_profit": 14.0, "n_income": 10.0,
     "sell_exp": 8.0, "admin_exp": 6.0},
    {"revenue": 180.0, "oper_cost": 95.0, "operate_profit": 40.0, "n_income": 30.0,
     "sell_exp": 9.0, "admin_exp": 7.0},
]
FRAUD_CASHFLOW = [
    {"n_cashflow_act": 12.0, "depreciation": 5.0},
    {"n_cashflow_act": -45.0, "depreciation": 6.0},
]


def _audit_fraud_sample():
    return AuditEngine().run_audit(
        balance_df=pd.DataFrame(FRAUD_BALANCE),
        cashflow_df=pd.DataFrame(FRAUD_CASHFLOW),
        income_df=pd.DataFrame(FRAUD_INCOME),
    )


def test_fraud_sample_triggers_beneish_fatal_with_threshold_assertion():
    """造假样本：Beneish M-Score 必须判致命，且得分写死超过 config 阈值。"""
    flags = _audit_fraud_sample()
    m_flags = [f for f in flags if f.framework == "Beneish M-Score"]

    assert m_flags, "造假样本未触发任何 Beneish M-Score 旗标"
    fatal = [f for f in m_flags if f.level == LEVEL_FATAL]
    assert fatal, f"造假样本未触发致命 Beneish 旗标，实际: {[f.level for f in m_flags]}"
    # 写死阈值：M-Score 必须严格超过 config.BENEISH_M_FATAL_SCORE
    assert float(fatal[0].value) > config.BENEISH_M_FATAL_SCORE


def test_fraud_sample_triggers_sloan_accrual_anomaly():
    """造假样本：应计异象（纸面富贵）必须被 Sloan 模型捕获。"""
    flags = _audit_fraud_sample()
    sloan = [f for f in flags if f.framework == "Sloan Accrual"]

    assert sloan, "造假样本未触发 Sloan 应计异象旗标"
    assert any(f.level in (LEVEL_FATAL, LEVEL_HIGH) for f in sloan)


def test_fraud_sample_triggers_receivable_and_inventory_divergence():
    """造假样本：应收与存货增速双双超出营收，Buffett 质量模型须同时告警。"""
    flags = _audit_fraud_sample()
    buffett = [f for f in flags if f.framework == "Buffett Quality"]
    titles = " ".join(f.title for f in buffett)

    assert "应收账款" in titles, "未识别应收账款增速远超营收"
    assert "存货" in titles, "未识别存货积压减值风险"


def test_fraud_sample_triggers_multi_framework_consensus():
    """造假样本：至少 3 个独立审计框架同时给出致命或高危，形成交叉印证。"""
    flags = _audit_fraud_sample()
    severe = {f.framework for f in flags if f.level in (LEVEL_FATAL, LEVEL_HIGH)}

    assert len(severe) >= 3, f"交叉印证不足，仅命中: {sorted(severe)}"
    assert "Beneish M-Score" in severe
    assert "Sloan Accrual" in severe


def test_healthy_sample_does_not_trigger_beneish_fatal():
    """反向对照：健康样本（现金流与利润匹配）不得被误判为财务操纵。"""
    bs = [
        {"total_assets": 100.0, "total_cur_assets": 55.0, "total_cur_liab": 30.0,
         "accounts_receiv": 12.0, "inventories": 15.0, "fix_assets": 35.0,
         "goodwill": 0.0, "total_liab": 50.0, "undistr_profit": 20.0, "money_cap": 20.0},
        {"total_assets": 110.0, "total_cur_assets": 60.0, "total_cur_liab": 31.0,
         "accounts_receiv": 13.0, "inventories": 16.0, "fix_assets": 36.0,
         "goodwill": 0.0, "total_liab": 52.0, "undistr_profit": 26.0, "money_cap": 24.0},
    ]
    inc = [
        {"revenue": 100.0, "oper_cost": 60.0, "operate_profit": 14.0, "n_income": 10.0,
         "sell_exp": 8.0, "admin_exp": 6.0},
        {"revenue": 108.0, "oper_cost": 65.0, "operate_profit": 15.0, "n_income": 11.0,
         "sell_exp": 8.0, "admin_exp": 6.0},
    ]
    cf = [
        {"n_cashflow_act": 12.0, "depreciation": 5.0},
        {"n_cashflow_act": 13.0, "depreciation": 5.5},
    ]
    flags = AuditEngine().run_audit(
        balance_df=pd.DataFrame(bs),
        cashflow_df=pd.DataFrame(cf),
        income_df=pd.DataFrame(inc),
    )
    m_flags = [f for f in flags if f.framework == "Beneish M-Score"]

    assert not any(f.level == LEVEL_FATAL for f in m_flags), "健康样本被误判为财务操纵"


def test_beneish_m_score_fraud_detection():
    """测试 Beneish M-Score 对高应收、虚增营收的造假检出率。"""
    engine = AuditEngine()
    bs_data = [
        {"total_assets": 100.0, "total_cur_assets": 80.0, "accounts_receiv": 20.0, "fix_assets": 20.0, "total_liab": 50.0},
        {"total_assets": 120.0, "total_cur_assets": 100.0, "accounts_receiv": 80.0, "fix_assets": 20.0, "total_liab": 80.0},
    ]
    inc_data = [
        {"revenue": 100.0, "oper_cost": 60.0, "n_income": 20.0},
        {"revenue": 110.0, "oper_cost": 40.0, "n_income": 50.0},
    ]
    cf_data = [
        {"n_cashflow_act": 15.0},
        {"n_cashflow_act": -30.0},
    ]

    flags = engine.run_audit(
        balance_df=pd.DataFrame(bs_data),
        cashflow_df=pd.DataFrame(cf_data),
        income_df=pd.DataFrame(inc_data),
    )
    m_flags = [f for f in flags if f.framework == "Beneish M-Score"]
    assert len(m_flags) > 0
    assert any(f.level in (LEVEL_FATAL, LEVEL_HIGH) for f in m_flags)


def test_piotroski_f_score():
    """测试 Piotroski F-Score 9 签号健康度评分。"""
    engine = AuditEngine()
    # 恶化数据: 净利润亏损、现金流为负、资产负债率上升、流动比率下降
    bs_data = [
        {"total_assets": 100.0, "total_cur_assets": 50.0, "total_cur_liab": 20.0, "total_liab": 30.0},
        {"total_assets": 100.0, "total_cur_assets": 30.0, "total_cur_liab": 40.0, "total_liab": 60.0},
    ]
    inc_data = [
        {"revenue": 100.0, "oper_cost": 50.0, "n_income": 10.0},
        {"revenue": 80.0, "oper_cost": 60.0, "n_income": -10.0},
    ]
    cf_data = [
        {"n_cashflow_act": 15.0},
        {"n_cashflow_act": -20.0},
    ]
    flags = engine.run_audit(
        balance_df=pd.DataFrame(bs_data),
        cashflow_df=pd.DataFrame(cf_data),
        income_df=pd.DataFrame(inc_data),
    )
    f_flags = [f for f in flags if f.framework == "Piotroski F-Score"]
    assert len(f_flags) >= 1
    assert f_flags[0].level == LEVEL_HIGH


def test_dupont_roe_collapse():
    """测试 DuPont ROE 暴跌 > 10pp 触发 🟠 高危红旗 (业务周期性波动不升格为退市致命红旗)。"""
    engine = AuditEngine()
    bs_data = [
        {"total_assets": 100.0, "total_hldr_eqy_exc_min_int": 80.0},
        {"total_assets": 100.0, "total_hldr_eqy_exc_min_int": 80.0},
    ]
    inc_data = [
        {"revenue": 100.0, "n_income": 20.0},  # 上期 ROE = 20 / 80 = 25%
        {"revenue": 100.0, "n_income": 5.0},   # 本期 ROE = 5 / 80 = 6.25% (暴跌 18.75pp)
    ]
    flags = engine.run_audit(
        balance_df=pd.DataFrame(bs_data),
        cashflow_df=pd.DataFrame(),
        income_df=pd.DataFrame(inc_data),
    )
    dp_flags = [f for f in flags if f.framework == "DuPont"]
    assert len(dp_flags) == 1
    assert dp_flags[0].level == LEVEL_HIGH


def test_buffett_scissors_gap():
    """测试巴菲特质量检查中应收账款增速远超营收增速的剪刀差。"""
    engine = AuditEngine()
    bs_data = [
        {"total_assets": 100.0, "total_hldr_eqy_exc_min_int": 50.0, "accounts_receiv": 20.0, "inventories": 10.0},
        {"total_assets": 120.0, "total_hldr_eqy_exc_min_int": 50.0, "accounts_receiv": 35.0, "inventories": 10.0},
    ]
    inc_data = [
        {"revenue": 100.0, "n_income": 10.0, "operate_profit": 10.0, "total_profit": 10.0},
        {"revenue": 110.0, "n_income": 12.0, "operate_profit": 12.0, "total_profit": 12.0},
    ]
    cf_data = [
        {"n_cashflow_act": 10.0},
        {"n_cashflow_act": 10.0},
    ]
    flags = engine.run_audit(
        balance_df=pd.DataFrame(bs_data),
        cashflow_df=pd.DataFrame(cf_data),
        income_df=pd.DataFrame(inc_data),
    )
    buff_flags = [f for f in flags if f.framework == "Buffett Quality" and "应收账款增速" in f.title]
    assert len(buff_flags) == 1
    assert buff_flags[0].level == LEVEL_HIGH


def test_governance_fatal_pledge():
    """测试大股东高质押触发 🔴 致命红旗。"""
    engine = AuditEngine()
    gov_info = {"pledge_ratio": 0.85, "has_reduction_plan": True}
    flags = engine.run_audit(
        balance_df=pd.DataFrame(),
        cashflow_df=pd.DataFrame(),
        income_df=pd.DataFrame(),
        governance_info=gov_info,
    )
    fatal = [f for f in flags if f.level == LEVEL_FATAL]
    assert len(fatal) == 1
    assert "质押" in fatal[0].title


def test_altman_z_score_distress():
    """测试 Altman Z-Score 困境预警。"""
    engine = AuditEngine()
    # ★ 20261029 审计 P0-3：权益必须用生产真实键 ``total_hldr_eqy_inc_min_int``
    #   （旧 fixture 写 ``total_equity``，那是生产 balance 永远不会产生的键名，
    #   导致 Altman 的 MV 兜底恒退化为 1.0，测试通过却从未真正测过 Z 分口径）。
    bs_data = [
        {"total_assets": 100.0, "total_cur_assets": 10.0, "total_cur_liab": 80.0, "total_liab": 90.0, "undistr_profit": -50.0, "total_hldr_eqy_inc_min_int": 10.0}
    ]
    inc_data = [{"revenue": 20.0, "operate_profit": -30.0}]
    flags = engine.run_audit(
        balance_df=pd.DataFrame(bs_data),
        cashflow_df=pd.DataFrame(),
        income_df=pd.DataFrame(inc_data),
    )
    z_flags = [f for f in flags if f.framework == "Altman Z-Score"]
    assert len(z_flags) == 1
    assert z_flags[0].level == LEVEL_FATAL


def test_goodwill_impairment_risk():
    """测试商誉占净资产超过 50% 触发致命红旗。"""
    engine = AuditEngine()
    bs_data = [{"total_assets": 200.0, "total_hldr_eqy_exc_min_int": 100.0, "goodwill": 60.0}]
    flags = engine.run_audit(
        balance_df=pd.DataFrame(bs_data),
        cashflow_df=pd.DataFrame(),
        income_df=pd.DataFrame(),
    )
    gw_flags = [f for f in flags if f.framework == "Buffett Quality" and "商誉" in f.title]
    assert len(gw_flags) == 1
    assert gw_flags[0].level == LEVEL_FATAL


def test_shareholder_dispersion_risk():
    """测试股东户数激增超过 20% 触发筹码发散预警。"""
    engine = AuditEngine()
    gov_info = {"holder_change_pct": 28.5}
    flags = engine.run_audit(
        balance_df=pd.DataFrame(),
        cashflow_df=pd.DataFrame(),
        income_df=pd.DataFrame(),
        governance_info=gov_info,
    )
    chip_flags = [f for f in flags if f.framework == "Shareholder Flow"]
    assert len(chip_flags) == 1
    assert chip_flags[0].level == LEVEL_HIGH


def test_forecast_anomaly_fatal_loss():
    """测试业绩预告首亏触发 🔴 致命红旗。"""
    engine = AuditEngine()
    gov_info = {
        "forecast": {
            "type": "首亏",
            "p_change_min": -150.0,
            "p_change_max": -120.0,
            "net_profit_min": -5000.0,
            "ann_date": "2026-07-15",
        }
    }
    flags = engine.run_audit(
        balance_df=pd.DataFrame(),
        cashflow_df=pd.DataFrame(),
        income_df=pd.DataFrame(),
        governance_info=gov_info,
    )
    fc_flags = [f for f in flags if f.framework == "Forecast Anomaly"]
    assert len(fc_flags) == 1
    assert fc_flags[0].level == LEVEL_FATAL
    assert "首亏" in fc_flags[0].title


def test_trap_detector_eight_signals():
    """测试杀猪盘 8 信号检测引擎。"""
    detector = TrapDetector()
    score, warnings = detector.evaluate(
        ticker="000001",
        concepts=["重大利好", "即将爆发", "老师带单", "VIP直播间"],
    )
    assert score <= 5
    assert len(warnings) >= 2


def test_top3_grouping_and_ranking():
    """测试基于 metric_refs 的风险分组与 Top3 杀伤力排序 (完全对齐 Ashare)。"""
    engine = AuditEngine()
    bs_data = [
        {"total_assets": 100.0, "total_hldr_eqy_exc_min_int": 50.0, "accounts_receiv": 20.0, "goodwill": 60.0},
        {"total_assets": 100.0, "total_hldr_eqy_exc_min_int": 50.0, "accounts_receiv": 40.0, "goodwill": 60.0},
    ]
    inc_data = [
        {"revenue": 100.0, "n_income": 20.0},
        {"revenue": 105.0, "n_income": 5.0},
    ]
    gov_info = {"pledge_ratio": 0.80}
    flags = engine.run_audit(
        balance_df=pd.DataFrame(bs_data),
        cashflow_df=pd.DataFrame(),
        income_df=pd.DataFrame(inc_data),
        governance_info=gov_info,
    )
    top3 = get_top3_risks(flags)
    assert len(top3) <= 3
    # 致命红旗必须排在最前 (质押或商誉或ROE崩塌)
    assert top3[0].level == LEVEL_FATAL


def test_high_cash_high_debt_fatal():
    """测试康美/康得新级别存贷双高致命红旗检测。"""
    engine = AuditEngine()
    bs_data = [
        {"total_assets": 1000.0e8, "money_cap": 300.0e8, "st_borr": 250.0e8, "non_cur_liab_due_1y": 50.0e8, "lt_borr": 0.0},
    ]
    inc_data = [
        {"fin_exp": 35.0e8, "operate_profit": 20.0e8, "n_income": 15.0e8},
    ]
    flags = engine.run_audit(
        balance_df=pd.DataFrame(bs_data),
        cashflow_df=pd.DataFrame(),
        income_df=pd.DataFrame(inc_data),
    )
    forensic_flags = [f for f in flags if f.framework == "Forensic Accounting" and "存贷双高" in f.title]
    assert len(forensic_flags) == 1
    assert forensic_flags[0].level == LEVEL_FATAL
    assert "存贷双高与财务费用严重侵蚀" in forensic_flags[0].title


def test_high_cash_high_debt_warn():
    """测试存贷双高关注预警 (未重度侵蚀但双高比例超20%)。"""
    engine = AuditEngine()
    bs_data = [
        {"total_assets": 1000.0e8, "money_cap": 220.0e8, "st_borr": 210.0e8, "non_cur_liab_due_1y": 0.0, "lt_borr": 0.0},
    ]
    inc_data = [
        {"fin_exp": 5.0e8, "operate_profit": 100.0e8, "n_income": 80.0e8},
    ]
    flags = engine.run_audit(
        balance_df=pd.DataFrame(bs_data),
        cashflow_df=pd.DataFrame(),
        income_df=pd.DataFrame(inc_data),
    )
    forensic_flags = [f for f in flags if f.framework == "Forensic Accounting" and "存贷双高" in f.title]
    assert len(forensic_flags) == 1
    assert forensic_flags[0].level == LEVEL_HIGH
    assert "结构性异常" in forensic_flags[0].title


def test_high_cash_high_debt_financial_industry_exemption():
    """测试金融银行业对存贷双高模型的主动豁免（避免将存贷款当成双高造假）。"""
    engine = AuditEngine()
    bs_data = [
        {"total_assets": 1000.0e8, "money_cap": 300.0e8, "st_borr": 300.0e8},
    ]
    flags = engine.run_audit(
        balance_df=pd.DataFrame(bs_data),
        cashflow_df=pd.DataFrame(),
        income_df=pd.DataFrame(),
        governance_info={"industry": "银行"},
    )
    forensic_flags = [f for f in flags if f.framework == "Forensic Accounting" and "存贷双高" in f.title]
    assert len(forensic_flags) == 0


def test_cip_stagnant_anomaly_high():
    """测试在建工程长期不转固与异常膨胀高危红旗。"""
    engine = AuditEngine()
    bs_data = [
        {"end_date": "20241231", "total_assets": 1000.0e8, "fix_assets": 300.0e8, "cip": 180.0e8},
        {"end_date": "20251231", "total_assets": 1100.0e8, "fix_assets": 310.0e8, "cip": 220.0e8},
    ]
    flags = engine.run_audit(
        balance_df=pd.DataFrame(bs_data),
        cashflow_df=pd.DataFrame(),
        income_df=pd.DataFrame(),
    )
    cip_flags = [f for f in flags if f.framework == "Forensic Accounting" and "在建工程" in f.title]
    assert len(cip_flags) == 1
    assert cip_flags[0].level == LEVEL_HIGH
    assert "在建工程长期不转固" in cip_flags[0].title


def test_cip_scale_warning_medium():
    """测试在建工程体量庞大预警。"""
    engine = AuditEngine()
    bs_data = [
        {"total_assets": 1200.0e8, "fix_assets": 500.0e8, "cip": 220.0e8},
    ]
    flags = engine.run_audit(
        balance_df=pd.DataFrame(bs_data),
        cashflow_df=pd.DataFrame(),
        income_df=pd.DataFrame(),
    )
    cip_flags = [f for f in flags if f.framework == "Forensic Accounting" and "在建工程" in f.title]
    assert len(cip_flags) == 1
    assert cip_flags[0].level == "🟡"
    assert "规模庞大" in cip_flags[0].title
