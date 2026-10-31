"""股权质押取数与排雷判据测试。

★ 这批用例守的是一条**被用户纠正的结论**与一个**口径错配 bug**
-------------------------------------------------------------------
用户指出「个股分析中无法获取到质押，实际能获取」——通道确实存在：

    ``CWServ.tdxf10_gg_zbyz`` + ``params=["gqzy", <6位代码>, ""]``

返回 3 张表：

    table 2  全公司累计质押汇总  T001 / ljzygs(万股) / zzgb(占总股本%)
    table 1  各主要股东质押汇总  t003 股东名 / t015 股数 / t016 占总股本%
                                t021 占**其所持股份**%(爆仓踩踏关键指标) / t018 披露日
    table 0  质押流水明细        T003 质押人 / T004 质权人 / T005 股数 / T009 起始 / T010 解除

查证后发现真正的缺陷**不是通道缺失，而是口径错配**：旧实现把 ``t021``
（占其持股比例）当作 ``pledge_ratio`` 去比 ``PLEDGE_FATAL_RATIO=0.70``
（占总股本口径）。实测后果：

    格力 000651  旧 1.0000 → 新 0.1535   控股股东满仓质押但仅占总股本 15.35% ⇒ 白马被误杀
    立讯 002475  旧 0.3783 → 新 0.1418
    宁德 300750  旧 0.1475 → 新 0.0068   旧值夸大 21 倍
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

import config
from data.eltdx_collector import parse_pledge_response
from screener.filter_audit import filter_audit


def _table(rows: list[dict]) -> SimpleNamespace:
    return SimpleNamespace(rows=tuple(rows), count=len(rows))


def _resp(
    holders: list[dict] | None = None,
    zzgb: float | None = None,
    ljzygs: float | None = None,
    records: list[dict] | None = None,
) -> SimpleNamespace:
    """构造 zbyz/gqzy 响应。

    ``holders`` = table1 行（t003/t015/t016/t021/t018）
    ``records`` = table0 质押流水分行（T003/T005/T006/T007/T011/T012）
    """
    return SimpleNamespace(
        ok=True,
        tables=(
            _table(records or []),                                          # table0 流水明细
            _table(holders or []),                                          # table1 股东汇总
            _table([{"T001": "000651", "ljzygs": ljzygs, "zzgb": zzgb}]),    # table2 公司汇总
        ),
    )


def _live_record(holder: str, shares: float, total_pct: float, own_pct: float) -> dict:
    """一笔**未解押**的质押（T011 实际解押日 / T012 解押股数皆空）。"""
    return {"T003": holder, "T005": shares, "T006": own_pct, "T007": total_pct,
            "T011": None, "T012": None}


def _closed_record(holder: str, shares: float, total_pct: float) -> dict:
    """一笔**已解押**的质押。"""
    return {"T003": holder, "T005": shares, "T006": 0.5, "T007": total_pct,
            "T011": "2024-06-28", "T012": shares}


# ══════════════════════════════════════════════════ 口径分离
def test_pledge_ratio_is_total_share_basis_not_own_holding_basis():
    """★★ 核心回归：``pledge_ratio`` 必须是**占总股本**，绝不能是占其持股。

    格力 000651 真实数据：珠海明骏把**自己持股 100%** 质押，但那些股份
    只占总股本 **15.35%**。旧实现返回 1.0 ⇒ 被 ``PLEDGE_FATAL_RATIO=0.70``
    一票否决，白马被误杀。
    """
    out = parse_pledge_response(_resp(
        holders=[{"t003": "珠海明骏投资合伙企业(有限合伙)", "t015": 85956.6532,
                  "t016": 15.35, "t021": 100, "t018": "2026-07-16"}],
        zzgb=15.35, ljzygs=85956.6532,
    ))
    assert out is not None
    assert out["pledge_ratio"] == pytest.approx(0.1535)        # 占总股本
    assert out["pledge_ratio_of_own_max"] == pytest.approx(1.0)  # 占其持股，单独存
    assert out["top_pledgor"] == "珠海明骏投资合伙企业(有限合伙)"
    assert out["total_pledge_shares"] == pytest.approx(85956.6532)

    # ★ 决定性断言：口径修正前后必须差一个数量级，否则说明又混了
    assert out["pledge_ratio"] < config.PLEDGE_FATAL_RATIO
    assert out["pledge_ratio_of_own_max"] > config.PLEDGE_FATAL_RATIO


def test_pledge_own_ratio_kept_even_when_total_is_tiny():
    """宁德 300750：占总股本 0.68%，占其持股 14.75% —— 旧值夸大 21 倍。"""
    out = parse_pledge_response(_resp(
        holders=[{"t003": "李平", "t015": 2973.0, "t016": 0.68, "t021": 14.75,
                  "t018": "2023-11-24"}],
        zzgb=0.68, ljzygs=2973.0,
    ))
    assert out["pledge_ratio"] == pytest.approx(0.0068)
    assert out["pledge_ratio_of_own_max"] == pytest.approx(0.1475)


def test_pledge_falls_back_to_holder_total_ratio_when_company_missing():
    """公司汇总缺失时，退到股东口径的**占总股本** t016（仍不是 t021）。"""
    out = parse_pledge_response(_resp(
        holders=[{"t003": "甲", "t015": 1000.0, "t016": 12.0, "t021": 90.0, "t018": "2026-01-01"}],
        zzgb=None, ljzygs=None,
    ))
    assert out["pledge_ratio"] == pytest.approx(0.12)
    assert out["pledge_ratio_of_own_max"] == pytest.approx(0.90)


def test_pledge_own_ratio_none_when_not_disclosed():
    """分众 002027 的 t021 为 None ⇒ 占其持股不可核验，必须是 None 而不是 0。"""
    out = parse_pledge_response(_resp(
        holders=[{"t003": "易贤忠", "t015": 2980.0, "t016": 9.86, "t021": None,
                  "t018": "2015-12-24"}],
        zzgb=9.86, ljzygs=2980.0,
    ))
    assert out["pledge_ratio"] == pytest.approx(0.0986)
    assert out["pledge_ratio_of_own_max"] is None


# ══════════════════════════════════════════════════ 不可核验 vs 确认无质押
def test_pledge_zero_when_confirmed_no_pledge():
    """接口正常返回且确无在押记录（美的/茅台）⇒ 0.0，属**确认无质押**。"""
    out = parse_pledge_response(_resp(holders=[], zzgb=None, ljzygs=None, records=[]))
    assert out is not None
    assert out["pledge_ratio"] == 0.0
    assert out["pledge_source"] == "none"
    assert out["pledge_live_records"] == 0


# ══════════════════════════════════════════════════ 三表填充程度差异（最关键）
def test_pledge_detail_fallback_when_summary_tables_are_empty():
    """★★★ 科达利 002850 回归：**table1 空 且 table2 全 None，但 table0 有在押记录**。

    真实数据：明细 32 条，其中 7 条未解押（T011/T012 皆空），合计占总股本 **2.03%**，
    质押人为励建炬。

    旧实现只看 table1/table2，会判成 ``pledge_ratio=0.0``（"确认无质押"）——
    这是比误杀更糟的方向：**把有质押的票当无质押放行**，Tier 2 排雷直接失效。
    """
    out = parse_pledge_response(_resp(
        holders=[], zzgb=None, ljzygs=None,
        records=[
            _live_record("励建炬", 115.0, 0.55, 6.2),
            _live_record("励建炬", 72.0, 0.34, 3.9),
            _live_record("励建炬", 96.0, 0.46, 5.2),
            _live_record("励建炬", 48.0, 0.23, 2.6),
            _closed_record("励建立", 200.0, 0.74),      # 已解押，须排除
        ],
    ))
    assert out["pledge_source"] == "detail"
    assert out["pledge_ratio"] == pytest.approx(0.0158)          # 0.55+0.34+0.46+0.23
    assert out["pledge_ratio_of_own_max"] == pytest.approx(0.179)  # 同股东 T006 求和
    assert out["pledge_live_records"] == 4
    assert out["top_pledgor"] == "励建炬"
    assert out["pledge_ratio"] > 0, "★ 绝不能把只有明细表的在押标的判为 0"


def test_pledge_all_records_closed_means_no_pledge():
    """★ 美的 000333：明细全是**已解押**记录 ⇒ 确认无质押（而不是当成"有质押"）。"""
    out = parse_pledge_response(_resp(
        holders=[], zzgb=None, ljzygs=None,
        records=[_closed_record("美的控股有限公司", 10000.0, 1.42)],
    ))
    assert out["pledge_ratio"] == 0.0
    assert out["pledge_source"] == "none"
    assert out["pledge_live_records"] == 0


def test_pledge_detail_ratio_is_none_when_sum_exceeds_100_percent():
    """★★★ 002269 美邦服饰实测：明细累加超 100% ⇒ 判**不可核验**，不截断。

    按 T011/T012/T010 三判据过滤后仍剩 16 笔（起始日 2012~2016、T010 空），
    累加 T007 超 100%；累加股数 14.41 亿股 ＞ 上海华服+胡佳佳合计持股约
    3.5 亿股（超 4 倍）⇒ 明细里存在**未关闭的旧记录/重复计**。

    截断到 100% 会输出「质押 100%」这种荒谬结论并污染报告；
    正确做法是判为不可核验，交上层按 NFR-02 降权（绝不硬编假值）。
    """
    out = parse_pledge_response(_resp(
        holders=[], zzgb=None, ljzygs=None,
        records=[_live_record("上海华服投资有限公司", 5000.0, 60.0, 50.0),
                 _live_record("上海华服投资有限公司", 5000.0, 49.86, 40.0)],
    ))
    assert out["pledge_ratio"] is None
    assert out["pledge_source"] == "detail_inconsistent"
    assert out["pledge_ratio_of_own_max"] is None, "脏记录算出的占其持股同样不可信"


def test_pledge_detail_inconsistent_when_holder_own_sum_exceeds_100():
    """★★ 同一股东「占其持股%」累加 > 100% ⇒ 必然含重复/未关闭的旧记录。

    这比"总量超 100%"更灵敏：某股东把自己持股质押掉的比例不可能超过 100%，
    但该情形在**占总股本口径尚未超 100%** 时就会暴露。
    002269 的 16 笔全是上海华服投资，占其持股累加远超 100%。
    """
    out = parse_pledge_response(_resp(
        holders=[], zzgb=None, ljzygs=None,
        records=[_live_record("上海华服", 28464.0, 11.27, 22.37),
                 _live_record("上海华服", 15208.0, 6.02, 11.95),
                 _live_record("上海华服", 13020.0, 12.96, 16.07),
                 _live_record("上海华服", 14810.0, 14.65, 20.88)],
    ))
    # 占总股本累加 45.0%（未超 100%），但占其持股累加 71.27%… 需构造真正超 100% 的
    assert out["pledge_source"] == "detail"
    assert out["pledge_ratio_of_own_max"] == pytest.approx(0.7127)

    out2 = parse_pledge_response(_resp(
        holders=[], zzgb=None, ljzygs=None,
        records=[_live_record("甲", 100.0, 2.0, 90.0),     # 占其持股 90%
                 _live_record("甲", 100.0, 2.0, 60.0)],    # 再加 60% ⇒ 150% > 100%
    ))
    assert out2["pledge_source"] == "detail_inconsistent"
    assert out2["pledge_ratio"] is None


def test_pledge_detail_record_end_date_filters_expired():
    """★★ T010（解除日/截止日）**早于今天** ⇒ 已到期，不得算作在押。

    002269 的 22 笔 T011/T012 皆空记录中，20 笔 T010 是 2017~2019 年的
    解除日（起始日更早到 2012 年）。只看 T011/T012 会把十几年老记录
    当成当前在押 ⇒ 累加出 109.86%（用户用截图纠正）。
    """
    expired = {"T003": "上海华服", "T005": 28464.0, "T006": 22.37, "T007": 11.27,
               "T009": "2016-10-12", "T010": "2019-05-18", "T011": None, "T012": None}
    future = {"T003": "甲", "T005": 1000.0, "T006": 5.0, "T007": 2.0,
              "T009": "2026-01-01", "T010": "2027-04-29", "T011": None, "T012": None}
    no_end = {"T003": "甲", "T005": 500.0, "T006": 2.5, "T007": 1.0,
              "T009": "2026-03-01", "T010": None, "T011": None, "T012": None}

    out = parse_pledge_response(_resp(holders=[], zzgb=None,
                                      records=[expired, future, no_end]))
    # expired 被 T010 过滤；future(2.0) + no_end(1.0) = 3.0%
    assert out["pledge_ratio"] == pytest.approx(0.03)
    assert out["pledge_live_records"] == 2
    assert out["pledge_source"] == "detail"


def test_audit_does_not_veto_on_low_confidence_detail_pledge():
    """★★ detail 来源**不参与一票否决**，只警示。

    实测 800 只采样：detail 来源 43 只里只有 2 只超 70%（600282 93.39% 等）。
    明细存在「部分解押留多条记录」的重复计问题 ⇒ 精度不足以支撑不可逆否决。
    真正的高质押风险股几乎都有汇总表（采样中 company 来源 317 只全覆盖）。
    """
    gov = _gov(0.80, None)
    gov["pledge_source"] = "detail"
    out = filter_audit([{"code": "600282", "name": "明细回溯高值"}],
                       _StubCollector(gov), max_workers=1)
    assert len(out) == 1, "低置信度的明细回溯值不得触发一票否决"
    assert out[0]["pledge_low_confidence"] is True


def test_audit_treats_inconsistent_detail_as_unverified_not_vetoed():
    """明细不自洽 ⇒ 按「不可核验」降权放行，绝不因此否决。"""
    gov = _gov(None, None)
    gov["pledge_source"] = "detail_inconsistent"
    out = filter_audit([{"code": "002269", "name": "明细不自洽"}],
                       _StubCollector(gov), max_workers=1)
    assert len(out) == 1
    assert out[0]["audit_status"] == "UNVERIFIED_PLEDGE"
    assert out[0]["pledge_ratio"] is None


def test_audit_still_vetoes_high_pledge_from_summary_table():
    """对照组：company 来源（有汇总表）的高质押**照常否决**。"""
    gov = _gov(0.80, None)
    gov["pledge_source"] = "company"
    out = filter_audit([{"code": "600001", "name": "汇总表高值"}],
                       _StubCollector(gov), max_workers=1)
    assert out == []


def test_pledge_source_precedence_company_over_holder_over_detail():
    """三级回退优先级：company(table2) > holder(table1) > detail(table0)。"""
    common_detail = [_live_record("甲", 100.0, 1.0, 9.0)]

    as_company = parse_pledge_response(_resp(
        holders=[{"t003": "甲", "t016": 20.0, "t021": 50.0, "t018": "2026-01-01"}],
        zzgb=12.0, records=common_detail,
    ))
    assert (as_company["pledge_source"], as_company["pledge_ratio"]) == ("company", 0.12)

    as_holder = parse_pledge_response(_resp(
        holders=[{"t003": "甲", "t016": 20.0, "t021": 50.0, "t018": "2026-01-01"}],
        zzgb=None, records=common_detail,
    ))
    assert (as_holder["pledge_source"], as_holder["pledge_ratio"]) == ("holder", 0.20)

    as_detail = parse_pledge_response(_resp(holders=[], zzgb=None, records=common_detail))
    assert (as_detail["pledge_source"], as_detail["pledge_ratio"]) == ("detail", 0.01)


def test_pledge_none_when_channel_unverifiable():
    """★ NFR-02：通道故障必须返回 None，**绝不**兜底成 0.0。

    0.0 会让"通道故障"与"确认无质押"不可区分 —— 那正是 P0-3 的旧事故形态。
    """
    assert parse_pledge_response(None) is None
    assert parse_pledge_response(SimpleNamespace(ok=False, tables=())) is None
    assert parse_pledge_response(SimpleNamespace(ok=True, tables=(_table([]),))) is None


# ══════════════════════════════════════════════════ 排雷判据
class _StubCollector:
    """只提供治理数据的最小替身。"""

    def __init__(self, gov: dict) -> None:
        self.gov = gov

    def get_f10_governance_and_concept(self, code_str: str) -> dict:
        return self.gov


def _gov(total_ratio: float | None, own_ratio: float | None) -> dict:
    return {
        "pledge_ratio": total_ratio,
        "company_pledge_ratio": total_ratio,
        "pledge_ratio_of_own_max": own_ratio,
        "total_pledge_shares": 0.0,
        "pledge_details": [],
        "top_pledgor": "某股东",
        "has_violation_record": False,
        "violation_count": 0,
        "recent_violation_count": 0,
        "violations": [],
        "has_reduction_plan": False,
        "concepts": [],
        "main_business": [],
    }


def test_audit_rejects_high_total_share_pledge():
    """质押占总股本 > 70% ⇒ 一票否决（这是 PLEDGE_FATAL_RATIO 的本义）。"""
    out = filter_audit([{"code": "600001", "name": "高质押"}],
                       _StubCollector(_gov(0.75, None)), max_workers=1)
    assert out == []


def test_audit_does_not_reject_white_horse_with_fully_pledged_minority_stake():
    """★★ 格力回归：控股股东 100% 质押，但占总股本仅 15.35% ⇒ **不得**否决。

    若这条失败，说明又把"占其持股比例"喂给了"占总股本口径"的阈值。
    """
    out = filter_audit([{"code": "000651", "name": "格力电器"}],
                       _StubCollector(_gov(0.1535, 1.0)), max_workers=1)
    assert len(out) == 1
    assert out[0]["pledge_ratio"] == pytest.approx(0.1535)
    assert out[0]["pledge_ratio_of_own_max"] == pytest.approx(1.0)
    assert out[0]["pledge_own_high_risk"] is True      # 保留高危标记供降权


def test_audit_rejects_when_own_pledge_high_and_scale_is_large():
    """占其持股 >95% **且** 占总股本 >20% ⇒ 大规模强平的踩踏风险，否决。"""
    out = filter_audit([{"code": "600002", "name": "爆仓高危"}],
                       _StubCollector(_gov(0.30, 0.98)), max_workers=1)
    assert out == []


def test_audit_treats_unverified_pledge_as_not_fatal():
    """通道不可核验 ⇒ 降权放行并标 ``UNVERIFIED_PLEDGE``，不当作"确认无质押"。"""
    out = filter_audit([{"code": "600003", "name": "未核验"}],
                       _StubCollector(_gov(None, None)), max_workers=1)
    assert len(out) == 1
    assert out[0]["audit_status"] == "UNVERIFIED_PLEDGE"
    assert out[0]["pledge_ratio"] is None
