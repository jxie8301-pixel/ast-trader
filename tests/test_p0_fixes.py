"""P0 四项的独立回归用例（纯离线，不依赖行情链路）。

每项修复对应一组用例，任一小组失败即可定位到具体 P0 项：

* P0-1  「好公司?」中文子串误判 —— `format_three_part_conclusion` / `is_avoid_gear`
* P0-2  亏损股进入 DCF/SOTP —— `_build_pillar_3_odds` 负值断流与锚点除零保护
* P0-3  质押率硬编码 0.0 —— 采集/排雷/审计三层 None 语义
* P0-4  Beneish/Altman 行业适用性 —— `classify_industry` 准入开关
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pandas as pd
import pytest

import config
from core.audit_engine import AuditEngine
from core.industry import INDUSTRY_FINANCIAL, INDUSTRY_UNKNOWN, classify_industry
from core.judgment_chain import (
    QUALITY_VERDICT_GOOD,
    format_three_part_conclusion,
    is_avoid_gear,
    is_good_company,
    is_good_price,
)
from core.red_flags import LEVEL_FATAL, LEVEL_HIGH, LEVEL_INFO
from screener.filter_audit import filter_audit

EMPTY_DF = pd.DataFrame()


# =============================================================================
# P0-1  «好公司?» 中文子串误判
# =============================================================================


@pytest.mark.parametrize(
    "verdict, expected",
    [("好", True), ("部分好", True), ("不好", False), ("", False), (None, False)],
)
def test_p0_1_quality_verdict_semantics(verdict: str | None, expected: bool) -> None:
    """取值域映射正确：唯独「不好」不得被判为好公司。"""
    assert is_good_company(verdict) is expected


def test_p0_1_bad_quality_shows_no_in_conclusion() -> None:
    """核心回归：质地「不好」时三分结论必须输出 否/存疑。"""
    concl = format_three_part_conclusion("不好", 0.0, "合理")
    assert "好公司? 【否/存疑】" in concl
    # 同时不得因为「好价格」而把「好公司」带成 是
    assert "好公司? 【是】" not in concl


def test_p0_1_good_quality_still_shows_yes() -> None:
    """正向保护：「好」与「部分好」仍应输出 是。"""
    for verdict in QUALITY_VERDICT_GOOD:
        assert "好公司? 【是】" in format_three_part_conclusion(verdict, 0.0, "合理")


def test_p0_1_price_and_bet_semantics() -> None:
    """好价格走白名单；好下注严格由仓位派生。"""
    assert is_good_price("便宜(有余地)") is True
    assert is_good_price("合理") is True
    assert is_good_price("已被价格计入") is False
    assert is_good_price("买完完美未来") is False
    assert is_good_price("未核验(净利润为负)") is False

    assert "好下注? 【是】" in format_three_part_conclusion("好", 0.05, "合理")
    assert "好下注? 【否】" in format_three_part_conclusion("好", 0.0, "合理")


def test_p0_1_suffix_branch_keeps_semantics() -> None:
    """Lint 纠偏分支与主分支文案同源，且不得回退到子串判定。"""
    concl = format_three_part_conclusion("不好", 0.0, "便宜(有余地)", suffix="机检未通过")
    assert concl.startswith("好公司? 【否/存疑】")
    assert "好下注? 【否】" in concl
    assert "好价格? 【是】" in concl
    assert concl.endswith("(机检未通过)")


@pytest.mark.parametrize(
    "gear, expected",
    [
        ("回避", True),
        ("减仓", True),
        ("核心仓", False),
        ("观察", False),
        ("等证据临界(观察)", False),
        ("不追高(贵但优质)", False),
        ("期权仓(小)", False),
    ],
)
def test_p0_1_avoid_gear_whitelist(gear: str, expected: bool) -> None:
    """档位分类走显式白名单，「等证据临界(观察)」不得因含「观察」被误并入回避。"""
    assert is_avoid_gear(gear) is expected


# =============================================================================
# P0-2  亏损股严禁进入 DCF / SOTP
# =============================================================================


def _odds_runner() -> Any:
    from core.judgment_chain import JudgmentChainRunner

    return JudgmentChainRunner()


def test_p0_2_negative_net_income_blocks_valuation() -> None:
    """净利润为负 → 未核验(净利润为负)，不生成 derivation / anchor，且仓位归零。"""
    runner = _odds_runner()
    summary, verdict, sotp, dcf, deriv, anchor, rdcf, verified = runner._build_pillar_3_odds(
        price=10.0,
        total_shares_yi=10.0,
        pe_val=0.0,
        total_mv=100e8,
        derived_data={"latest_vitals": {"latest_net_income": -2.88e8}},
        is_tech=False,
        mainbz_list=[],
    )
    assert verified is False
    assert verdict == "未核验(净利润为负)"
    assert deriv is None
    assert anchor is None
    assert rdcf is None
    assert sotp == 0.0 and dcf == 0.0
    assert "未核验" in summary


def test_p0_2_zero_net_income_also_blocks_valuation() -> None:
    """净利润恰好为 0 同样不可作为估值底座，且不得回退到 PE 反推。"""
    runner = _odds_runner()
    _, verdict, _, _, deriv, _, _, verified = runner._build_pillar_3_odds(
        price=10.0,
        total_shares_yi=10.0,
        pe_val=20.0,          # PE 可用，但净利润为 0 时严禁反推
        total_mv=100e8,
        derived_data={"latest_vitals": {"latest_net_income": 0.0}},
        is_tech=False,
        mainbz_list=[],
    )
    assert verified is False
    assert verdict == "未核验(净利润为负)"
    assert deriv is None


def test_p0_2_missing_net_income_falls_back_to_pe() -> None:
    """净利润缺失（而非为负）时，仍允许 PE 反推兜底，保持既有能力不退化。"""
    runner = _odds_runner()
    _, verdict, _, _, deriv, _, _, verified = runner._build_pillar_3_odds(
        price=10.0,
        total_shares_yi=10.0,
        pe_val=20.0,
        total_mv=100e8,
        derived_data={"latest_vitals": {}},
        is_tech=False,
        mainbz_list=[],
    )
    assert verified is True
    assert deriv is not None
    assert verdict != "未核验(净利润为负)"


def test_p0_2_anchor_zero_no_zero_division(monkeypatch: pytest.MonkeyPatch) -> None:
    """锚点非正时不得触发 ZeroDivisionError（回归 `:399` 缺失的守卫）。"""
    import core.judgment_chain as jc

    monkeypatch.setattr(
        jc,
        "generate_standard_derivation",
        lambda **kwargs: {
            "derivation": {"p_f_n": {"market_cap": 1.0, "fact": 1.0, "narrative": 0.0,
                                     "narrative_share": 0.0, "kind": "free_option"}},
            "anchor_range": {"low": {"value": 0.0}, "high": {"value": 0.0}, "same_direction": False},
            "reverse_dcf": {"implied_cagr": 0.0, "sanity": "合理", "falsification_condition": "x"},
        },
    )
    runner = _odds_runner()
    summary, _verdict, _sotp, _dcf, _deriv, _anchor, _rdcf, _verified = runner._build_pillar_3_odds(
        price=10.0,
        total_shares_yi=10.0,
        pe_val=20.0,
        total_mv=100e8,
        derived_data={"latest_vitals": {}},
        is_tech=False,
        mainbz_list=[],
    )
    assert "N/A(锚点非正)" in summary


# =============================================================================
# P0-3  质押率 None 语义与多因子排雷
# =============================================================================


def _gov(pledge: float | None, recent_violations: int = 0, total_violations: int = 0) -> dict[str, Any]:
    return {
        "pledge_ratio": pledge,
        "has_violation_record": total_violations > 0,
        "violation_count": total_violations,
        "recent_violation_count": recent_violations,
        "has_reduction_plan": False,
        "concepts": [],
        "main_business": [],
    }


def test_p0_3_unverified_pledge_raises_audit_flag() -> None:
    """质押率不可核验时，审计层必须显式标记，而不是静默当作 0 放行。"""
    flags = AuditEngine()._check_governance(_gov(None))
    titles = [f.title for f in flags]
    assert any("质押比例未核验" in t for t in titles)
    assert not any(f.level == LEVEL_FATAL for f in flags)


def test_p0_3_high_pledge_still_vetoes_when_verified() -> None:
    """质押率可核验且超阈值时，致命红旗能力不得退化。"""
    flags = AuditEngine()._check_governance(_gov(0.85))
    fatal = [f for f in flags if f.level == LEVEL_FATAL]
    assert any("质押" in f.title for f in fatal)


def test_p0_3_violation_records_produce_flags() -> None:
    """违规处罚记录：近期达阈值判致命，仅历史记录判高危。"""
    engine = AuditEngine()
    fatal = engine._check_governance(_gov(None, recent_violations=config.GOVERNANCE_VIOLATION_FATAL_COUNT))
    assert any(f.level == LEVEL_FATAL and "违规" in f.title for f in fatal)

    high = engine._check_governance(_gov(None, recent_violations=0, total_violations=1))
    assert any("违规" in f.title for f in high)
    assert not any(f.level == LEVEL_FATAL for f in high)


def _mock_collector(pledge: float | None, recent_violations: int = 0) -> MagicMock:
    coll = MagicMock()
    coll.get_f10_governance_and_concept.return_value = _gov(pledge, recent_violations, recent_violations)
    return coll


def test_p0_3_filter_audit_vetoes_high_pledge() -> None:
    """Tier 2：质押可核验且超阈值 → 一票否决。"""
    passed = filter_audit([{"code": "000002", "name": "高质押", "limit_reason": "x"}], _mock_collector(0.85))
    assert passed == []


def test_p0_3_filter_audit_marks_unverified_pledge() -> None:
    """Tier 2：质押不可核验 → 不否决，但标记为 UNVERIFIED_PLEDGE（不再伪装成 0）。"""
    passed = filter_audit([{"code": "000001", "name": "未核验", "limit_reason": "x"}], _mock_collector(None))
    assert len(passed) == 1
    assert passed[0]["pledge_ratio"] is None
    assert passed[0]["audit_status"] == "UNVERIFIED_PLEDGE"


def test_p0_3_filter_audit_vetoes_dense_violations() -> None:
    """Tier 2 多因子：近期违规密集 → 一票否决（不再只有质押单一判据）。"""
    passed = filter_audit(
        [{"code": "000004", "name": "违规密集", "limit_reason": "x"}],
        _mock_collector(None, recent_violations=config.GOVERNANCE_VIOLATION_FATAL_COUNT),
    )
    assert passed == []


# =============================================================================
# P0-4  Beneish / Altman 行业适用性准入
# =============================================================================


@pytest.mark.parametrize(
    "name, expected",
    [
        ("工商银行", INDUSTRY_FINANCIAL),
        ("平安银行", INDUSTRY_FINANCIAL),
        ("中信证券", INDUSTRY_FINANCIAL),
        # 已知边界：中国平安属综合保险集团，但简称不含「保险」类词，
        # 纯关键词启发式无法覆盖 —— 需接入真实行业分类数据源后才能解决。
        ("中国平安", INDUSTRY_UNKNOWN),
        ("贵州茅台", INDUSTRY_UNKNOWN),
        ("宁德时代", INDUSTRY_UNKNOWN),
        ("中芯国际", INDUSTRY_UNKNOWN),
    ],
)
def test_p0_4_classify_industry(name: str, expected: str) -> None:
    """行业识别：金融机构归入金融业，其余保持未分类。"""
    assert classify_industry(name=name) == expected


def test_p0_4_classify_industry_from_main_business() -> None:
    """主营构成含银行专属结构词时亦能识别（银行主营常按区域披露）。"""
    assert classify_industry(name="某某股份", main_business=[{"name": "总行和境内分行", "ratio": 100.0}]) == (
        INDUSTRY_FINANCIAL
    )


def test_p0_4_explicit_industry_wins() -> None:
    assert classify_industry(industry="房地产", name="工商银行") == "房地产"


def test_p0_4_beneish_abstains_for_financial() -> None:
    """金融业 Beneish 主动弃权：不再给出财务操纵致命红旗。"""
    flags = AuditEngine()._check_beneish(EMPTY_DF, EMPTY_DF, EMPTY_DF, industry=INDUSTRY_FINANCIAL)
    assert len(flags) == 1
    assert flags[0].level == LEVEL_INFO
    assert "弃权" in flags[0].title
    assert not any(f.level == LEVEL_FATAL for f in flags)


def test_p0_4_altman_abstains_for_financial() -> None:
    """金融业 Altman 主动弃权：不再给出破产高危误报。"""
    flags = AuditEngine()._check_altman(EMPTY_DF, EMPTY_DF, None, industry=INDUSTRY_FINANCIAL)
    assert len(flags) == 1
    assert flags[0].level == LEVEL_INFO
    assert not any(f.level == LEVEL_FATAL for f in flags)


def test_p0_4_models_still_run_for_non_financial() -> None:
    """非金融业不得被误弃权（数据不足时应返回空清单而非弃权旗标）。"""
    engine = AuditEngine()
    assert engine._check_beneish(EMPTY_DF, EMPTY_DF, EMPTY_DF, industry=INDUSTRY_UNKNOWN) == []
    assert engine._check_altman(EMPTY_DF, EMPTY_DF, None, industry=INDUSTRY_UNKNOWN) == []


def test_p0_4_bank_no_longer_flagged_as_manipulator() -> None:
    """端到端：以「工商银行」为名的标的，审计结果中不得出现财务操纵 / 破产类红旗。"""
    flags = AuditEngine().run_audit(
        balance_df=EMPTY_DF,
        cashflow_df=EMPTY_DF,
        income_df=EMPTY_DF,
        governance_info={"concepts": [], "main_business": []},
        quote_info={"name": "工商银行"},
    )
    # 两个模型均不得给出任何高等级结论（致命/高危）
    assert not any(f.level in (LEVEL_FATAL, LEVEL_HIGH) for f in flags)
    # 也不得产出属于这两个模型的业务旗标，只保留 Governance 框架的弃权留痕
    assert not any(f.framework in ("Beneish M-Score", "Altman Z-Score") for f in flags)
    assert any("弃权" in f.title for f in flags)
