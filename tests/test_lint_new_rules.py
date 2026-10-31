"""本批补齐的门控规则回归：R1 / R2 / R3 / R4' / R5 / R14 / R15 / R16 / R18。

对应计划 P2。两条设计前提必须被测试锁死：
1. **新增规则默认 warn，不参与 passed** —— 否则一条误报就会把全市场清零仓位。
2. **config.LINT_RULE_SEVERITY 可无代码改动把规则升为 fail**。
"""
from __future__ import annotations

import pytest

import config
from core.red_flags import LEVEL_FATAL, RedFlagItem
from lint.validator import LEVEL_FAIL, LEVEL_WARN, Finding, LintValidator

FATAL_TITLE = "控股股东质押率 85%"


def _flag(level: str = LEVEL_FATAL, fid: str = "pledge_fatal", title: str = FATAL_TITLE) -> RedFlagItem:
    return RedFlagItem(
        id=fid, framework="Governance", level=level, title=title,
        value=0.85, threshold="> 70%", evidence="质押暴雷", node="path",
    )


def _flag_dict(fid: str = "pledge_fatal", level: str = LEVEL_FATAL, title: str = FATAL_TITLE) -> dict:
    return {"id": fid, "framework": "Governance", "level": level, "title": title,
            "value": 0.85, "threshold": "> 70%", "evidence": "质押暴雷", "node": "path"}


def _card(**over) -> dict:
    card = {
        "ticker": "002273",
        "name": "水晶光电",
        "trade_date": "20261028",
        "price": 12.0,
        "pct_chg": 9.9,
        "decision_gear": "回避",
        "position_cap": 0.0,
        "quality_verdict": "好",
        "state_verdict": "↑变好+证据确认",
        "odds_verdict": "合理",
        "path_verdict": "可承受",
        "invalidation_line": "跌破 10.5 元止损",
        "critical_wait": "等待重组问询函回复",
        "pillar_1_quality": "主营盈利良好",
        "pillar_2_state": "状态在变好",
        "pillar_3_odds": "估值合理",
        "pillar_4_path": f"左尾可控；{FATAL_TITLE} 已在正文中叙述",
        "sub_verdicts_quality": [
            {"question": f"问题{i}", "judgment": "✓", "evidence": f"凭据{i}"} for i in range(1, 6)
        ],
        "all_flags": [_flag_dict()],
        "top3_risks": [_flag_dict()],
        "anchor_range": {"low": {"value": 9.0}, "high": {"value": 15.0}},
        "pillar_5_decision": {
            "decision_gear": "回避",
            "decision_title": "【回避】",
            "position_cap": 0.0,
            "invalidation_line": "跌破 10.5 元止损",
            "triad_verdict": "[↑变好+证据确认 | 合理 | 可承受]",
        },
    }
    card.update(over)
    return card


# ---------------------------------------------------------------- 分级语义
def test_new_rules_default_to_warn_and_do_not_block():
    """最小卡缺字段必然触发 R1 warn，但 passed 必须仍为 True。"""
    passed, findings = LintValidator().validate(
        {"decision_gear": "回避", "position_cap": 0.0, "invalidation_line": "禁止建仓"}, [_flag()]
    )
    assert passed
    assert findings and all(f.startswith("[WARN]") for f in findings)


def test_rule_can_be_promoted_to_fail_via_config_without_code_change(monkeypatch):
    """把 R1 从 warn 升为 fail 后，同一张卡必须阻断。"""
    monkeypatch.setattr(config, "LINT_RULE_SEVERITY", {**config.LINT_RULE_SEVERITY, "R1": "fail"})
    passed, _ = LintValidator().validate(
        {"decision_gear": "回避", "position_cap": 0.0, "invalidation_line": "禁止建仓"}, [_flag()]
    )
    assert not passed


def test_finding_str_keeps_fail_text_verbatim():
    f = Finding(rule="R8", level=LEVEL_FAIL, message="[R8 越权发声] ...")
    assert str(f) == "[R8 越权发声] ..."
    w = Finding(rule="R1", level=LEVEL_WARN, message="[R1 契约校验] ...")
    assert str(w) == "[WARN] [R1 契约校验] ..."


def test_validate_findings_returns_typed_findings():
    out = LintValidator().validate_findings(_card(), [_flag()])
    assert all(isinstance(f, Finding) for f in out)


# ---------------------------------------------------------------- R1
def test_r1_flags_schema_violation():
    out = LintValidator().validate_findings(_card(ticker="A12345"), [_flag()])
    assert any(f.rule == "R1" and "ticker" in f.message for f in out)


def test_r1_silent_on_clean_card():
    out = LintValidator().validate_findings(_card(), [_flag()])
    assert not [f for f in out if f.rule == "R1"]


# ---------------------------------------------------------------- R2
def test_r2_top3_must_come_from_full_list():
    card = _card(top3_risks=[_flag_dict(fid="hand_picked", title="手工挑的风险"), ])
    out = LintValidator().validate_findings(card, [_flag()])
    assert any(f.rule == "R2" and "不在全量红旗清单" in f.message for f in out)


