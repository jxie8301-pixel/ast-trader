"""沪深全市场母池（L0）的界定、板块判定与覆盖率闸门测试。

★ 这批用例守的是一个根本性问题：改造前 ``screen`` 的候选池来自涨停天梯
（约 71 只 / 沪深 5225 只 ≈ 1.4%），却对外宣称"全市场筛选"。母池必须由本项目
自主界定，并且**能自证扫了多少**。
"""
from __future__ import annotations

import dataclasses
from datetime import date
from types import SimpleNamespace

import pytest

from screener.universe import (
    ALL_REASON_CODES,
    REASON_BSE_OUT_OF_SCOPE,
    REASON_DELISTING,
    REASON_NOT_A_SHARE,
    REASON_ST_RISK_WARNING,
    UniverseBuildResult,
    UniverseRow,
    board_class,
    classify_row,
    filter_by_listing_age,
    is_bse_code,
    is_delisting_name,
    is_hs_a_share_code,
    is_st_name,
    min_ipo_natural_days,
)


def _row(**kw) -> UniverseRow:
    base = dict(code="600519", full_code="sh600519", name="贵州茅台", exchange="sh")
    base.update(kw)
    return UniverseRow(**base)


# ---------------------------------------------------------------- 代码分类
@pytest.mark.parametrize("code", ["920002", "830799", "430047", "837212", "870508", "889999"])
def test_bse_codes_are_recognized(code: str) -> None:
    """北交所三个代码段都可被识别 —— 识别了才能显式排除，而不是悄悄混进主板口径。"""
    assert is_bse_code(code) is True


@pytest.mark.parametrize("code", ["600519", "688981", "000333", "300308", "002594", "301001"])
def test_hs_a_share_codes_are_recognized(code: str) -> None:
    assert is_bse_code(code) is False
    assert is_hs_a_share_code(code) is True


def test_689_cdr_and_302_new_segment_are_a_shares() -> None:
    """★ 20261028 全量实测发现的真实代码段：科创板 CDR 689 与深市 302。

    改造前的 ``is_gem_star`` 只认 300/301/688，这两类会被误判为主板，
    从而用错涨跌幅上限（10.5% vs 20.5%）与成交额门槛（5亿 vs 3亿）。
    """
    assert is_hs_a_share_code("689009", "sh") is True
    assert is_hs_a_share_code("302132", "sz") is True


def test_b_share_is_not_hs_a_share() -> None:
    assert is_hs_a_share_code("200011", "sz") is False
    assert is_hs_a_share_code("900901", "sh") is False


def test_st_and_delisting_name_detection() -> None:
    # 判定口径与 eltdx 自身 CodeApi.latest_st 一致（名称前缀法）
    assert is_st_name("ST银河") is True
    assert is_st_name("*ST海航") is True
    assert is_st_name("SST华新") is True
    assert is_st_name("S*ST前锋") is True
    assert is_st_name("贵州茅台") is False
    assert is_delisting_name("长生退") is True
    assert is_delisting_name("贵州茅台") is False


# ---------------------------------------------------------------- 板块判定
def test_board_class_prefers_code_table_board_over_prefix() -> None:
    """板块以代码表 ``board`` 为准（实测取值域 sse_*/szse_*），前缀仅兜底。"""
    assert board_class("sse_main_board") == "main"
    assert board_class("szse_main_board") == "main"
    assert board_class("sse_star_market") == "growth"
    assert board_class("szse_chinext") == "growth"


def test_board_class_falls_back_to_prefix() -> None:
    assert board_class(None, "689009", "sh") == "growth"   # 科创板 CDR
    assert board_class(None, "302132", "sz") == "growth"   # 深市新代码段
    assert board_class(None, "600519", "sh") == "main"


def test_board_class_unknown_board_falls_back_conservatively() -> None:
    """未见过的新板块：回退到前缀；判不出时按**主板**（门槛更严）处理。"""
    assert board_class("some_new_board", "600519", "sh") == "main"
    assert board_class("some_new_board", "300308", "sz") == "growth"


# ---------------------------------------------------------------- 剔除判定
def test_classify_row_normal_stock_passes() -> None:
    assert classify_row("贵州茅台", "600519", "sh", board="sse_main_board", category="a_share") is None


def test_classify_row_st_is_excluded() -> None:
    assert classify_row("ST银河", "000806", "sz", category="a_share") == REASON_ST_RISK_WARNING


def test_classify_row_delisting_precedes_st() -> None:
    """退市先于 ST：两者同时成立时应以更严重的「退市」为准。"""
    assert classify_row("ST长生退", "002680", "sz", category="a_share") == REASON_DELISTING


