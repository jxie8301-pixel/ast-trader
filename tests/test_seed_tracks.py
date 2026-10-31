"""种子标的**穿透走查**（Seed Validation）—— 联网套件。

用户明确要求的验收口径（第二批/第三批）：

* **巨无霸中军（美的集团 000333）**：必须且只能进入轨道 C（趋势中军轨），
  严禁进入短线打板池（轨道 A）或被误杀；
* **连板妖股（襄阳轴承 000678）**：必须进入轨道 A（连板梯队轨）；
* **断板/收阴标的**：必须进入轨道 B（潜在弱转强观察）；
* **ST / 风险警示标的**：必须在第一步被 100% 拦截在门外。

★ 为什么这里不断言"某只票今天一定被选中"
------------------------------------------
每日行情不同，硬断言"美的今日必入选"会造成每日假红，反而掩盖真正的回归。
    本套件只断言**结构性不变量**：
      · 中军**不得**被打板池截留（口径错配）；
      · 中军**必须**具备轨道 C 的参选资格（不得被误杀）；
      · 涨停股**不得**进入轨道 C（中军不追板）；
      · ST **必须** 100% 出池。
    是否被选中，取决于当日是否真的满足均线多头等判据 —— 那是策略结果而非 bug。

用法::

    pytest tests/test_seed_tracks.py -m seednet
"""
from __future__ import annotations

import pytest

import config
from screener.finance_batch import fetch_finance
from screener.filter_liquidity import filter_liquidity
from screener.profile_batch import fetch_profiles
from screener.tracks import prefilter_track_c, turnover_band
from screener.universe import build_universe

pytestmark = pytest.mark.seednet

#: 产业中军样本（深主板巨无霸，非涨停、非题材炒作）
SEED_MIDCAP_LEADER = "sz000333"     # 美的集团
SEED_MIDCAP_CODE = "000333"
#: 连板妖股样本（深主板，20261028 实测为 5 板空间板）
SEED_LADDER_LEADER = "sz000678"     # 襄阳轴承
SEED_LADDER_CODE = "000678"


def _candidate_from_profile(full_code: str) -> dict | None:
    """用真实画像构造一个轨道判据可直接消费的候选字典。"""
    profiles, _ = fetch_profiles([full_code])
    snap = profiles.get(full_code)
    if snap is None:
        pytest.skip(f"{full_code} 画像不可得（通道异常，非判据问题）")
    return {
        "code": snap.code or full_code[2:],
        "full_code": full_code,
        "name": snap.name or "",
        "board_kind": ("growth" if (snap.board or "").endswith(("star_market", "chinext")) else "main"),
        "close": snap.last_price,
        "change_pct": snap.change_pct,
        "amount": snap.amount,
        "turnover_rate": snap.turnover_rate,
        "total_mv": snap.total_market_value,
    }


def test_midcap_leader_is_not_captured_by_track_a():
    """★ 中军绝不能被打板池截留 —— 那是口径错配，不是"没被选中"。"""
    c = _candidate_from_profile(SEED_MIDCAP_LEADER)
    quotes = {
        c["full_code"]: {
            "close": c["close"], "pre_close": None,
            "pct_chg": c["change_pct"], "amount": c["amount"],
            "turnover_ratio": c["turnover_rate"],
        }
    }
    passed = filter_liquidity([c], quotes)
    assert passed == [], (
        f"美的集团(000333) 进入了轨道 A 打板池 —— 产业中军被短线接力口径截留，"
        f"pct={c['change_pct']} amount={c['amount']}"
    )


def test_midcap_leader_is_eligible_for_track_c():
    """★ 中军必须具备轨道 C 的参选资格 —— 不得被阈值误杀。

    这条正是按市值分档换手率的落点：美的当日换手约 0.345%，
    若沿用统一 1.5%~5% 门槛会在此被误杀。
    """
    c = _candidate_from_profile(SEED_MIDCAP_LEADER)
    kept, before_cap, dropped = prefilter_track_c([c])
    assert dropped == {}, f"美的集团被轨道 C 预筛误杀: {dropped} (turnover={c['turnover_rate']}, mv={c['total_mv']})"
    assert before_cap == 1

    # 换手率分档必须让大市值中军落在区间内
    lo, hi = turnover_band(c["total_mv"])
    assert lo <= (c["turnover_rate"] or 0.0) <= hi


