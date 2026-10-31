"""判断层回归：降级守卫、失败闭环、提示词渲染。

对应计划 P4。这些用例**全部离线**（`AI_ENABLED` 默认关闭），
是「AI 不得破坏确定性」这一约束的可执行证明。

最关键的三条断言：
· AI 关闭时 `enrich()` 返回 None，调用方拿到规则判定原值；
· AI 只能降级不能升级（`test_upgrade_is_blocked*`）；
· 无证据引用即弃权（`test_*no_evidence*`）。
"""
from __future__ import annotations

import config
import pytest

from core.ai_coprocessor import (
    apply_enrichment,
    apply_text,
    enrich,
    nominations_to_dicts,
)
from core.ai_coprocessor import cache, guard, prompts
from core.ai_coprocessor.provider import AIUnavailable, extract_json
from core.ai_enrichment import AIEnrichment, EvidenceRef, RedFlagNomination, MODULES


def _ai(judgment: str | None = "✗", *, evidence: int = 1, abstained: bool = False) -> AIEnrichment:
    return AIEnrichment(
        module="moat",
        judgment=judgment,
        evidence=tuple(
            EvidenceRef(source="announcement", quote=f"原文片段{i}", url="http://x/y.pdf", page=i)
            for i in range(1, evidence + 1)
        ),
        abstained=abstained,
        reason="超时" if abstained else "",
    )


# ---------------------------------------------------------------- 降级守卫
@pytest.mark.parametrize(
    "rule,ai_judgment,expected",
    [
        ("✓", "⚠️", "⚠️"),      # 允许降级
        ("✓", "✗", "✗"),        # 允许降级
        ("⚠️", "✗", "✗"),        # 允许降级
        ("✗", "⚠️", "✗"),        # ★ 禁止升级
        ("✗", "✓", "✗"),        # ★ 禁止升级
        ("⚠️", "✓", "⚠️"),        # ★ 禁止升级
        ("✓", "✓", "✓"),        # 同档不动
    ],
)
def test_apply_enrichment_direction(rule, ai_judgment, expected):
    assert apply_enrichment(rule, _ai(ai_judgment)) == expected


def test_upgrade_is_blocked_even_with_evidence():
    """哪怕证据充分，升级也必须被拦 —— 这是仓位安全线。"""
    ai = _ai("✓", evidence=3)
    assert apply_enrichment("✗", ai) == "✗"


def test_none_ai_returns_rule_verdict():
    assert apply_enrichment("✓", None) == "✓"


def test_abstained_ai_returns_rule_verdict():
    assert apply_enrichment("✓", _ai("✗", abstained=True)) == "✓"


def test_no_evidence_returns_rule_verdict():
    """★ 无引用即弃权 —— 防幻觉的核心闸门。"""
    assert apply_enrichment("✓", _ai("✗", evidence=0)) == "✓"


def test_unknown_judgment_symbol_returns_rule_verdict():
    """AI 输出非三态符号时无法比较序值，一律回退。"""
    assert apply_enrichment("✓", _ai("非常好")) == "✓"


def test_null_judgment_returns_rule_verdict():
    assert apply_enrichment("✓", _ai(None)) == "✓"


# ---------------------------------------------------------------- 文本型结论
def test_apply_text_replaces_when_usable():
    ai = _ai("等待上交所重组问询函回复披露")
    assert apply_text("等待行业下游资本开支拐点", ai) == "等待上交所重组问询函回复披露"


def test_apply_text_keeps_rule_when_abstained():
    ai = _ai("等待某某", abstained=True)
    assert apply_text("原规则文案", ai) == "原规则文案"


def test_apply_text_keeps_rule_when_no_evidence():
    assert apply_text("原规则文案", _ai("等待某某", evidence=0)) == "原规则文案"


def test_apply_text_caps_length():
    ai = _ai("等" * 500)
    out = apply_text("原文案", ai, max_len=50)
    assert len(out) <= 51 and out.endswith("…")


# ---------------------------------------------------------------- 解析闭环
def test_parse_payload_accepts_valid_output():
    payload = {
        "module": "moat",
        "judgment": "⚠️",
        "evidence": [{"source": "announcement", "quote": "客户认证周期 2 年", "page": 4}],
        "nominations": [{"id": "n1", "level": "🟠", "title": "客户集中", "evidence": "前五大 62%"}],
        "abstained": False,
    }
    e = guard.parse_payload(payload, "moat")
    assert not e.abstained and e.usable
    assert e.judgment == "⚠️" and len(e.evidence) == 1 and e.evidence[0].page == 4
    assert len(e.nominations) == 1


def test_parse_payload_abstains_without_evidence():
    payload = {"module": "moat", "judgment": "⚠️", "evidence": [], "abstained": False}
    e = guard.parse_payload(payload, "moat")
    assert e.abstained and not e.usable