def test_classify_row_bse_is_explicitly_out_of_scope() -> None:
    """北交所必须产出**显式**剔除码 —— 不能靠成交额门槛隐式排掉。"""
    assert classify_row("某北交所", "920002", "bj", category="a_share") == REASON_BSE_OUT_OF_SCOPE
    assert classify_row("某北交所", "830799", "sz", category="a_share") == REASON_BSE_OUT_OF_SCOPE


def test_classify_row_non_a_share_category_is_excluded() -> None:
    assert classify_row("某某B股", "200011", "sz", category="b_share") == REASON_NOT_A_SHARE
    assert classify_row("某某ETF", "510300", "sh", category="etf") == REASON_NOT_A_SHARE


def test_classify_row_falls_back_to_prefix_when_category_missing() -> None:
    assert classify_row("某某B股", "200011", "sz", category=None) == REASON_NOT_A_SHARE


# ---------------------------------------------------------------- 次新剔除
def test_filter_by_listing_age_drops_new_listings() -> None:
    today = date(2026, 10, 28)
    rows = [
        _row(code="1", full_code="sh600001", ipo_date="2026-10-01"),   # 27 自然日 → 次新
        _row(code="2", full_code="sz000002", ipo_date="1991-01-29"),   # 老股
        _row(code="3", full_code="sz000003", ipo_date=None),           # 上市日期不可核验
    ]
    kept, dropped = filter_by_listing_age(rows, today=today)

    assert dropped == 1
    assert [r.code for r in kept] == ["2", "3"]


def test_filter_by_listing_age_keeps_unverified_ipo_date() -> None:
    """上市日期不可核验时**保守放行**（次新是风格过滤，不是风控红线）。

    误放行的代价（一只次新进池）远低于误剔除（把正常票当次新丢掉）。
    """
    rows = [_row(ipo_date=None)]
    kept, dropped = filter_by_listing_age(rows, today=date(2026, 10, 28))
    assert dropped == 0 and len(kept) == 1


def test_min_ipo_natural_days_converts_trading_days() -> None:
    """60 个交易日 ≈ 84 个自然日（按 5/7 换算）。"""
    assert min_ipo_natural_days() == 84


# ---------------------------------------------------------------- 覆盖率闸门
def test_coverage_ok_when_ratio_meets_threshold() -> None:
    r = UniverseBuildResult(scanned_total=5225, expected_total=5225)
    assert r.coverage_ratio == 1.0
    assert r.coverage_ok is True


def test_coverage_rejects_partial_scan() -> None:
    r = UniverseBuildResult(scanned_total=1000, expected_total=5225)
    assert r.coverage_ratio is not None and r.coverage_ratio < 0.98
    assert r.coverage_ok is False


def test_coverage_rejects_unavailable_denominator() -> None:
    """★ 分母不可得时返回 **None**（不是 0.0）并判失败。

    0.0 会与「扫到 0 只」混淆：前者是通道故障，后者是行情异常，处置方式不同。
    """
    r = UniverseBuildResult(scanned_total=100, expected_total=None)
    assert r.coverage_ratio is None
    assert r.coverage_ok is False


def test_excluded_reason_codes_are_known() -> None:
    r = UniverseBuildResult()
    r.bump(REASON_ST_RISK_WARNING, 194)
    r.bump(REASON_ST_RISK_WARNING)
    assert r.excluded[REASON_ST_RISK_WARNING] == 195
    assert set(r.excluded) <= set(ALL_REASON_CODES)


def test_result_to_dict_exposes_audit_fields() -> None:
    d = UniverseBuildResult(scanned_total=10, expected_total=10).to_dict()
    for key in ("scanned_total", "expected_total", "coverage_ratio", "coverage_ok",
                "active_count", "excluded", "bse_intrusion", "unknown_boards", "warnings"):
        assert key in d


# ---------------------------------------------------------------- 次新剔除与母池行契约
def test_universe_row_is_frozen_and_replaceable() -> None:
    """UniverseRow 冻结，补齐 ipo_date 必须走 dataclasses.replace。"""
    r = _row()
    with pytest.raises(dataclasses.FrozenInstanceError):
        r.ipo_date = "2001-08-27"  # type: ignore[misc]
    r2 = dataclasses.replace(r, ipo_date="2001-08-27")
    assert r2.ipo_date == "2001-08-27" and r.ipo_date is None


def test_simple_namespace_row_shape_is_accepted_by_classify() -> None:
    """冒烟：``codes.a_shares`` 返回的行对象字段能被正确消费（board/category）。"""
    raw = SimpleNamespace(
        code="688981", name="中芯国际", exchange="sh",
        board="sse_star_market", category="a_share", board_reason="SSE STAR",
        previous_close_price=88.0,
    )
    assert classify_row(raw.name, raw.code, raw.exchange,
                        board=raw.board, category=raw.category) is None
    assert board_class(raw.board, raw.code, raw.exchange) == "growth"