def test_ladder_leader_is_not_misrouted_into_track_c():
    """★ 涨停/连板股属轨道 A，中军轨不追板 —— 反向走查防止两轨互相污染。"""
    c = _candidate_from_profile(SEED_LADDER_LEADER)
    if (c["change_pct"] or 0) < 9.5:
        pytest.skip(f"襄阳轴承当日未涨停（pct={c['change_pct']}），不适用本走查")
    kept, _, _ = prefilter_track_c([c])
    assert kept == [], "涨停股进入了轨道 C（中军不追板，属分轨错配）"


def test_st_stocks_are_blocked_at_l0():
    """★ ST / 风险警示标的必须在母池层被 100% 拦截。"""
    result = build_universe()
    assert result.coverage_ok, f"母池闸门未通过: {result.warnings}"

    kept_codes = {r.code for r in result.rows}
    assert result.excluded.get("ST_RISK_WARNING", 0) > 0, "本次未剔除任何 ST —— 无法证明拦截规则生效"

    from data.eltdx_client import open_client

    with open_client() as client:
        st_rows = list(client.codes.latest_st("sh")) + list(client.codes.latest_st("sz"))
    leaked = [r.code for r in st_rows if r.code in kept_codes]
    assert leaked == [], f"ST 标的泄漏进母池: {leaked}"


def test_institutional_holding_is_verifiable_and_well_formed():
    """★ 机构持股**有数据通道** —— 此前判"无通道"是错的（用错了 Entry）。

    通道：``CWServ.tdxf10_gg_gdyj`` + ``section="ltgd"`` 的 ``tables[1]``。
    """
    from screener.f10_deep import fetch_institutional_holdings

    holdings, stats = fetch_institutional_holdings([SEED_MIDCAP_CODE])
    assert stats["ok"] == 1, f"十大流通股东取数失败: {stats}"
    hold = holdings[SEED_MIDCAP_CODE]

    assert hold.verified
    assert hold.periods >= 4, f"报告期数过少: {hold.periods}"
    assert hold.institutional_ratio is not None
    # 四类占比之和不得超过 1（允许有"其他"桶）
    total = (hold.institutional_ratio + hold.state_ratio
             + hold.corporate_ratio + hold.retail_ratio)
    assert 0 < total <= 1.0 + 1e-9, f"占比之和异常: {total}"
    # 美的：产业资本(美的控股)占大头，机构(北上资金+保险)次之 —— 结构性校验
    assert hold.corporate_ratio > 0, "未见产业资本（控股股东）"


def test_profit_trend_is_verifiable_from_multi_period_reports():
    """★ ROE/净利润边际拐点**可核验** —— 此前判"单期快照不可得"是错的。

    通道：``CWServ.tdxf10_gg_cwfx`` 一次返回 32~114 个报告期。
    """
    from screener.f10_deep import fetch_profit_trends

    trends, stats = fetch_profit_trends([SEED_MIDCAP_CODE])
    assert stats["ok"] == 1, f"多期财报取数失败: {stats}"
    tr = trends[SEED_MIDCAP_CODE]

    assert tr.periods >= 8, f"报告期数不足以判拐点: {tr.periods}"
    assert tr.verified, "拐点不可核验"
    assert tr.trend in ("turning_positive", "accelerating", "stable", "decelerating")
    assert tr.yoy_pct is not None and tr.yoy_delta_pp is not None
    # ROE 由恒等式 净资产=资产总计-负债合计 推出，量级必须在合理区间
    assert tr.roe_pct is not None and 0 < tr.roe_pct < 60.0, f"ROE 量级异常: {tr.roe_pct}"


