"""Unit tests for MacroMarketEngine and Macro-Gate cross-validation matrix."""
from __future__ import annotations

import pandas as pd
import pytest

from core.macro_regime import MacroRegimeEngine, MacroRegimeResult
from core.judgment_chain import JudgmentChainRunner
from screener.ladder_analyzer import MarketSentimentOverview


def _build_mock_index_df(trend: str = "bear") -> pd.DataFrame:
    """构建用于测试的指数日线 DataFrame (倒序排列，第0行为最新交易日，共25根K线)。"""
    if trend == "bear":
        # 过去25天从 3900 阴跌至 3648
        closes = [3900.0 - i * 10.0 for i in range(25)]
    elif trend == "bull":
        # 过去25天从 3500 稳步主升至 3860
        closes = [3500.0 + i * 15.0 for i in range(25)]
    else:
        # 高位滞涨：先涨到 3890，最近几天高位放量滞涨
        closes = [3600.0 + i * 15.0 for i in range(20)] + [3890.0 - i * 3.0 for i in range(5)]

    # 倒序排列：第 0 行是最新的
    rev_closes = list(reversed(closes))
    rows = []
    for idx, c in enumerate(rev_closes):
        p_c = rev_closes[idx + 1] if idx + 1 < len(rev_closes) else c
        pct = (c - p_c) / p_c * 100.0
        amt = 7.0e11 if trend == "bear" else (1.4e12 if trend == "high_stall" else 1.1e12)
        rows.append({
            "ts_code": "000001.SH",
            "trade_date": f"202610{28-idx:02d}",
            "open": c * 1.002,
            "high": c * 1.005,
            "low": c * 0.995,
            "close": round(c, 2),
            "pct_chg": round(pct, 2),
            "vol": amt / 100.0,
            "amount": amt,
        })
    return pd.DataFrame(rows)


def test_divergence_speculative_cling_identification():
    """测试核心场景：大盘连跌破位阴跌 + 4900+只普跌，但单只个股顶到5板。
    系统必须精准识别为【大盘破位阴跌 + 局部妖股逆势抱团】，严禁错误定性为'高位分歧期'！
    """
    engine = MacroRegimeEngine()
    index_df = _build_mock_index_df(trend="bear")
    market_stat = {
        "up_count": 606,
        "down_count": 4922,
        "neutral_count": 42,
        "total_count": 5577,
        "total_amount": 1.47e12,
    }
    mock_ladder = type("MockLadder", (), {
        "space_board_level": 5,
        "space_board_tickers": ["上海九百(600838)"],
        "total_limit_up_count": 42,
        "total_limit_down_count": 23,
        "total_broken_count": 23,
        "broken_rate_pct": 35.4,
    })()

    res = engine.evaluate(
        trade_date="20261027",
        index_daily_df=index_df,
        market_stat_dict=market_stat,
        ladder_overview=mock_ladder,
    )

    assert res.resonance_type == "DIVERGENCE_SPECULATIVE_CLING"
    assert "大盘破位阴跌" in res.macro_regime_label
    assert "局部妖股逆势抱团" in res.macro_regime_label
    assert res.is_gate_open is False
    assert res.suggested_position_cap_pct <= 20
    assert any("补跌" in w or "避险" in w for w in res.risk_warnings)
    assert res.breadth_metrics.breadth_regime == "极端普跌冰点"
    assert res.index_metrics.trend_regime == "破位阴跌探底"
    assert res.composite_score < 40.0


def test_resonance_bull_identification():
    """测试多头共振场景：大盘多头排列、全市场多数个股上涨、连板良性。"""
    engine = MacroRegimeEngine()
    index_df = _build_mock_index_df(trend="bull")
    market_stat = {
        "up_count": 3820,
        "down_count": 1210,
        "neutral_count": 50,
        "total_count": 5080,
        "total_amount": 1.85e12,
    }
    mock_ladder = type("MockLadder", (), {
        "space_board_level": 5,
        "space_board_tickers": ["领涨龙头(000001)"],
        "total_limit_up_count": 68,
        "total_limit_down_count": 2,
        "total_broken_count": 8,
        "broken_rate_pct": 10.5,
    })()

    res = engine.evaluate(
        trade_date="20261027",
        index_daily_df=index_df,
        market_stat_dict=market_stat,
        ladder_overview=mock_ladder,
    )

    assert res.resonance_type == "RESONANCE_BULL"
    assert "共振主升" in res.macro_regime_label
    assert res.is_gate_open is True
    assert res.suggested_position_cap_pct >= 70
    assert res.composite_score >= 70.0


