"""F10 深度取数测试：多期财报拐点 + 十大流通股东机构持股。

★ 这批用例守的是两条**被推翻的既有结论**
---------------------------------------------
此前代码注释断言：
    「ROE 边际拐点不可得：finance_batch 只给单期快照」
    「机构持股无数据通道：eltdx 不给前十大流通股东」

实测证明这两条都是**用错了通道**：

* ``CWServ.tdxf10_gg_cwfx``（``finance_report``）一次返回 **32~114 个报告期**，
  每行带 ``rq`` ⇒ 拐点**可核验**；
* ``CWServ.tdxf10_gg_gdyj`` + ``section="ltgd"`` 的 ``tables[1]`` 返回
  **10 名股东 × 18 个报告期**，每行带 ``lb`` 类别 + ``cgs`` 持股数 ⇒ 机构持股**可算**。

教训固化在 :mod:`screener.f10_deep` 的模块文档里：判定"无数据通道"之前，
必须穷举该业务的**全部** Entry，而不只是高级封装方法。
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

import config
from screener import tracks as T
from screener.f10_deep import (
    InstitutionalHolding,
    ProfitTrend,
    parse_institutional_holding,
    parse_profit_trend,
)
from screener.tracks import apply_track_c_institutional, apply_track_d_trend


def _table(rows: list[dict]) -> SimpleNamespace:
    return SimpleNamespace(rows=tuple(rows), count=len(rows))


def _shareholder_resp(rows: list[dict]) -> SimpleNamespace:
    """构造 gdyj/ltgd 响应：tables[0] 股本序列、tables[1] 十大流通股东明细。"""
    return SimpleNamespace(
        ok=True,
        tables=(_table([{"rq": "2026-06-30", "T004": 1}]), _table(rows)),
    )


# ══════════════════════════════════════════════════ 机构持股
def test_institutional_holding_excludes_controlling_corporate():
    """★ 一般法人（控股股东/产业资本）**不得**计入机构 —— 否则指标失效。

    实测美的控股占十大流通股东 48.6%，若把它算作"机构"，
    任何有大股东的公司都会虚假地"机构重仓"。
    """
    rows = [
        {"rq": "2026-06-30", "gd": "美的控股有限公司", "lb": "一般法人", "cgs": 2_169_178_713},
        {"rq": "2026-06-30", "gd": "香港中央结算有限公司", "lb": "北上资金", "cgs": 893_478_198},
        {"rq": "2026-06-30", "gd": "中国人寿保险-005L", "lb": "保险", "cgs": 206_856_697},
        {"rq": "2026-06-30", "gd": "中央汇金", "lb": "特殊法人", "cgs": 88_260_460},
        {"rq": "2026-06-30", "gd": "黄健", "lb": "自然人", "cgs": 86_140_000},
    ]
    hold = parse_institutional_holding("000333", _shareholder_resp(rows))
    assert hold is not None
    total = 2_169_178_713 + 893_478_198 + 206_856_697 + 88_260_460 + 86_140_000

    # 机构 = 北上资金 + 保险（严格机构口径）
    assert hold.institutional_ratio == pytest.approx((893_478_198 + 206_856_697) / total)
    # 国家队单独统计，不计入严格机构
    assert hold.state_ratio == pytest.approx(88_260_460 / total)
    assert hold.corporate_ratio == pytest.approx(2_169_178_713 / total)
    assert hold.retail_ratio == pytest.approx(86_140_000 / total)
    assert hold.verified is True
    assert hold.report_date == "2026-06-30"


def test_institutional_holding_uses_latest_period_only():
    """多报告期时必须只取**最新一期**，否则会把历史股东重复计入。"""
    rows = [
        {"rq": "2025-12-31", "gd": "旧机构", "lb": "基金", "cgs": 1000},
        {"rq": "2026-06-30", "gd": "新机构", "lb": "基金", "cgs": 300},
        {"rq": "2026-06-30", "gd": "自然人甲", "lb": "自然人", "cgs": 100},
    ]
    hold = parse_institutional_holding("000001", _shareholder_resp(rows))
    assert hold.report_date == "2026-06-30"
    assert hold.institutional_ratio == pytest.approx(300 / 400)
    assert hold.periods == 2


def test_institutional_holding_returns_none_on_empty():
    """空响应 → None（不可核验），**不是**"零机构持股"。"""
    assert parse_institutional_holding("000001", _shareholder_resp([])) is None
    assert parse_institutional_holding("000001", SimpleNamespace(ok=True, tables=())) is None
    assert parse_institutional_holding(
        "000001", _shareholder_resp([{"rq": "2026-06-30", "gd": "X", "lb": "基金", "cgs": None}])
    ) is None


def test_track_c_institutional_never_drops_a_stock():
    """★ 用户裁决：机构持股**不参与准入**，只加权/降权。

    取不到股东数据是通道问题，不是标的问题 —— 绝不能据此淘汰一只合格中军。
    """
    passed = [
        {"code": "000001", "name": "达标", "total_mv": 5e11},
        {"code": "000002", "name": "未达标", "total_mv": 5e11},
        {"code": "000003", "name": "不可核验", "total_mv": 5e11},
    ]
    holdings = {
        "000001": InstitutionalHolding(code="000001", institutional_ratio=0.40),
        "000002": InstitutionalHolding(code="000002", institutional_ratio=0.05),
    }
    out, tiers = apply_track_c_institutional(passed, holdings)
    assert len(out) == 3, "机构持股不得淘汰任何标的"
    assert tiers == {"1": 1, "2": 1, "3": 1}
    # 排序：达标 → 未达标 → 不可核验
    assert [c["code"] for c in out] == ["000001", "000002", "000003"]
    assert out[0]["institutional_holding"] == "40.0%"
    assert out[2]["institutional_holding"] == "UNVERIFIED"
    assert out[2]["institutional_ratio"] is None


# ══════════════════════════════════════════════════ 多期拐点
def _income(periods: list[tuple[str, float]]) -> SimpleNamespace:
    return _table([{"rq": rq, "T030": v} for rq, v in periods])


def _quarters(start: int = 2019, n: int = 8, base: float = 100.0,
              growth: list[float] | None = None) -> list[tuple[str, float]]:
    """生成 n 年 × 4 季度的累计口径归母净利润。growth[i] = 第 i 年相对倍数。"""
    growth = growth or [1.0] * n
    out = []
    for i in range(n):
        year = start + i
        for md in ("03-31", "06-30", "09-30", "12-31"):
            out.append((f"{year}-{md}", base * growth[i]))
    out.sort(key=lambda kv: kv[0], reverse=True)
    return out


def _explicit(fy: tuple[float, float], q3: tuple[float, float]) -> list[tuple[str, float]]:
    """构造 8 期：只需控制 **最新期(12-31)** 与 **上一期(09-30)** 的今年/去年值。

    ★ 注意：不能让同一年内 4 个季度取同一个值 —— 那样任意两期的同比都相等，
      ``yoy_delta_pp`` 恒为 0，永远测不出加速/减速（实测踩到过）。
      ``fy=(今年, 去年)``、``q3=(今年, 去年)``。
    """
    vals = {
        "2026-12-31": fy[0], "2025-12-31": fy[1],
        "2026-09-30": q3[0], "2025-09-30": q3[1],
        "2026-06-30": 1.0, "2025-06-30": 1.0,
        "2026-03-31": 1.0, "2025-03-31": 1.0,
    }
    return sorted(vals.items(), key=lambda kv: kv[0], reverse=True)


def test_profit_trend_turning_positive():
    """★ 困境反转的核心形态：上期同比为负、本期同比转正。"""
    # 最新期 110/100 = +10%（正）；上一期 80/100 = -20%（负）
    tr = parse_profit_trend("000001", _income(_explicit(fy=(110, 100), q3=(80, 100))))
    assert tr.verified
    assert tr.trend == "turning_positive"
    assert tr.yoy_pct == pytest.approx(10.0)
    assert tr.yoy_prev_pct == pytest.approx(-20.0)
    assert tr.is_positive is True


def test_profit_trend_accelerating_and_decelerating():
    # 最新期同比 +30%，上一期同比 0% ⇒ 边际 +30pp
    acc = parse_profit_trend("000001", _income(_explicit(fy=(130, 100), q3=(100, 100))))
    assert acc.trend == "accelerating"
    assert acc.yoy_delta_pp == pytest.approx(30.0)

    # 最新期同比 0%，上一期同比 +30% ⇒ 边际 -30pp
    dec = parse_profit_trend("000002", _income(_explicit(fy=(100, 100), q3=(130, 100))))
    assert dec.trend == "decelerating"
    assert dec.yoy_delta_pp == pytest.approx(-30.0)


def test_profit_trend_stable():
    flat = _quarters(2019, 8, growth=[1.0] * 8)
    tr = parse_profit_trend("000003", _income(flat))
    assert tr.trend == "stable"
    assert tr.yoy_delta_pp == pytest.approx(0.0)


def test_profit_trend_unverified_when_periods_insufficient():
    """★ 期数不足 → UNVERIFIED，而**不是**"零增长"。次新股常见。"""
    few = _quarters(2024, 1)     # 仅 4 期，算不出两个同比点
    tr = parse_profit_trend("000004", _income(few))
    assert tr.trend == "UNVERIFIED"
    assert tr.verified is False
    assert tr.yoy_pct is None


def test_profit_trend_unverified_when_base_negative():
    """去年同季亏损 ⇒ 同比增速在数学上无定义，返回 UNVERIFIED（不是 +∞）。"""
    periods = _quarters(2019, 8, growth=[1.0, 1.0, 1.0, 1.0, 1.0, 1.0, -1.0, 1.0])
    tr = parse_profit_trend("000005", _income(periods))
    assert tr.trend == "UNVERIFIED"
    assert tr.yoy_pct is None


def test_profit_trend_roe_from_balance_sheet_identity():
    """净资产用恒等式 ``资产总计 - 负债合计``，**不猜**"归母权益"是哪个 T 字段。"""
    periods = _quarters(2019, 8, growth=[1.0] * 8)
    balance = _table([
        {"rq": rq, "T039": 1000.0, "T053": 600.0} for rq, _ in periods
    ])
    tr = parse_profit_trend("000006", _income(periods), balance)
    assert tr.roe_pct == pytest.approx(100.0 / 400.0 * 100.0)     # 净利润100 / 权益400
    assert tr.roe_delta_pp == pytest.approx(0.0)


def test_profit_trend_roe_none_without_balance_sheet():
    """资产负债表不可得时，净利润拐点仍要能算 —— ROE 才是 None。"""
    periods = _quarters(2019, 8, growth=[1.0] * 8)
    tr = parse_profit_trend("000007", _income(periods), None)
    assert tr.verified
    assert tr.trend == "stable"
    assert tr.roe_pct is None


# ══════════════════════════════════════════════════ 轨道 D 拐点准入
def test_track_d_trend_rejects_decelerating_but_keeps_unverified():
    """★ 不可核验 ≠ 不合格：UNVERIFIED 必须放行并标注，只有可核验的恶化才否决。"""
    passed = [
        {"code": "000001", "name": "拐点向上"},
        {"code": "000002", "name": "边际恶化"},
        {"code": "000003", "name": "不可核验"},
    ]
    trends = {
        "000001": ProfitTrend(code="000001", trend="turning_positive", yoy_pct=12.0),
        "000002": ProfitTrend(code="000002", trend="decelerating", yoy_delta_pp=-15.0),
    }
    kept, dropped, unverified = apply_track_d_trend(passed, trends)
    assert [c["code"] for c in kept] == ["000001", "000003"]
    assert dropped == {T.D_TREND_DETERIORATING: 1}
    assert unverified == 1
    assert kept[1]["roe_trend"] == "UNVERIFIED"


def test_track_d_trend_unverified_must_not_be_counted_as_dropped():
    """★★ 守恒陷阱回归（20261028 首跑复现「不守恒 差额 -6」）。

    不可核验的标的**仍在输出里**，若同时把它记进 dropped，就会出现
    「同一只票既被记淘汰又在输出中」的重复计数，归因矩阵直接报不守恒。
    """
    passed = [{"code": f"00000{i}"} for i in range(1, 7)]
    trends = {"000001": ProfitTrend(code="000001", trend="decelerating")}
    kept, dropped, unverified = apply_track_d_trend(passed, trends)

    assert len(kept) == 5                      # 只有 1 只被"边际恶化"否决
    assert sum(dropped.values()) == 1
    assert unverified == 5
    # ★ 核心不变量：input == Σdropped + output，UNVERIFIED 不参与
    assert len(passed) == sum(dropped.values()) + len(kept)


def test_track_d_trend_can_be_disabled():
    original = config.TRACK_D_TREND_ENABLED
    config.TRACK_D_TREND_ENABLED = False
    try:
        kept, dropped, unverified = apply_track_d_trend([{"code": "000001"}], {})
        assert dropped == {} and unverified == 0
        assert kept[0]["roe_trend"] == "DISABLED"
    finally:
        config.TRACK_D_TREND_ENABLED = original


def test_track_d_trend_soft_mode_keeps_decelerating():
    """``TRACK_D_TREND_REJECT_DETERIORATING=False`` 时拐点只标注、不否决。"""
    original = config.TRACK_D_TREND_REJECT_DETERIORATING
    config.TRACK_D_TREND_REJECT_DETERIORATING = False
    try:
        kept, dropped, _ = apply_track_d_trend(
            [{"code": "000002"}],
            {"000002": ProfitTrend(code="000002", trend="decelerating")},
        )
        assert len(kept) == 1
        assert dropped == {}
    finally:
        config.TRACK_D_TREND_REJECT_DETERIORATING = original


def test_track_rules_registers_trend_reasons():
    """新剔除码必须登记，否则死规则检测覆盖不到。

    ★ ``D_TREND_UNVERIFIED`` **故意不登记** —— 它不是判据而是数据质量标记，
      且不可核验的标的会保留在输出里；若登记为判据，恒 0 会被死规则检测误报，
      记进 dropped 则会让归因矩阵不守恒。
    """
    assert T.D_TREND_DETERIORATING in T.TRACK_RULES[T.TRACK_D]
    assert T.D_TREND_UNVERIFIED not in T.TRACK_RULES[T.TRACK_D]
