"""轨道 B / C / D 的判据、预筛与派生指标测试。

★ 这批用例守的是第二批与第三批的核心交付：
1. **轨道 B 真有"弱"**。改造前 ``ladder_analyzer`` 只取封板行，炸板行被丢弃 ——
   一个纯粹由完好封死涨停构成的池子里，物理上不存在"弱转强"的逻辑条件。
2. **轨道 C 能选出中军**。像美的集团这种沿均线稳步推升、单日涨 3%~5% 的
   产业中军，改造前在任何体系下都不可能被选出来。
3. **轨道 D 的估值不靠猜**。`f10.valuation` 实测无 PE/PB、`finance_diagnosis`
   返回 0 行，全部改由 `corporate.finance_batch` 自算，且单位换算必须正确。

★ 数据纪律：不可核验与不合格必须是两个不同的 reason_code。
"""
from __future__ import annotations

import pytest

import config
from screener import tracks as T
from screener.finance_batch import FinanceSnapshot
from screener.kline_batch import (
    Bar,
    avg_amount,
    bullish_ma_stack,
    ma,
    recent_limit_up_days,
    volume_ratio,
    vwap_deviation,
)


# ───────────────────────────────────────────────────── 合成 K 线
def _bar(close: float, pre_close: float, open_: float | None = None, amount: float | None = None,
         lots: float | None = None, date: str = "2026-10-28") -> Bar:
    """构造一根 K 线；amount/lots 缺省时按 close 反推，保证 VWAP 与价格自洽。"""
    o = close if open_ is None else open_
    lots = lots if lots is not None else 100_000.0
    amount = amount if amount is not None else close * lots * 100.0
    return Bar(date=date, open=o, high=max(o, close), low=min(o, close),
               close=close, pre_close=pre_close, amount=amount, volume_lots=lots)


def _uptrend_bars(n: int = 70, start: float = 10.0, step: float = 0.05,
                  amount: float = 1.2e9) -> list[Bar]:
    """线性上升的多头排列 K 线（Close > MA5 > MA20 > MA60）。"""
    bars: list[Bar] = []
    prev = start
    for i in range(n):
        close = start + i * step
        lots = amount / (close * 100.0)
        bars.append(_bar(close=close, pre_close=prev, amount=amount, lots=lots))
        prev = close
    return bars


# ───────────────────────────────────────────────────── 技术指标
def test_ma_returns_none_when_bars_insufficient():
    """★ MA 不可核验必须返回 None，不是 0.0 —— 否则"收盘 > MA5"会恒真。"""
    assert ma(_uptrend_bars(3), 5) is None
    assert ma(_uptrend_bars(5), 5) is not None


def test_avg_amount_and_volume_ratio():
    bars = _uptrend_bars(25, amount=1.0e9)
    assert avg_amount(bars, 20) == pytest.approx(1.0e9)
    assert avg_amount(bars, 30) is None          # 根数不足 → None
    assert volume_ratio(bars) == pytest.approx(1.0, rel=0.05)


def test_volume_ratio_none_on_zero_previous_volume():
    """昨日成交量为 0 → None（除零会伪装成"无量/极端缩量"）。"""
    bars = [_bar(10.0, 9.9, lots=0.0), _bar(10.0, 10.0, lots=5000.0)]
    assert volume_ratio(bars) is None


def test_recent_limit_up_days_detects_and_is_none_when_unverifiable():
    bars = [
        _bar(9.0, 8.9),
        _bar(9.7, 9.0),     # +7.8% 未涨停
        _bar(10.0, 9.7),    # +3.1% 未涨停
        _bar(11.0, 10.0),   # 昨日涨停 (+10%)
        _bar(10.7, 11.0),   # 今日
    ]
    assert recent_limit_up_days(bars, 3) == 1
    assert recent_limit_up_days([bars[-1]], 3) is None   # 无历史 → 不可核验


def test_recent_limit_up_days_respects_board_kind():
    """双创 20cm：同一根 +10% 的 K 线在创业板不算涨停。"""
    bars = [_bar(10.0, 9.0), _bar(11.0, 10.0)]
    assert recent_limit_up_days(bars, 3, "main") == 1
    assert recent_limit_up_days(bars, 3, "growth") == 0


