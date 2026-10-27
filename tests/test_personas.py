"""Unit tests for 24 Youzi Personas matching UZI-Skill implementation."""
from __future__ import annotations

import pytest

from core.youzi_personas import evaluate_youzi_personas, extract_tape_features


def test_zhang_mz_capacity_trend_persona():
    """测试章盟主容量趋势战法在放量主升龙头上命中。"""
    quote = {
        "close": 25.0,
        "pct_chg": 5.5,
        "amount": 15e8,  # 15亿大成交 (命中 capacity)
        "high": 25.0,
        "open": 23.5,
        "pre_close": 23.7,
        "turnover_ratio": 8.0,
    }
    momentum = {
        "volume_ratio": 2.2,
        "is_bullish_ma": True,  # 命中 trend_up
    }
    theme_info = {
        "concepts": ["AI", "算力", "光模块"],
        "leader_rank": 1,  # 命中 leader
        "breadth_pct": 70.0,  # 命中 theme_hot
    }

    features = extract_tape_features(
        quote=quote,
        momentum=momentum,
        market_cap=200e8,
        theme_info=theme_info,
        hard_event=True,
    )

    matched = evaluate_youzi_personas(features)
    assert len(matched) > 0
    names = [p["youzi_name"] for p in matched]
    assert "章盟主" in names
    assert any("容量趋势" in p["style"] for p in matched)


def test_youzi_veto_rule_triggers():
    """测试当流动性不足 (< 2亿) 时，一票否决容量型游资。"""
    quote = {
        "close": 10.0,
        "pct_chg": 5.0,
        "amount": 1.2e8,  # 仅 1.2 亿成交额 (触发 illiquid 一票否决)
        "turnover_ratio": 2.0,
    }
    momentum = {"volume_ratio": 1.0, "is_bullish_ma": True}
    theme_info = {"concepts": ["消费"], "leader_rank": 1, "breadth_pct": 60.0}

    features = extract_tape_features(
        quote=quote,
        momentum=momentum,
        market_cap=50e8,
        theme_info=theme_info,
    )

    matched = evaluate_youzi_personas(features)
    names = [p["youzi_name"] for p in matched]
    assert "章盟主" not in names  # 必须被 illiquid 一票否决
    assert "方新侠" not in names  # 必须被 illiquid 一票否决