def test_pledge_channel_is_reachable_and_two_ratios_are_separated():
    """★ 股权质押**有数据通道** —— ``CWServ.tdxf10_gg_zbyz`` + ``params=["gqzy", code, ""]``。

    此前判断"个股分析中获取不到质押"是错的：通道一直存在，缺陷在于把
    ``t021``（占其持股比例）当成了 ``pledge_ratio``（占总股本口径）。
    """
    from data.eltdx_collector import EltdxCollector

    gov = EltdxCollector().get_f10_governance_and_concept(SEED_MIDCAP_CODE)
    # 通道可达性：至少"确认无质押(0.0)"或"取到比例"二者之一，不能是 None
    assert gov.get("pledge_ratio") is not None, "质押通道不可核验"

    total = gov["pledge_ratio"]
    own = gov.get("pledge_ratio_of_own_max")
    assert 0.0 <= total <= 1.0, f"质押占总股本比例量级异常: {total}"
    if own is not None:
        assert 0.0 <= own <= 1.0, f"占其持股比例量级异常: {own}"
        # 两个口径必须**分别**存储，且占总股本不得超过占其持股（常识约束）
        assert total <= own + 1e-9, (
            f"口径疑似又混了：占总股本 {total} > 占其持股 {own}"
        )


@pytest.mark.parametrize("code6", ["002850", "300750"])
def test_pledge_live_records_must_never_yield_zero_ratio(code6):
    """★★ 核心不变量：**只要有未解押记录，质押率就不许为 0**。

    科达利 002850 的 ``table1``/``table2`` 全空，只有 ``table0`` 明细有数据；
    旧实现据此判成"确认无质押"，把有质押的票当无质押放行 —— 比误杀更危险。

    这条断言与具体数值无关（不随行情漂移），只守结构不变量：
    ``pledge_live_records > 0 ⇒ pledge_ratio > 0``。
    """
    from data.eltdx_collector import EltdxCollector

    gov = EltdxCollector().get_f10_governance_and_concept(code6)
    ratio = gov.get("pledge_ratio")
    live = int(gov.get("pledge_live_records") or 0)

    assert ratio is not None, f"{code6} 质押不可核验"
    assert gov.get("pledge_source") in (
        "company", "holder", "detail", "none", "detail_inconsistent")
    # 物理上界：质押不可能超过总股本（部分解押留多条记录会让明细累加虚高）
    assert 0.0 <= ratio <= 1.0, f"{code6} 质押率越界: {ratio}"
    if live > 0:
        assert ratio > 0, (
            f"{code6} 有 {live} 笔未解押记录却判出质押率 {ratio} —— 三表填充程度差异未被处理"
        )
    else:
        assert ratio == 0.0, f"{code6} 无在押记录却判出质押率 {ratio}"


def test_midcap_leader_has_verifiable_valuation_inputs():
    """★ 轨道 D 的估值必须由真实财务自算，且量级合理（不是 None、不是荒谬值）。"""
    fin_map, stats = fetch_finance([SEED_MIDCAP_LEADER])
    snap = fin_map.get(SEED_MIDCAP_LEADER)
    if snap is None:
        pytest.skip("财务通道不可得（非判据问题）")

    assert snap.eps and snap.eps > 0
    assert snap.bvps and snap.bvps > 0
    roe = snap.roe_pct()
    assert roe is not None and roe > 0, f"ROE 不可核验: {roe}"
    # 量级合理性：A 股白马半年报 ROE 通常落在 5%~30%，超出即疑似单位换算错误
    assert 0 < roe < 60.0, f"ROE {roe:.2f}% 超出合理量级 —— 疑似单位换算错误"

    price = _candidate_from_profile(SEED_MIDCAP_LEADER).get("close")
    pe, pb = snap.pe(price), snap.pb(price)
    assert pe is not None and 0 < pe < 200, f"PE={pe} 不合理"
    assert pb is not None and 0 < pb < 50, f"PB={pb} 不合理"
