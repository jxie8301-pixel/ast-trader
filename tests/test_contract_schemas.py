"""契约层回归：决断卡与 AI 输出的 JSON Schema 校验。

对应计划 P1。核心是让「AI 结论可被机检」这件事**先于 AI 本身落地** ——
没有契约就没有门控，没有门控就不能放 AI 进决策链。
"""
import copy

import pytest

from core.schema_validator import (
    SchemaNotFoundError,
    available_schemas,
    validate,
    validate_or_raise,
)


def _valid_card() -> dict:
    """合规决断卡最小样本（字段取值域与 lint/validator.py VERDICT_DOMAINS 一致）。"""
    return {
        "ticker": "002273",
        "name": "水晶光电",
        "trade_date": "20261028",
        "price": 12.0,
        "pct_chg": 9.9,
        "decision_gear": "期权仓(小)",
        "position_cap": 0.20,
        "quality_verdict": "好",
        "state_verdict": "↑变好+证据确认",
        "odds_verdict": "合理",
        "path_verdict": "可承受",
        "invalidation_line": "跌破 10.5 元止损",
        "critical_wait": "等待重组问询函回复",
        "sub_verdicts_quality": [
            {"question": "生意模式赚钱吗", "judgment": "✓", "evidence": "毛利率 31%"},
            {"question": "赚钱质量真吗", "judgment": "⚠️", "evidence": "OCF/净利 0.72"},
            {"question": "护城河存在吗", "judgment": "✓", "evidence": "客户认证周期 2 年"},
            {"question": "管理层可信吗", "judgment": "✓", "evidence": "无减持记录"},
            {"question": "财务底子稳吗", "judgment": "✓", "evidence": "资产负债率 38%"},
        ],
        "pillar_5_decision": {
            "decision_gear": "期权仓(小)",
            "decision_title": "【进攻】",
            "position_cap": 0.20,
            "invalidation_line": "跌破 10.5 元止损",
        },
    }


def _valid_enrichment() -> dict:
    return {
        "module": "moat",
        "judgment": "护城河主要来自客户认证周期，非概念标签",
        "confidence": 0.72,
        "evidence": [
            {
                "source": "announcement",
                "url": "http://data.tdx.com.cn/tdxfiles/pdf_abg_sh/202609/605336_20260916_GG5S.pdf",
                "page": 4,
                "quote": "公司前五大客户销售占比 62.31%，均为长期合作客户",
            }
        ],
        "nominations": [
            {
                "id": "nomination-moat-a1b2c3",
                "level": "🟠",
                "title": "客户集中度高",
                "evidence": "前五大客户占比 62.31%",
                "source": "nomination",
                "node": "quality",
            }
        ],
        "abstained": False,
    }


# ---------------------------------------------------------------- 基础
def test_available_schemas_lists_all_three():
    names = available_schemas()
    assert "common.schema.json" in names
    assert "decision_card.schema.json" in names
    assert "ai_enrichment.schema.json" in names


def test_valid_card_passes():
    assert validate(_valid_card(), "decision_card") == []


def test_unknown_schema_raises():
    with pytest.raises(SchemaNotFoundError):
        validate({}, "nonexistent")


# ---------------------------------------------------------------- 决断卡
@pytest.mark.parametrize(
    "mutate,expect_fragment",
    [
        (lambda c: c.pop("quality_verdict"), "required"),
        (lambda c: c.update(price=0), "price"),
        (lambda c: c.update(price=-1.0), "price"),
        (lambda c: c.update(quality_verdict="非常好"), "quality_verdict"),
        (lambda c: c.update(state_verdict="变好"), "state_verdict"),
        (lambda c: c.update(ticker="A12345"), "ticker"),
        (lambda c: c.update(sub_verdicts_quality=c["sub_verdicts_quality"][:3]), "too short"),
    ],
)
def test_card_violations_are_caught(mutate, expect_fragment):
    card = _valid_card()
    mutate(card)
    errors = validate(card, "decision_card")
    assert errors, "违规样本必须被检出"
    assert any(expect_fragment in e for e in errors), errors


def test_sub_verdict_requires_non_empty_evidence():
    """没有证据的判定不允许进卡 —— 这是『无引用即弃权』在决断卡侧的体现。"""
    card = _valid_card()
    card["sub_verdicts_quality"][0]["evidence"] = ""
    assert validate(card, "decision_card")


def test_sub_verdict_judgment_domain():
    card = _valid_card()
    card["sub_verdicts_quality"][0]["judgment"] = "良好"
    assert any("judgment" in e for e in validate(card, "decision_card"))


def test_validate_or_raise_raises_with_all_errors():
    card = _valid_card()
    card.pop("quality_verdict")
    card["price"] = -1.0
    with pytest.raises(Exception) as exc:
        validate_or_raise(card, "decision_card")
    assert "契约校验未通过" in str(exc.value)


def test_valid_card_is_not_mutated():
    card = _valid_card()
    snapshot = copy.deepcopy(card)
    validate(card, "decision_card")
    assert card == snapshot


# ---------------------------------------------------------------- AI 输出
def test_valid_enrichment_passes():
    assert validate(_valid_enrichment(), "ai_enrichment") == []


def test_enrichment_without_evidence_is_rejected():
    """★ 未弃权却拿不出证据 = 幻觉风险，必须被契约拦下。"""
    payload = _valid_enrichment()
    payload["evidence"] = []
    errors = validate(payload, "ai_enrichment")
    assert errors and any("evidence" in e for e in errors), errors


def test_abstained_without_reason_is_rejected():
    """★ 弃权必须写明原因，禁止静默失败。"""
    payload = _valid_enrichment()
    payload["abstained"] = True
    payload.pop("reason", None)
    errors = validate(payload, "ai_enrichment")
    assert errors and any("reason" in e for e in errors), errors


def test_abstained_with_reason_needs_no_evidence():
    payload = {
        "module": "catalyst",
        "judgment": None,
        "abstained": True,
        "reason": "公告 PDF 下载超时",
        "evidence": [],
        "nominations": [],
    }
    assert validate(payload, "ai_enrichment") == []


def test_enrichment_rejects_unknown_fields():
    """AI 最容易自作主张加字段；契约必须收紧到 additionalProperties=false。"""
    payload = _valid_enrichment()
    payload["position_cap"] = 0.35          # 严禁 AI 输出数值
    assert validate(payload, "ai_enrichment")


def test_enrichment_module_domain():
    payload = _valid_enrichment()
    payload["module"] = "valuation"
    assert any("module" in e for e in validate(payload, "ai_enrichment"))


def test_evidence_quote_must_be_non_empty():
    payload = _valid_enrichment()
    payload["evidence"][0]["quote"] = ""
    assert validate(payload, "ai_enrichment")


def test_cross_file_ref_resolves():
    """跨文件 $ref 必须能解析到 common.schema.json —— 否则整套契约形同虚设。"""
    payload = _valid_enrichment()
    payload["nominations"][0]["level"] = "🔵"      # 非法定级别
    errors = validate(payload, "ai_enrichment")
    assert errors, "跨文件 $ref 未生效（common.schema.json 的枚举没被应用）"
