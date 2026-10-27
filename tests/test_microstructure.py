"""Unit tests for Market Microstructure & Smart Money Analyzer."""
from __future__ import annotations

import datetime as dt
from types import SimpleNamespace
import pytest

from core.microstructure import MicrostructureAnalyzer, MicrostructureProfile


def test_microstructure_empty_fallback():
    analyzer = MicrostructureAnalyzer()
    prof = analyzer.analyze([], current_price=10.0)
    assert prof.smart_q == 1.0
    assert prof.smart_phase == "NEUTRAL"
    assert prof.smart_vwap == 10.0


def test_smart_money_accumulation_simulation():
    """测试低吸吸筹识别：高效高敏成交发生在低价格带。"""
    bars = []
    base_time = dt.datetime(2026, 10, 20, 9, 35)

    # 构造 100 根 5 分钟线，总成交量 100,000 手，前 20% 为 20,000 手
    for i in range(100):
        t = base_time + dt.timedelta(minutes=5 * i)
        if i < 20:
            # 低价 10.0 元，1000 手/根，单笔涨幅大 (+2.5%) -> S 值高，全为阳线
            bars.append(SimpleNamespace(
                time=t,
                open=10.0,
                close=10.25,
                volume_lots=1000.0,
                amount=1020000.0,
            ))
        else:
            # 高价 12.0 元，1000 手/根，微幅波动 (+0.05%) -> S 值低，平庸成交
            bars.append(SimpleNamespace(
                time=t,
                open=12.0,
                close=12.006,
                volume_lots=1000.0,
                amount=1200300.0,
            ))

    analyzer = MicrostructureAnalyzer()
    prof = analyzer.analyze(bars, current_price=12.0)

    # 聪明钱时段应该聚焦在低价区
    assert prof.smart_vwap < prof.all_vwap
    assert prof.smart_q < 1.0
    assert prof.smart_buy_ratio > 80.0
    assert prof.smart_phase == "ACCUMULATION"


def test_smart_money_distribution_simulation():
    """测试高位派发识别：高效大波动成交发生在高位阴线。"""
    bars = []
    base_time = dt.datetime(2026, 10, 20, 9, 35)

    # 构造 100 根 5 分钟线，总成交量 100,000 手，前 20% 为 20,000 手
    for i in range(100):
        t = base_time + dt.timedelta(minutes=5 * i)
        if i < 20:
            # 高价 20.0 元，1000 手/根，单笔快速杀跌 (-3%) -> S 极大，大阴线
            bars.append(SimpleNamespace(
                time=t,
                open=20.0,
                close=19.4,
                volume_lots=1000.0,
                amount=1950000.0,
            ))
        else:
            # 低价 15.0 元，1000 手/根，平稳微小波动 (+0.05%) -> S 值小
            bars.append(SimpleNamespace(
                time=t,
                open=15.0,
                close=15.008,
                volume_lots=1000.0,
                amount=1500400.0,
            ))

    analyzer = MicrostructureAnalyzer()
    prof = analyzer.analyze(bars, current_price=19.5)

    assert prof.smart_vwap > prof.all_vwap
    assert prof.smart_q > 1.0
    assert prof.smart_sell_ratio > 80.0
    assert prof.smart_phase == "DISTRIBUTION"


def test_main_force_lockup_stage_detection():
    """测试主升锁仓加速阶段识别：高连板龙头 + 底部主力成本低已大幅锁仓。"""
    bars = []
    base_time = dt.datetime(2026, 10, 20, 9, 35)

    for i in range(100):
        t = base_time + dt.timedelta(minutes=5 * i)
        if i < 20:
            # 早期低位 8.0 元启动，S 值高
            bars.append(SimpleNamespace(
                time=t,
                open=8.0,
                close=8.2,
                volume_lots=1000.0,
                amount=810000.0,
            ))
        else:
            # 当前 12.0 元加速，换手平稳
            bars.append(SimpleNamespace(
                time=t,
                open=12.0,
                close=12.01,
                volume_lots=1000.0,
                amount=1200500.0,
            ))

    analyzer = MicrostructureAnalyzer()
    ladder = {"board_level": 4, "is_leader": True, "broken_count": 0}
    prof = analyzer.analyze(bars, current_price=12.0, ladder_info=ladder)

    assert "主升锁仓" in prof.main_force_stage


def test_main_force_passive_fall_stage_detection():
    """测试主跌破位/无抵抗阴跌阶段识别：上方套牢盘重 + 破位且缺乏承接。"""
    bars = []
    base_time = dt.datetime(2026, 10, 20, 9, 35)

    for i in range(100):
        t = base_time + dt.timedelta(minutes=5 * i)
        bars.append(SimpleNamespace(
            time=t,
            open=100.0,
            close=99.8,
            volume_lots=500.0,
            amount=4990000.0,
        ))

    analyzer = MicrostructureAnalyzer()
    momentum = {
        "overhead_chip_pct": 75.0,
        "current_drawdown": -22.0,
        "is_bullish_ma": False,
    }
    prof = analyzer.analyze(bars, current_price=98.0, momentum=momentum)

    assert "无抵抗阴跌" in prof.main_force_stage

