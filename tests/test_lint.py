"""Unit tests for AST-Trader quality gating (Lint) rules."""
from __future__ import annotations

import pytest

from core.red_flags import LEVEL_FATAL, RedFlagItem
from lint.validator import LintValidator


def test_validator_blocks_buy_on_fatal_flag():
    """测试当存在致命红旗时，必须拦截 '买入' 决策。"""
    validator = LintValidator()
    fatal_flag = RedFlagItem(
        id="pledge_fatal",
        framework="Governance",
        level=LEVEL_FATAL,
        title="大股东质押率 85%",
        value=0.85,
        threshold="> 70%",
        evidence="质押暴雷",
        node="path",
    )

    card_invalid = {
        "decision_gear": "买入",
        "position_cap": 0.20,
        "invalidation_line": "跌破 5 日线止损",
    }

    passed, findings = validator.validate(card_invalid, [fatal_flag])
    assert not passed
    assert any("致命红旗未回避" in f for f in findings)


def test_validator_passes_when_gear_is_avoid():
    """测试当正确封顶为 '回避' 且仓位为 0 时，门控通过。"""
    validator = LintValidator()
    fatal_flag = RedFlagItem(
        id="pledge_fatal",
        framework="Governance",
        level=LEVEL_FATAL,
        title="大股东质押率 85%",
        value=0.85,
        threshold="> 70%",
        evidence="质争暴雷",
        node="path",
    )

    card_valid = {
        "decision_gear": "回避",
        "position_cap": 0.0,
        "invalidation_line": "禁止建仓",
    }

    passed, findings = validator.validate(card_valid, [fatal_flag])
    assert passed
    assert len(findings) == 0