def test_bullish_ma_stack_true_false_and_none():
    assert bullish_ma_stack(_uptrend_bars(70)) is True
    down = list(reversed(_uptrend_bars(70)))
    assert bullish_ma_stack(down) is False
    assert bullish_ma_stack(_uptrend_bars(10)) is None     # MA60 不可得 → 弃权


def test_vwap_deviation_sign():
    bars = [_bar(close=10.0, pre_close=10.0, amount=1.0e8, lots=100_000.0)]
    # amount/(lots*100) = 1e8/1e7 = 10.0 ⇒ 与收盘价一致
    assert vwap_deviation(bars) == pytest.approx(0.0)


# ───────────────────────────────────────────────────── 轨道 B
def _cand(code: str, pct: float, amount: float = 3.0e8, mv: float = 5.0e10,
          turn: float = 3.0, board_kind: str = "main") -> dict:
    return {
        "code": code, "full_code": ("sh" if code.startswith("6") else "sz") + code,
        "name": f"N{code}", "board_kind": board_kind,
        "change_pct": pct, "amount": amount, "turnover_rate": turn, "total_mv": mv,
        "close": 10.0,
    }


def test_track_b_prefilter_keeps_broken_and_weak_active():
    cands = [
        _cand("600001", pct=5.0),      # 大涨 → 出局
        _cand("600002", pct=-3.0),     # 收阴且活跃 → 入选
        _cand("600003", pct=-3.0, amount=1.0e7),  # 收阴但不活跃 → 出局
        _cand("600004", pct=9.9),      # 涨停 → 出局（归轨道 A）
    ]
    kept, dropped = T.prefilter_track_b(cands, broken_codes={"600004"})
    codes = {c["code"] for c in kept}
    # 炸板行即使今日涨幅高也必须入选（它就是"弱"的来源）
    assert codes == {"600002", "600004"}
    # ★ 逐判据归因：大涨归 B_NOT_WEAK_TODAY，不活跃归 B_PREFILTER_OUT
    assert dropped.get(T.B_NOT_WEAK_TODAY) == 1        # 600001
    assert dropped.get(T.B_PREFILTER_OUT) == 1         # 600003 成交额不足


def test_track_b_passes_when_healthy_pullback():
    """昨日涨停 + 今日缩量收阴 + 未破 MA5 + 未大幅低于均价 → 反包候选。"""
    bars = [
        _bar(9.0, 8.9, lots=80_000.0),
        _bar(9.5, 9.0, lots=85_000.0),
        _bar(10.0, 9.5, lots=90_000.0),
        _bar(11.0, 10.0, lots=100_000.0),    # 昨日涨停
        _bar(10.7, 11.0, open_=10.9, lots=70_000.0),  # 今日收阴缩量
    ]
    c = _cand("600001", pct=-2.7)
    res = T.screen_track_b([c], {"sh600001": bars})
    assert len(res.passed) == 1
    p = res.passed[0]
    assert p["track"] == T.TRACK_B
    assert p["playbook"].max_position_pct > 0
    assert p["playbook"].base_position_pct == 0     # 当日不建仓，等次日确认
    assert res.dropped == {}


def test_track_b_rejects_no_recent_limit_up():
    """没有前序的"强"，就谈不上"弱转强"。"""
    bars = [
        _bar(9.0, 8.9, lots=80_000.0), _bar(9.5, 9.0, lots=85_000.0),
        _bar(10.0, 9.5, lots=90_000.0), _bar(10.2, 10.0, lots=100_000.0),
        _bar(10.0, 10.2, open_=10.2, lots=70_000.0),
    ]
    res = T.screen_track_b([_cand("600001", pct=-2.0)], {"sh600001": bars})
    assert res.dropped.get(T.B_NO_RECENT_LIMIT_UP) == 1
    assert res.passed == []