def test_parse_payload_abstains_on_schema_violation():
    e = guard.parse_payload({"module": "unknown_module"}, "moat")
    assert e.abstained


def test_parse_payload_abstains_on_non_dict():
    e = guard.parse_payload("不是对象", "moat")
    assert e.abstained


def test_parse_payload_honors_explicit_abstain():
    e = guard.parse_payload({"module": "moat", "abstained": True, "reason": "公告 PDF 超时"}, "moat")
    assert e.abstained and e.reason == "公告 PDF 超时"


def test_parse_payload_drops_empty_quote():
    payload = {"module": "moat", "evidence": [{"source": "announcement", "quote": "  "}]}
    assert guard.parse_payload(payload, "moat").abstained


def test_parse_payload_drops_nomination_without_title():
    payload = {
        "module": "moat",
        "evidence": [{"source": "announcement", "quote": "x"}],
        "nominations": [{"id": "n1", "level": "🟠", "title": "", "evidence": "y"}],
    }
    assert guard.parse_payload(payload, "moat").nominations == ()


# ---------------------------------------------------------------- 提名单向阀
def test_nominations_are_risk_only():
    """★ AI 唯一的输出通道只能是风险，不存在『加信心』字段。"""
    ai = AIEnrichment(
        module="governance", judgment=None,
        evidence=(EvidenceRef(source="announcement", quote="非经营性资金占用"),),
        nominations=(RedFlagNomination(id="n1", level="🔴", title="资金占用",
                                       evidence="P12 载明", node="path"),),
    )
    out = nominations_to_dicts([ai])
    assert len(out) == 1 and out[0]["level"] == "🔴"
    assert all(k in out[0] for k in ("id", "level", "title", "evidence", "source"))


def test_nominations_to_dicts_skips_none():
    assert nominations_to_dicts([None, _ai()]) == []


# ---------------------------------------------------------------- 默认关闭
def test_ai_disabled_by_default():
    assert config.AI_ENABLED is False


def test_enrich_returns_none_when_disabled(monkeypatch):
    monkeypatch.setattr(config, "AI_ENABLED", False)
    assert enrich("moat", {"name": "X", "ticker": "000001"}) is None


def test_enrich_many_all_none_when_disabled(monkeypatch):
    monkeypatch.setattr(config, "AI_ENABLED", False)
    from core.ai_coprocessor import enrich_many
    out = enrich_many({}, tuple(MODULES))
    assert set(out) == set(MODULES) and all(v is None for v in out.values())


def test_enrich_rejects_unknown_module(monkeypatch):
    monkeypatch.setattr(config, "AI_ENABLED", True)
    with pytest.raises(ValueError):
        enrich("valuation", {})


# ---------------------------------------------------------------- 提示词
def test_all_module_prompts_render():
    ctx = {
        "name": "水晶光电", "ticker": "002273", "concepts": "AI, 消费电子",
        "business_composition": "光学元件 78%", "gross_margin": "31%",
        "net_margin": "8%", "roe": "11%", "evidence": "（无）",
        "announcements": "（无）", "state_verdict": "横盘", "gear": "观察",
        "seats": "（无）", "market_regime": "震荡",
    }
    for m in MODULES:
        text = prompts.render(m, **ctx)
        assert text and "（" in text
        assert "{evidence}" not in text


def test_render_unknown_module_raises():
    with pytest.raises(ValueError):
        prompts.render("valuation")


def test_system_prompt_states_three_boundaries():
    sp = prompts.system_prompt()
    for kw in ("数值权限", "升级权限", "无证据即弃权"):
        assert kw in sp


def test_prompt_files_are_on_disk():
    for m in MODULES:
        assert (prompts.PROMPT_DIR / f"{m}.md").is_file()


# ---------------------------------------------------------------- 缓存与解析
def test_cache_key_changes_with_prompt():
    a = cache.make_key("moat", "prompt A")
    b = cache.make_key("moat", "prompt B")
    c = cache.make_key("catalyst", "prompt A")
    assert a != b and a != c


def test_extract_json_tolerates_code_fence():
    raw = '```json\n{"module": "moat"}\n```'
    assert extract_json(raw) == {"module": "moat"}


def test_extract_json_rejects_garbage():
    with pytest.raises(AIUnavailable):
        extract_json("完全没有 JSON")


def test_cache_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path)
    key = cache.make_key("moat", "p")
    assert cache.get(key) is None
    cache.put(key, {"module": "moat", "abstained": True})
    assert cache.get(key) == {"module": "moat", "abstained": True}


def test_cache_get_survives_corruption(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path)
    key = cache.make_key("moat", "p")
    (tmp_path / f"{key}.json").write_text("{ 坏掉的 json", encoding="utf-8")
    assert cache.get(key) is None
