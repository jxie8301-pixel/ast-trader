"""C-5 测试围栏：锁定 audit_engine 四个模型在「字段缺失」下的**当前行为**。

为什么先建围栏
--------------
``core/audit_engine.py`` 的 Piotroski / Dupont / Buffett / InvestIncomeErosion
四个模型共 **22 行 23 处** ``or 0.0`` 兜底，把缺失财务字段静默填成 0，
是 NFR-02「缺失特征自动弃权、不伪装成有效信号」的欠账（已登记为
``docs/UNIMPLEMENTED_WORKLIST.md`` 的 C-5）。

本文件是改造的**第一步围栏**：先用具体固定断言把改造前的行为钉死，
再逐模块把 ``or 0.0`` 改成 None 语义。改造后若其中任何一条断言发生变化，
即为「红旗产出差异」，必须逐条解释后更新本文件。

★ 本文件已完成「围栏 → 改造 → 更新围栏」闭环：带「C-5 改造后」字样的用例断言
  **改造后的期望行为**，其中 Piotroski 用例的 docstring 保留了改造前后的差异说明。

字段缺失分布（实测，供改造时对照）
----------------------------------
* ``_check_piotroski``          :182 / :199 / :210  → 3 处
* ``_check_dupont``             :490 / :491 / :492 / :493 / :495 / :496 / :497 / :498 → 8 处
* ``_check_buffett_quality``    :549 / :550 / :569 / :574 / :595~:600 → 10 处
* ``_check_invest_income_erosion`` :671 → 1 行 2 处
* Beneish / Altman / Sloan / governance / valuation 等**实测无** ``or 0.0``，不在改造范围。
"""
from __future__ import annotations

import pandas as pd

from core.audit_engine import AuditEngine
from core.red_flags import LEVEL_HIGH, LEVEL_LOW

# ───────────────────────────────────────────────────────────── 构造样本
def _inc_full() -> pd.DataFrame:
    """两期完整利润表（良性增长样本）。"""
    return pd.DataFrame([
        {"end_date": "20241231", "revenue": 10e8, "oper_cost": 7e8,
         "n_income_attr_p": 1.0e8, "invest_income": 0.05e8,
         "fv_value_chg_gain": 0.0, "operate_profit": 1.2e8},
        {"end_date": "20251231", "revenue": 13e8, "oper_cost": 8.5e8,
         "n_income_attr_p": 1.4e8, "invest_income": 0.05e8,
         "fv_value_chg_gain": 0.0, "operate_profit": 1.6e8},
    ])


def _bs_full() -> pd.DataFrame:
    """两期完整资产负债表（良性增长样本）。"""
    return pd.DataFrame([
        {"end_date": "20241231", "total_assets": 15e8, "total_liab": 6e8,
         "total_cur_assets": 8e8, "total_cur_liab": 4e8,
         "accounts_receiv": 2e8, "inventories": 2e8,
         "goodwill": 0.5e8, "total_hldr_eqy_exc_min_int": 9e8},
        {"end_date": "20251231", "total_assets": 18e8, "total_liab": 7e8,
         "total_cur_assets": 10e8, "total_cur_liab": 5e8,
         "accounts_receiv": 2.2e8, "inventories": 2.1e8,
         "goodwill": 0.5e8, "total_hldr_eqy_exc_min_int": 11e8},
    ])


def _cf_full() -> pd.DataFrame:
    return pd.DataFrame([
        {"end_date": "20241231", "n_cashflow_act": 1.2e8},
        {"end_date": "20251231", "n_cashflow_act": 1.8e8},
    ])


def _cf_empty_fields() -> pd.DataFrame:
    """只有日期、经营现金流字段缺失的现金流量表。"""
    return pd.DataFrame([{"end_date": "20241231"}, {"end_date": "20251231"}])


def _inc_missing_ni() -> pd.DataFrame:
    """净利润字段（n_income_attr_p / n_income）全缺失的利润表。"""
    return _inc_full().drop(columns=["n_income_attr_p"])


# ─────────────────────────────────────────────────────── Piotroski 围栏
def test_fence_piotroski_full_data_scores_strong():
    """围栏：完整数据下 Piotroski 应判「强健」（F=8，🟢）。"""
    flags = AuditEngine()._check_piotroski(_bs_full(), _inc_full(), _cf_full())

    assert len(flags) == 1
    assert flags[0].framework == "Piotroski F-Score"
    assert flags[0].value == 8
    assert flags[0].level == LEVEL_LOW
    assert "强健" in flags[0].title