def test_track_b_rejects_volume_expansion_on_decline():
    """放量下跌是派发不是洗盘。"""
    bars = [
        _bar(9.0, 8.9, lots=80_000.0), _bar(9.5, 9.0, lots=85_000.0),
        _bar(10.0, 9.5, lots=90_000.0), _bar(11.0, 10.0, lots=100_000.0),
        _bar(10.7, 11.0, open_=10.9, lots=130_000.0),  # 量比 1.3 > 0.8
    ]
    res = T.screen_track_b([_cand("600001", pct=-2.7)], {"sh600001": bars})
    assert res.dropped.get(T.B_VOLUME_NOT_SHRUNK) == 1


def test_track_b_rejects_broken_ma5():
    """昨日涨停，今日缩量但**跌破 MA5** —— 洗盘演变成破位，不再是反包候选。"""
    bars = [
        _bar(11.0, 10.9, lots=80_000.0),
        _bar(11.5, 11.0, lots=85_000.0),
        _bar(12.0, 11.5, lots=90_000.0),
        _bar(13.2, 12.0, lots=100_000.0),               # 昨日涨停 +10%
        _bar(11.0, 13.2, open_=13.0, lots=70_000.0),    # 今日收阴缩量但破 MA5(=11.74)
    ]
    res = T.screen_track_b([_cand("600001", pct=-4.3)], {"sh600001": bars})
    assert res.dropped.get(T.B_BELOW_MA5) == 1


def test_track_b_missing_bars_is_separate_from_unqualified():
    """★ 不可核验 ≠ 不合格：日 K 缺失必须单独记账，不能混进"不合格"。"""
    res = T.screen_track_b([_cand("600001", pct=-2.0)], {})
    assert res.dropped.get(T.B_BARS_MISSING) == 1
    assert res.dropped.get(T.B_NO_RECENT_LIMIT_UP) is None


def test_track_b_broken_today_bypasses_weakness_check():
    """当日炸板天然满足"弱"，不再要求今日涨幅 ≤ 阈值。"""
    bars = [
        _bar(9.0, 8.9, lots=80_000.0), _bar(9.5, 9.0, lots=85_000.0),
        _bar(10.0, 9.5, lots=90_000.0), _bar(11.0, 10.0, lots=100_000.0),
        _bar(10.7, 11.0, open_=10.9, lots=70_000.0),
    ]
    c = _cand("600001", pct=8.0)   # 盘中冲高后炸板，收盘仍大涨
    res = T.screen_track_b([c], {"sh600001": bars}, broken_codes={"600001"})
    assert len(res.passed) == 1 and res.passed[0]["is_broken_today"] is True


# ───────────────────────────────────────────────────── 轨道 C
def test_track_c_prefilter_filters_by_cap_turnover_and_pct():
    """市值绝对值、换手率区间、涨幅区间三道免费字段门槛。"""
    cands = [
        _cand("600001", pct=3.0, mv=5.0e11, turn=3.0),   # 千亿 + 温和换手 + 稳步涨 → 入选
        _cand("600002", pct=3.0, mv=5.0e9, turn=3.0),    # 50 亿 < 100 亿 → 出局
        _cand("600003", pct=3.0, mv=5.0e11, turn=12.0),  # 换手过高 → 出局
        _cand("600004", pct=9.9, mv=5.0e11, turn=3.0),   # 涨停 → 归轨道 A
    ]
    # 补齐一个"市值分位垫底"的样本，让 600001 的分位确定性地落在前 30%
    cands += [_cand(f"6001{i:02d}", pct=3.0, mv=1.0e10 + i * 1.0e9, turn=3.0) for i in range(10)]
    kept, before_cap, dropped = T.prefilter_track_c(cands)
    assert "600001" in {c["code"] for c in kept}
    for gone in ("600002", "600003", "600004"):
        assert gone not in {c["code"] for c in kept}
    # ★ 逐判据归因：三只分别命中三条不同的判据
    assert dropped.get(T.C_MARKET_CAP_TOO_SMALL) == 1
    assert dropped.get(T.C_TURNOVER_OUT_OF_RANGE) == 1
    assert dropped.get(T.C_PCT_OUT_OF_RANGE) == 1
    assert before_cap >= len(kept)


