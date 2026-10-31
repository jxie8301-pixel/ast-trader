"""Unit tests for AST-Trader quality gating (Lint) rules."""
from __future__ import annotations

import pytest

import config
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
    # 本批补齐的新规则默认 **warn 级**：不参与 passed，但会出现在 findings 里。
    # 该用例是最小卡（无 ticker / 五支柱判定等字段），必然触发 R1 契约 warn。
    # 故只断言「无 fail 级发现」，而不是「零发现」。
    assert not [f for f in findings if not f.startswith("[WARN]")]


# =============================================================================
# 本批新增：R10 / R11 / R12
# =============================================================================

BASE_OK_CARD = {
    "decision_gear": "回避",
    "position_cap": 0.0,
    "invalidation_line": "禁止建仓",
    "price": 20.0,
    "quality_verdict": "部分好",
    "state_verdict": "横盘",
    "odds_verdict": "未核验(净利润为负)",
    "path_verdict": "可承受",
    "pillar_1_quality": "质地一般，盈利质量偏弱。",
    "pillar_2_state": "状态横盘，未见明确催化。",
    "pillar_5_decision": {"position_cap": 0.0},
}


def _validate(card: dict) -> tuple[bool, list[str]]:
    return LintValidator().validate(card, [])


def test_r10_rejects_out_of_domain_verdict():
    """R10 正向：判定结论不在合法取值域内时必须拦截。"""
    passed, findings = _validate({**BASE_OK_CARD, "quality_verdict": "非常好"})
    assert not passed
    assert any("R10" in f and "quality_verdict" in f for f in findings)


def test_r10_accepts_all_documented_domains():
    """R10 反向：文档中全部合法取值（含未核验态）均不得被误判。"""
    from lint.validator import LintValidator as LV

    for key, domain in LV.VERDICT_DOMAINS.items():
        for value in domain:
            passed, findings = _validate({**BASE_OK_CARD, key: value})
            assert passed, f"{key}={value} 被误报: {findings}"


def test_r10_ignores_missing_verdict():
    """R10 边界：缺失判定由字段完整性规则处理，R10 不做'缺失即违规'判定。"""
    card = {k: v for k, v in BASE_OK_CARD.items() if k != "quality_verdict"}
    passed, findings = _validate(card)
    assert passed
    assert not any("R10" in f for f in findings)


def test_r11_blocks_position_leak_in_early_pillars():
    """R11 正向：❶质地/❷状态 正文出现仓位表述必须拦截。"""
    passed, findings = _validate({**BASE_OK_CARD, "pillar_1_quality": "质地优秀，建议建仓 20%"})
    assert not passed
    assert any("R11" in f and "①质地正文" in f for f in findings)


def test_r11_does_not_check_path_pillar():
    """R11 反向边界：❹路径正文含止损价位与支撑位属合理，不得误报。"""
    passed, findings = _validate({**BASE_OK_CARD, "pillar_4_path": "跌破支撑 18.5 元止损，仓位清零"})
    assert passed
    assert not any("R11" in f for f in findings)


def test_r12_detects_position_cap_double_write_mismatch():
    """R12 正向：顶层仓位与 ⑤决策节点仓位双写不一致时必须拦截。"""
    card = {**BASE_OK_CARD, "position_cap": 0.20, "pillar_5_decision": {"position_cap": 0.10}}
    passed, findings = _validate(card)
    assert not passed
    assert any("R12" in f and "双写不一致" in f for f in findings)


def test_r12_detects_position_cap_above_extreme_tier():
    """R12 正向：单票仓位超过 config 极端档上限时必须拦截（守护 E-1 双档口径）。"""
    passed, findings = _validate({**BASE_OK_CARD, "position_cap": 0.35})
    assert not passed
    assert any("R12" in f and "仓位越界" in f for f in findings)


def test_r12_accepts_extreme_tier_cap():
    """R12 反向：极端档上限本身属于合法值，不得误报（双写需同步一致）。"""
    cap = config.MAX_SINGLE_POSITION_EXTREME
    card = {**BASE_OK_CARD, "position_cap": cap, "pillar_5_decision": {"position_cap": cap}}
    passed, findings = _validate(card)
    assert passed
    assert not any("R12" in f for f in findings)


def test_r12_detects_inverted_anchor_range():
    """R12 正向：SOTP 低端高于 DCF 高端（区间倒置）时必须拦截。"""
    card = {**BASE_OK_CARD, "anchor_range": {"low": {"value": 30.0}, "high": {"value": 20.0}}}
    passed, findings = _validate(card)
    assert not passed
    assert any("R12" in f and "区间倒置" in f for f in findings)


def test_r12_detects_non_positive_price():
    """R12 正向：现价为 0 或负数时必须拦截。"""
    passed, findings = _validate({**BASE_OK_CARD, "price": 0.0})
    assert not passed
    assert any("R12" in f and "现价非正" in f for f in findings)