def test_fence_piotroski_missing_ni_abstains_instead_of_false_flag():
    """C-5 改造后：净利润缺失时 Piotroski **整模型弃权**，不再产出任何旗标。

    ★ 改造前后差异（本轮唯一的红旗产出变化）：
      改造前 —— 缺失被 ``or 0.0`` 兜成 0，9 个分项里 3 个判 ✗，F=3
                触发 🟠「基本面健康度严重恶化 (Piotroski F-Score 极低)」；
      改造后 —— 核心输入不可核验 → 返回空列表。
      差异性质：**消除一条由数据缺失造成的假阳性**，不是漏报。
    """
    flags = AuditEngine()._check_piotroski(_bs_full(), _inc_missing_ni(), _cf_empty_fields())

    assert flags == []


def test_fence_piotroski_missing_ocf_abstains():
    """C-5 改造后：仅经营现金流缺失时同样整模型弃权。"""
    flags = AuditEngine()._check_piotroski(_bs_full(), _inc_full(), _cf_empty_fields())

    assert flags == []


def test_fence_piotroski_single_period_is_unverifiable():
    """围栏：不足两期时 Piotroski 直接弃权，不产出任何旗标。"""
    flags = AuditEngine()._check_piotroski(_bs_full(), _inc_full().tail(1), _cf_full())

    assert flags == []


# ─────────────────────────────────────────────────────────── Dupont 围栏
def test_fence_dupont_full_data_is_clean():
    """围栏：良性样本下 Dupont 不产出旗标。"""
    assert AuditEngine()._check_dupont(_bs_full(), _inc_full()) == []


def test_fence_dupont_missing_equity_is_skipped():
    """围栏：净资产缺失时 Dupont 走跳过分支，不产出旗标（不因 0 兜底误判杠杆）。"""
    bs = _bs_full().drop(columns=["total_hldr_eqy_exc_min_int"])

    assert AuditEngine()._check_dupont(bs, _inc_full()) == []


# ─────────────────────────────────────────────────── Buffett 系列围栏
def test_fence_buffett_full_data_is_clean():
    """围栏：良性样本下 Buffett 质量模型不产出旗标。"""
    assert AuditEngine()._check_buffett_quality(_bs_full(), _inc_full(), _cf_full()) == []


def test_fence_buffett_missing_ni_and_ocf_is_clean():
    """围栏：净利润与经营现金流缺失时 Buffett 不产出旗标（利润质量判据被真值守卫跳过）。"""
    flags = AuditEngine()._check_buffett_quality(_bs_full(), _inc_missing_ni(), _cf_empty_fields())

    assert flags == []


def test_fence_buffett_missing_equity_with_goodwill_is_clean():
    """围栏：商誉在场但净资产缺失时，商誉悬顶判据被跳过，不产出旗标。"""
    bs = _bs_full().drop(columns=["total_hldr_eqy_exc_min_int"])

    assert AuditEngine()._check_buffett_quality(bs, _inc_full(), _cf_full()) == []


def test_fence_invest_income_erosion_missing_operate_profit_is_clean():
    """围栏：营业利润缺失（或 <= 0）时，投资收益侵蚀判据直接弃权。"""
    inc = _inc_full().drop(columns=["operate_profit"])

    assert AuditEngine()._check_invest_income_erosion(inc) == []


def test_fence_invest_income_erosion_full_data_is_clean():
    """围栏：良性样本（投资收益占营业利润极低）下不产出旗标。"""
    assert AuditEngine()._check_invest_income_erosion(_inc_full()) == []


def test_fence_invest_income_erosion_partial_component_abstains():
    """C-5 改造后：构成项（投资收益 / 公允价值变动）任一缺失即弃权。

    缺失项填 0 会系统性**低估**占比，等于给「非主营收益顶高估值」放行。
    """
    engine = AuditEngine()

    # 仅缺 invest_income
    inc_a = _inc_full().drop(columns=["invest_income"])
    assert engine._check_invest_income_erosion(inc_a) == []

    # 仅缺 fv_value_chg_gain
    inc_b = _inc_full().drop(columns=["fv_value_chg_gain"])
    assert engine._check_invest_income_erosion(inc_b) == []
