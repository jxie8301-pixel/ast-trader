"""Unit tests for AST-Trader screener tier components."""
from __future__ import annotations

import pytest

from screener.filter_liquidity import filter_liquidity


def test_filter_liquidity_excludes_st_and_low_amount():
    """测试 Tier 1 过滤剔除 ST 与非涨停低流动性标的。"""
    ladder_rows = [
        {"code": "000001", "full_code": "sz000001", "name": "平安银行", "board_level": 1, "seal_amount": 1e8},
        {"code": "000002", "full_code": "sz000002", "name": "*ST万科", "board_level": 1, "seal_amount": 5e8},
        {"code": "000003", "full_code": "sz000003", "name": "PT退市股", "board_level": 1, "seal_amount": 5e8},
    ]
    quotes_map = {
        "sz000001": {"close": 12.5, "pct_chg": 9.95, "amount": 6e8},
        "sz000002": {"close": 5.2, "pct_chg": 5.0, "amount": 6e8},
        "sz000003": {"close": 1.1, "pct_chg": -10.0, "amount": 1e7},
    }

    passed = filter_liquidity(ladder_rows, quotes_map)
    assert len(passed) == 1
    assert passed[0]["code"] == "000001"