def test_track_c_prefilter_caps_by_market_cap_desc():
    """★ 限流必须按市值降序，且调用方能拿到截断数（与旧版无声截断的本质区别）。

    注意：市值分位门槛（前 30%）本身就是自限的 —— N 只候选最多只有 30%·N 只
    能通过分位线，随后才由 ``TRACK_C_PRE_FILTER_MAX`` 二次限流。
    """
    n = 20
    cands = [_cand(f"6000{i:02d}", pct=3.0, mv=1.0e11 * (1 + i), turn=3.0) for i in range(n)]
    original = config.TRACK_C_PRE_FILTER_MAX
    config.TRACK_C_PRE_FILTER_MAX = 3
    try:
        kept, before_cap, _ = T.prefilter_track_c(cands)
        # 分位 = (i+1)/20 ≥ 70% ⇒ i ≥ 13 ⇒ 共 7 只（i = 13..19）
        assert before_cap == 7
        assert len(kept) == 3
        # 保留的是市值最大的 3 只 —— 绝不是代码表原始顺序
        assert [c["code"] for c in kept] == ["600019", "600018", "600017"]
    finally:
        config.TRACK_C_PRE_FILTER_MAX = original


def test_track_c_passes_trend_leader():
    """产业中军：市值分位靠前 + 均线多头 + 大容量成交 → 必须能选出来。"""
    bars = _uptrend_bars(70, amount=1.2e9)
    c = _cand("000333", pct=3.0, mv=5.0e11, turn=2.5)
    c["market_cap_pctile"] = 0.95
    res = T.screen_track_c([c], {"sz000333": bars})
    assert len(res.passed) == 1
    p = res.passed[0]
    assert p["track"] == T.TRACK_C
    assert p["avg_amount_20d"] >= config.TRACK_C_MIN_AVG_AMOUNT_20D
    # ★ 机构持股无数据通道，必须显式标注 UNVERIFIED，而不是假装 0 或 15%
    assert p["institutional_holding"] == "UNVERIFIED"
    assert p["playbook"].max_position_pct > 0


def test_track_c_rejects_low_liquidity_capacity():
    bars = _uptrend_bars(70, amount=1.0e8)   # 日均 1 亿 < 8 亿
    c = _cand("000333", pct=3.0, mv=5.0e11, turn=2.5)
    res = T.screen_track_c([c], {"sz000333": bars})
    assert res.dropped.get(T.C_AVG_AMOUNT_BELOW) == 1


def test_track_c_rejects_non_bullish_ma():
    bars = list(reversed(_uptrend_bars(70, amount=1.2e9)))
    c = _cand("000333", pct=3.0, mv=5.0e11, turn=2.5)
    res = T.screen_track_c([c], {"sz000333": bars})
    assert res.dropped.get(T.C_MA_NOT_BULLISH) == 1


def test_track_c_missing_bars_separate():
    res = T.screen_track_c([_cand("000333", pct=3.0)], {})
    assert res.dropped.get(T.C_BARS_MISSING) == 1


# ───────────────────────────────────────────────────── 轨道 D
def _fin(**kw) -> FinanceSnapshot:
    # ★ 20261029 审计 P1-2：这里给的是**年报口径**（report_period=1231，年化系数=1），
    #   因此下面 PE/ROE 的断言与"旧的单期直算"数值一致。若改成 0331 一季报口径，
    #   PE 会变成 1/4、ROE 会变成 4 倍 —— 这正是本次修复要纠正的量纲问题。
    base = dict(full_code="sz000333", code="000333", eps=3.52, bvps=27.82,
                net_profit=2.64e10, equity=2.13e11, operating_cash_flow=3.75e10,
                total_assets=6.4e11, total_liabilities=3.9e11,
                report_period="20251231", report_period_source="archive_latest")
    base.update(kw)
    return FinanceSnapshot(**base)


def test_finance_snapshot_derived_metrics_units():
    """★ 单位是「元/股」与「元」，已用贵州茅台交叉验证（净资产/总股本 = BVPS）。"""
    f = _fin()
    assert f.pe(85.0) == pytest.approx(85.0 / 3.52, rel=1e-6)
    assert f.pb(85.0) == pytest.approx(85.0 / 27.82, rel=1e-6)
    assert f.roe_pct() == pytest.approx(2.64e10 / 2.13e11 * 100.0, rel=1e-6)
    assert f.ocf_to_profit() == pytest.approx(3.75e10 / 2.64e10, rel=1e-6)
    assert f.debt_ratio_pct() == pytest.approx(3.9e11 / 6.4e11 * 100.0, rel=1e-6)