def test_r2_fatal_flag_must_be_narrated_in_pillars():
    """🔴 不在任何支柱正文出现 = 读者看不到，等于没排雷。"""
    card = _card(pillar_4_path="左尾可控，无重大风险")
    out = LintValidator().validate_findings(card, [_flag()])
    assert any(f.rule == "R2" and "未归家" in f.message for f in out)


def test_r2_clean_when_fatal_is_narrated():
    out = LintValidator().validate_findings(_card(), [_flag()])
    assert not [f for f in out if f.rule == "R2"]


# ---------------------------------------------------------------- R3
def test_r3_double_written_truth_must_match():
    card = _card()
    card["pillar_5_decision"]["decision_gear"] = "核心仓(大)"
    out = LintValidator().validate_findings(card, [_flag()])
    assert any(f.rule == "R3" and "行动档位" in f.message for f in out)


def test_r3_checks_invalidation_line_too():
    card = _card()
    card["pillar_5_decision"]["invalidation_line"] = "跌破 8 元止损"
    out = LintValidator().validate_findings(card, [_flag()])
    assert any(f.rule == "R3" and "证伪线" in f.message for f in out)


# ---------------------------------------------------------------- R4'
def test_r4_budget_is_warn_not_fail():
    card = _card(pillar_1_quality="盈" * 5000)
    out = LintValidator().validate_findings(card, [_flag()])
    hits = [f for f in out if f.rule == "R4"]
    assert hits and all(f.level == LEVEL_WARN for f in hits)


# ---------------------------------------------------------------- R5
def test_r5_price_above_anchor_high_cannot_be_cheap():
    card = _card(price=30.0, odds_verdict="便宜(有余地)")
    out = LintValidator().validate_findings(card, [_flag()])
    assert any(f.rule == "R5" and "方向矛盾" in f.message for f in out)


def test_r5_silent_when_price_inside_anchor():
    out = LintValidator().validate_findings(_card(price=12.0, odds_verdict="便宜(有余地)"), [_flag()])
    assert not [f for f in out if f.rule == "R5"]


# ---------------------------------------------------------------- R14
def test_r14_process_note_is_caught():
    out = LintValidator().validate_findings(_card(critical_wait="待定，等进一步核实"), [_flag()])
    assert any(f.rule == "R14" and "待定" in f.message for f in out)


def test_r14_silent_on_final_text():
    out = LintValidator().validate_findings(_card(), [_flag()])
    assert not [f for f in out if f.rule == "R14"]


# ---------------------------------------------------------------- R15
def test_r15_triad_must_match_verdicts():
    card = _card()
    card["pillar_5_decision"]["triad_verdict"] = "[横盘 | 合理 | 可承受]"
    out = LintValidator().validate_findings(card, [_flag()])
    assert any(f.rule == "R15" for f in out)


def test_r15_is_fail_by_default():
    """R15 是纯字符串相等，零误报风险，因此可以默认 fail。"""
    assert config.LINT_RULE_SEVERITY["R15"] == "fail"
    card = _card()
    card["pillar_5_decision"]["triad_verdict"] = "[横盘 | 合理 | 可承受]"
    passed, findings = LintValidator().validate(card, [_flag()])
    assert not passed
    assert any("R15" in f for f in findings)


# ---------------------------------------------------------------- R16
def test_r16_stale_price_range_in_odds_text():
    card = _card(pillar_3_odds="参考价区 3.5~4.2 元，明显偏低")
    out = LintValidator().validate_findings(card, [_flag()])
    assert any(f.rule == "R16" and "3.5~4.2" in f.message for f in out)


def test_r16_accepts_range_matching_anchor():
    card = _card(pillar_3_odds="参考价区 9.0~15.0 元")
    out = LintValidator().validate_findings(card, [_flag()])
    assert not [f for f in out if f.rule == "R16"]


def test_r16_does_not_scan_path_pillar():
    """④路径正文含止损/支撑价位属合理设计，不得误报。"""
    card = _card(pillar_4_path="跌破 3.5~4.2 元区间即离场")
    out = LintValidator().validate_findings(card, [_flag()])
    assert not [f for f in out if f.rule == "R16"]


# ---------------------------------------------------------------- R18
def test_r18_duplicate_flag_id():
    card = _card(all_flags=[_flag_dict(), _flag_dict()])
    out = LintValidator().validate_findings(card, [_flag()])
    assert any(f.rule == "R18" and "重复" in f.message for f in out)


def test_r18_illegal_level():
    card = _card(all_flags=[_flag_dict(level="🔵")])
    out = LintValidator().validate_findings(card, [_flag()])
    assert any(f.rule == "R18" and "级别非法" in f.message for f in out)


# ---------------------------------------------------------------- 未移植项
def test_rejected_upstream_rules_are_absent():
    """登记「刻意不移植」的决策，避免后人无意中照抄回来。

    上游 R6（外链引用）、R11（散文密度）、R17（已兑现倍数）在本项目
    形态下不适用或自认无阻断力，见 lint/validator.py 模块文档。
    """
    v = LintValidator()
    for attr in ("_check_r6_links", "_check_r11_prose_density", "_check_r17_realized_multiple"):
        assert not hasattr(v, attr), f"{attr} 属于刻意拒绝移植的规则"
