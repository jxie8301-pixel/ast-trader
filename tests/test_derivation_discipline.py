"""数据纪律回归：反向 DCF 与质押率的「缺失即未核验，严禁捏造默认值」。

背景（P1-3，审计报告核实阶段发现的 2 项漏检）
------------------------------------------------
1. ``core/derivation.py`` 反向 DCF 曾把 ``implied_margin`` 写死 ``16.5`` ——
   既无数据源也无推导过程，属**凭空捏造的默认值**，直接违反 SRS §6.3
   「严禁捏造财务数据，缺失必须显式标注未核验」。
2. ``core/judgment_chain.py`` 质地五问 Q4 曾把质押率 ``or 0.0`` 兜底，
   导致断言「质押率 0.0% 处于安全线内」，把「通道不可得」伪装成
   「确认无质押」，与采集层 None 纪律及 ``filter_audit`` 的
   ``pledge_verified`` 口径直接冲突。
"""
from __future__ import annotations

from typing import Any

from core.derivation import generate_standard_derivation
from core.judgment_chain import JudgmentChainRunner, _normalize_pledge_pct


# ---------------------------------------------------------------- 反向 DCF
def test_reverse_dcf_implied_margin_is_not_fabricated():
    """P1-3: 反向 DCF 的隐含净利率严禁硬编码 16.5%，缺失必须置 None。"""
    result = generate_standard_derivation(
        current_price=13.31,
        total_shares_yi=4.0,
        net_income_latest_yi=1.2,
        main_business=[{"name": "核心主营", "ratio": 100.0}],
        is_growth=False,
    )

    rdcf = result["reverse_dcf"]
    assert rdcf["implied_margin"] is None
    assert rdcf["implied_margin"] != 16.5
    assert "未核验" in rdcf["implied_margin_basis"]


def test_reverse_dcf_has_no_hardcoded_margin_anywhere():
    """P1-3: 整个推导结果里不得出现任何 16.5 这个捏造常量。"""
    result = generate_standard_derivation(
        current_price=52.0,
        total_shares_yi=12.56,
        net_income_latest_yi=30.0,
        main_business=[{"name": "白酒", "ratio": 100.0}],
        is_growth=True,
    )

    def _walk(node: Any) -> bool:
        if isinstance(node, dict):
            return any(_walk(v) for v in node.values())
        if isinstance(node, list):
            return any(_walk(v) for v in node)
        if isinstance(node, float):
            return abs(node - 16.5) < 1e-9
        return False

    assert not _walk(result)


def test_reverse_dcf_exit_pe_uses_named_constant():
    """P1-3: 隐含退出 PE 的 1.2 倍已具名化，且不再是散落魔数。"""
    from core.derivation import REVERSE_DCF_EXIT_PE_MULTIPLE

    result = generate_standard_derivation(
        current_price=13.31,
        total_shares_yi=4.0,
        net_income_latest_yi=1.2,
        is_growth=False,
    )
    # 非成长股 base_pe = 15.0
    assert result["reverse_dcf"]["implied_exit_pe"] == 15.0 * REVERSE_DCF_EXIT_PE_MULTIPLE


def test_reverse_dcf_implied_cagr_is_computed_not_fallback():
    """正常锚点下隐含增速必须由公式算出，且 sanity 落在合法取值域内。"""
    result = generate_standard_derivation(
        current_price=13.31,
        total_shares_yi=4.0,
        net_income_latest_yi=1.2,
        is_growth=False,
    )

    rdcf = result["reverse_dcf"]
    assert rdcf["implied_cagr"] is not None
    assert rdcf["sanity"] in ("可信", "过度乐观", "买完完美未来")


# ---------------------------------------------------------------- 质押率口径
def test_normalize_pledge_pct_none_stays_none():
    """P1-3: 质押率未核验必须保持 None，严禁 or 0.0 兜底。"""
    assert _normalize_pledge_pct(None) is None


def test_normalize_pledge_pct_handles_both_scales():
    """P1-3: 分数制与百分数制都要归一到百分数；显式 0.0 表示「已核验无质押」。"""
    assert _normalize_pledge_pct(0.70) == 70.0   # 分数制
    assert _normalize_pledge_pct(45.0) == 45.0   # 百分数制原样
    assert _normalize_pledge_pct(0.0) == 0.0     # 已核验且无质押
    assert _normalize_pledge_pct("nonsense") is None


def test_quality_q4_does_not_claim_zero_pledge_when_unverified():
    """P1-3: 质押通道不可得时，Q4 严禁断言「质押率 0.0% 处于安全线内」。"""
    runner = JudgmentChainRunner()
    card = runner.run(
        ticker="603776.SH",
        name="永安行",
        trade_date="20261027",
        quote={"close": 15.20, "pct_chg": 0.8, "amount": 6.0e7,
               "circ_mv": 58.7e8, "total_mv": 58.7e8, "pe": 40.0,
               "turnover_ratio": 2.4},
        momentum={"is_bullish_ma": False, "ma5": 15.0, "ma20": 15.6, "overhead_chip_pct": 0.5},
        flags=[],
        matched_youzi=[],
        trap_warnings=[],
        concepts=[],
        ladder_info=None,
        # 采集层真实行为：pledge_ratio 恒为 None（eltdx F10 无质押通道）
        governance_info={"pledge_ratio": None, "has_reduction_plan": False,
                         "concepts": [], "main_business": []},
    )

    p1 = card.get("pillar_1_quality", "")
    assert "管理层可信吗" in p1
    assert "未核验" in p1
    assert "处于安全线内" not in p1
    assert "质押率 0.0%" not in p1
