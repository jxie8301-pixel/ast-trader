"""Unit tests for HTML rendering and screener pipeline components."""
from __future__ import annotations

import os
import tempfile
import pytest

from presentation.html_renderer import render_decision_card_html


def test_html_rendering():
    """测试独立离线 HTML 研报生成及关键要素完整性。"""
    sample_card = {
        "ticker": "002273.SZ",
        "name": "水晶光电",
        "trade_date": "20261027",
        "price": 23.50,
        "pct_chg": 3.45,
        "quality_verdict": "✓ 财务底子稳健，未见显著造假与异常应计异象",
        "state_verdict": "放量主升中 (量比 2.1，均线多头排列)",
        "odds_verdict": "赔率尚可 (下方强支撑位 21.80 元)",
        "path_verdict": "筹码路径相对健康 (知名席位: 章盟主)",
        "decision_gear": "买入",
        "position_cap": 0.20,
        "invalidation_line": "开盘跌破 MA5 (22.80 元) 或日内跌破分时均线 -3% 坚决止损",
        "top3_risks": [
            {
                "framework": "Beneish M-Score",
                "level": "🟡",
                "title": "M-Score 得分 -2.15: 处于造假安全区",
                "evidence": "应计收益与营收增速相符",
                "threshold": "> -1.78",
            }
        ],
        "matched_youzi": [
            {
                "youzi_name": "章盟主",
                "branch_name": "国泰君安证券股份有限公司上海江苏路证券营业部",
                "level": "一线顶级游资",
                "styles": ["波段主升", "大资金合力"],
            }
        ],
        "trap_warnings": [],
    }

    from core.capital_matrix import CapitalMatrixRadar
    from core.execution_playbook import PlaybookBuilder

    radar = CapitalMatrixRadar()
    sample_card["capital_matrix"] = radar.evaluate(
        quote={"close": 23.50, "pe": 20.0, "pb": 2.5, "turnover_ratio": 5.0, "total_mv": 120.0},
        momentum={"is_bullish_ma": True, "volume_ratio": 1.8, "ma5_bias": 1.2},
        flags=[],
        trap_warnings=[],
        matched_personas=["章盟主"],
        concepts=["消费电子"],
    )

    builder = PlaybookBuilder()
    sample_card["execution_playbook"] = builder.build(
        quote={"close": 23.50, "pre_close": 22.80},
        momentum={"support_level": 22.50, "resistance_level": 25.0},
        matched_personas=["章盟主"],
        action="BUY",
        ladder_info=None,
        fatal_flag=False,
    )

    with tempfile.TemporaryDirectory() as tmpdir:
        out_file = os.path.join(tmpdir, "test_report.html")
        saved_path = render_decision_card_html(sample_card, output_path=out_file)
        
        assert os.path.exists(saved_path)
        with open(saved_path, "r", encoding="utf-8") as f:
            content = f.read()

        # 验证核心标签与要素
        assert "水晶光电" in content
        assert "002273.SZ" in content
        assert "章盟主" in content
        assert "五节点因果决断卡" in content
        assert "四维资金博弈雷达" in content
        assert "实盘战术执行手册" in content
        assert "买入" in content
        assert "20%" in content
