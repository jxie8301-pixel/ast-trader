"""Unit tests for AST-Trader audit engine and red flag detection."""
from __future__ import annotations

import pandas as pd
import pytest

from core.audit_engine import AuditEngine
from core.red_flags import LEVEL_FATAL, LEVEL_HIGH


def test_beneish_m_score_fraud_detection():
    """测试 Beneish M-Score 对高应收、虚增营收的造假检出率。"""
    engine = AuditEngine()

    # 构造虚构营收严重背离应收账款的造假数据
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
        {"n_cashflow_act": -30.0},  # 净利润 50 亿但现金流为负 30 亿
    ]

    flags = engine.run_audit(
        balance_df=pd.DataFrame(bs_data),
        cashflow_df=pd.DataFrame(cf_data),
        income_df=pd.DataFrame(inc_data),
    )

    # 必须检出致命红旗或高危红旗
    m_flags = [f for f in flags if f.framework == "Beneish M-Score"]
    assert len(m_flags) > 0
    assert any(f.level in (LEVEL_FATAL, LEVEL_HIGH) for f in m_flags)


def test_governance_fatal_pledge():
    """测试大股东高质押触发 🔴 致命红旗。"""
    engine = AuditEngine()
    gov_info = {
        "pledge_ratio": 0.85,  # 85% 质押
        "has_reduction_plan": True,
    }

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
    bs_data = [
        {"total_assets": 100.0, "total_cur_assets": 10.0, "total_cur_liab": 80.0, "total_liab": 90.0, "undistr_profit": -50.0, "total_equity": 10.0}
    ]
    inc_data = [
        {"revenue": 20.0, "operate_profit": -30.0}
    ]
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
    bs_data = [
        {"total_assets": 200.0, "total_equity": 100.0, "goodwill": 60.0}  # 商誉 60 亿，净资产 100 亿 (占比 60%)
    ]
    flags = engine.run_audit(
        balance_df=pd.DataFrame(bs_data),
        cashflow_df=pd.DataFrame(),
        income_df=pd.DataFrame(),
    )
    gw_flags = [f for f in flags if f.framework == "Asset Impairment"]
    assert len(gw_flags) == 1
    assert gw_flags[0].level == LEVEL_FATAL


def test_shareholder_dispersion_risk():
    """测试股东户数激增超过 20% 触发筹码发散预警。"""
    engine = AuditEngine()
    gov_info = {
        "holder_change_pct": 28.5,  # 环比增 28.5%
    }
    flags = engine.run_audit(
        balance_df=pd.DataFrame(),
        cashflow_df=pd.DataFrame(),
        income_df=pd.DataFrame(),
        governance_info=gov_info,
    )
    chip_flags = [f for f in flags if f.framework == "Shareholder Dispersion"]
    assert len(chip_flags) == 1
    assert chip_flags[0].level == LEVEL_HIGH