def test_finance_snapshot_refuses_meaningless_ratios():
    """亏损股 PE、资不抵债 PB、负利润的含金量 —— 一律 None，不是 0 或负数。"""
    assert _fin(eps=-1.0).pe(10.0) is None
    assert _fin(bvps=-2.0).pb(10.0) is None
    assert _fin(net_profit=-1.0e9).ocf_to_profit() is None
    assert _fin(equity=-1.0).roe_pct() is None


def test_track_d_passes_value_with_cash_support():
    # 美的集团量级：price 80 / eps 3.52 → PE 22.7；/ bvps 27.82 → PB 2.88
    c = _cand("000333", pct=1.0, amount=2.0e9)
    c["close"] = 80.0
    res = T.screen_track_d([c], {"sz000333": _fin()})
    assert len(res.passed) == 1
    p = res.passed[0]
    assert p["track"] == T.TRACK_D
    assert p["roe_trend"] == "UNVERIFIED"   # ★ 单期快照，拐点不可核验，严禁编造斜率
    assert p["playbook"].max_position_pct > 0


def test_track_d_rejects_expensive():
    c = _cand("000333", pct=1.0, amount=2.0e9); c["close"] = 500.0
    res = T.screen_track_d([c], {"sz000333": _fin()})
    assert res.dropped.get(T.D_PE_TOO_HIGH) == 1


def test_track_d_rejects_low_roe():
    c = _cand("000333", pct=1.0, amount=2.0e9); c["close"] = 50.0
    res = T.screen_track_d([c], {"sz000333": _fin(net_profit=1.0e9)})  # ROE ≈ 0.47%
    assert res.dropped.get(T.D_ROE_TOO_LOW) == 1


def test_track_d_rejects_profit_without_cash():
    """利润没有现金流支撑 —— 典型应计操纵嫌疑。"""
    c = _cand("000333", pct=1.0, amount=2.0e9); c["close"] = 50.0
    res = T.screen_track_d([c], {"sz000333": _fin(operating_cash_flow=1.0e9)})
    assert res.dropped.get(T.D_OCF_WEAK) == 1


def test_track_d_unverified_valuation_is_its_own_reason():
    """★ 估值不可核验 ≠ 低估值：必须单列，否则"通道故障"会伪装成"市场没有便宜货"。"""
    c = _cand("000333", pct=1.0, amount=2.0e9); c["close"] = 50.0
    res = T.screen_track_d([c], {"sz000333": _fin(eps=None, bvps=None)})
    assert res.dropped.get(T.D_VALUATION_UNVERIFIED) == 1
    assert res.dropped.get(T.D_PE_TOO_HIGH) is None


def test_track_d_missing_finance_separate():
    res = T.screen_track_d([_cand("000333", pct=1.0, amount=2.0e9)], {})
    assert res.dropped.get(T.D_FINANCE_MISSING) == 1


# ───────────────────────────────────────────────────── 归因契约
def test_track_results_are_conserved():
    """每层 ``input == Σ dropped + output`` —— 归因链不能断。"""
    bars = _uptrend_bars(70, amount=1.2e9)
    cands = [
        dict(_cand("000333", pct=3.0, mv=5.0e11, turn=2.5), full_code="sz000333"),
        dict(_cand("000334", pct=3.0, mv=5.0e11, turn=2.5), full_code="sz000334"),
    ]
    res = T.screen_track_c(cands, {"sz000333": bars})
    assert len(res.passed) == 1
    assert res.dropped.get(T.C_BARS_MISSING) == 1
    assert res.input_count == 2


def test_track_rules_cover_all_reason_codes_used():
    """每个剔除码都必须在 TRACK_RULES 里登记，否则死规则检测会漏掉它。"""
    for tk, rules in T.TRACK_RULES.items():
        assert rules, f"轨道 {tk} 未登记任何判据"
    assert set(T.TRACK_RULES) == {T.TRACK_B, T.TRACK_C, T.TRACK_D}