def test_resonance_high_distribution_identification():
    """测试真正的高位分歧场景：大盘高位，短线炸板率畸高且跌停潮涌现。"""
    engine = MacroRegimeEngine()
    index_df = _build_mock_index_df(trend="high_stall")
    market_stat = {
        "up_count": 1600,
        "down_count": 3500,
        "neutral_count": 40,
        "total_count": 5140,
        "total_amount": 2.1e12,
    }
    mock_ladder = type("MockLadder", (), {
        "space_board_level": 6,
        "space_board_tickers": ["高位妖股(600000)"],
        "total_limit_up_count": 35,
        "total_limit_down_count": 18,
        "total_broken_count": 25,
        "broken_rate_pct": 41.7,
    })()

    res = engine.evaluate(
        trade_date="20261027",
        index_daily_df=index_df,
        market_stat_dict=market_stat,
        ladder_overview=mock_ladder,
    )

    assert res.resonance_type == "RESONANCE_HIGH_DISTRIBUTION"
    assert "高位" in res.macro_regime_label
    assert "派发" in res.macro_regime_label or "分歧" in res.macro_regime_label
    assert res.is_gate_open is False
    assert res.suggested_position_cap_pct <= 30


def test_judgment_chain_integration_with_macro_regime():
    """验证 JudgmentChainRunner 在接入多维宏观大盘结果时的决断逻辑。"""
    engine = MacroRegimeEngine()
    index_df = _build_mock_index_df(trend="bear")
    market_stat = {
        "up_count": 606,
        "down_count": 4922,
        "neutral_count": 42,
        "total_count": 5577,
        "total_amount": 1.47e12,
    }
    mock_ladder = type("MockLadder", (), {
        "space_board_level": 5,
        "space_board_tickers": ["上海九百(600838)"],
        "total_limit_up_count": 42,
        "total_limit_down_count": 23,
        "total_broken_count": 23,
        "broken_rate_pct": 35.4,
    })()

    macro_res = engine.evaluate(
        trade_date="20261027",
        index_daily_df=index_df,
        market_stat_dict=market_stat,
        ladder_overview=mock_ladder,
    )

    overview = MarketSentimentOverview(
        trade_date="20261027",
        space_board_level=5,
        space_board_tickers=["上海九百(600838)"],
        ladder_counts={5: 1, 4: 2, 3: 3},
        promotion_rates={5: 0.33},
        total_limit_up_count=42,
        sentiment_phase=macro_res.macro_regime_label,
        strongest_themes=[],
        total_limit_down_count=23,
        total_broken_count=23,
        broken_rate_pct=35.4,
        macro_regime_result=macro_res,
    )

    runner = JudgmentChainRunner()
    card = runner.run(
        ticker="600838.SH",
        name="上海九百",
        trade_date="20261027",
        quote={"close": 12.50, "pct_chg": 9.98, "turnover_ratio": 15.0, "total_mv": 50e8, "circ_mv": 50e8},
        momentum={"is_bullish_ma": True, "volume_ratio": 1.8},
        flags=[],
        matched_youzi=[],
        trap_warnings=[],
        ladder_info={"board_level": 5, "is_leader": True, "theme_name": "商业百货"},
        sentiment_overview=overview,
    )

    # 验证第一支柱描述包含清晰大盘指数与广度信息
    p_gate = card.get("pillar_gate", "")
    assert "大盘基准" in p_gate
    assert "全市场广度" in p_gate
    assert "超短局部生态" in p_gate
    assert "上海九百" in p_gate
    assert "情绪闸门收紧" in p_gate

    # 验证最终决断严格锁仓防守，仓位受控
    assert card.get("decision_gear") in ("观察", "回避")
    assert card.get("position_cap") == 0.0
