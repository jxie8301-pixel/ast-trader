"""AI 判断层接线回归：governance / theme_purity / tactic 三处接入点。

对应 A-1 收尾。核心要证明三件事：
1. **AI 关闭时行为逐字不变**（`scenario_note` 恒空、无提名红旗）。
2. **AI 只能加风险**：三处接入都只追加红旗，不改写既有判定。
3. **级别封顶生效**：AI 给 🔴 也会被压到 🟠，永远无法触发致命封顶。
"""
from __future__ import annotations

import pandas as pd
import pytest

import config
from core.ai_coprocessor import context as ai_context
from core.ai_coprocessor.guard import nominations_to_flags
from core.audit_engine import AuditEngine
from core.ai_enrichment import AIEnrichment, EvidenceRef, RedFlagNomination
from core.execution_playbook import ExecutionPlaybook, PlaybookBuilder


def _ai(module: str, *, level: str = "🔴", title: str = "资金占用", node: str = "path") -> AIEnrichment:
    return AIEnrichment(
        module=module,
        judgment=None,
        evidence=(EvidenceRef(source="announcement", quote="P12 载明非经营性资金占用"),),
        nominations=(RedFlagNomination(id=f"n-{module}", level=level, title=title,
                                       evidence="P12", node=node),),
    )


# ---------------------------------------------------------------- 提名单向阀
def test_nomination_level_is_capped_even_when_built_directly():
    """绕过 parse_payload 直接构造 AIEnrichment，🔴 也必须被压到 🟠。"""
    flags = nominations_to_flags({"governance": _ai("governance", level="🔴")})
    assert len(flags) == 1
    assert flags[0].level == config.AI_MAX_NOMINATION_LEVEL == "🟠"


def test_nomination_below_cap_is_untouched():
    flags = nominations_to_flags({"governance": _ai("governance", level="🟡")})
    assert flags[0].level == "🟡"


def test_nomination_metadata_is_complete():
    flags = nominations_to_flags({"theme_purity": _ai("theme_purity", node="state")})
    f = flags[0]
    assert f.framework == "AI 语义提名" and f.node == "state"
    assert f.title and f.evidence and f.id
    assert f.value is None


def test_illegal_node_falls_back_to_quality():
    flags = nominations_to_flags({"t": _ai("t", node="不可能的节点")})
    assert flags[0].node == "quality"


def test_empty_ai_map_yields_no_flags():
    assert nominations_to_flags({}) == []
    assert nominations_to_flags({"governance": None}) == []


# ---------------------------------------------------------------- governance → AuditEngine
def _empty_frames() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()


def test_run_audit_without_ai_has_no_nominations():
    bs, cf, inc = _empty_frames()
    flags = AuditEngine().run_audit(balance_df=bs, cashflow_df=cf, income_df=inc)
    assert not [f for f in flags if f.framework == "AI 语义提名"]


def test_run_audit_merges_governance_nominations():
    bs, cf, inc = _empty_frames()
    flags = AuditEngine().run_audit(
        balance_df=bs, cashflow_df=cf, income_df=inc,
        ai={"governance": _ai("governance")},
    )
    noms = [f for f in flags if f.framework == "AI 语义提名"]
    assert len(noms) == 1 and noms[0].title == "资金占用"
    assert noms[0].level == "🟠"


def test_run_audit_nominations_never_become_fatal():
    """★ 最严重后果仍由脚本红旗掌握 —— AI 不得直接触发致命封顶。"""
    bs, cf, inc = _empty_frames()
    flags = AuditEngine().run_audit(
        balance_df=bs, cashflow_df=cf, income_df=inc,
        ai={"governance": _ai("governance", level="🔴")},
    )
    assert not [f for f in flags if f.framework == "AI 语义提名" and f.level == "🔴"]


# ---------------------------------------------------------------- tactic → Playbook
def _quote() -> dict:
    return {"close": 10.0, "pre_close": 9.5, "open": 9.6, "high": 10.5,
            "low": 9.4, "volume": 1e7, "amount": 1e8}


def _momentum() -> dict:
    return {"support_level": 9.4, "resistance_level": 10.8, "vol_ratio": 2.1}


def test_playbook_scenario_note_empty_by_default():
    """AI 关闭时 scenario_note 恒为空串 —— 输出与历史逐字一致。"""
    pb = PlaybookBuilder().build(quote=_quote(), momentum=_momentum(),
                                 matched_personas=[], action="BUY")
    assert pb.scenario_note == ""


def test_playbook_scenario_note_filled_when_ai_usable():
    pb = PlaybookBuilder().build(
        quote=_quote(), momentum=_momentum(), matched_personas=[], action="BUY",
        ai={"tactic": AIEnrichment(module="tactic", judgment="若竞价高开且量比>2则…",
                                   evidence=(EvidenceRef(source="metrics", quote="量比 2.1"),))},
    )
    assert pb.scenario_note == "若竞价高开且量比>2则…"


def test_playbook_ai_never_touches_prices_or_tactic():
    """★ AI 无数值权限：entry_tactic / 价格 / 仓位 必须保持原样。"""
    plain = PlaybookBuilder().build(quote=_quote(), momentum=_momentum(),
                                    matched_personas=[], action="BUY")
    with_ai = PlaybookBuilder().build(
        quote=_quote(), momentum=_momentum(), matched_personas=[], action="BUY",
        ai={"tactic": AIEnrichment(module="tactic", judgment="AI 的情景描述",
                                   evidence=(EvidenceRef(source="metrics", quote="x"),))},
    )
    assert with_ai.entry_tactic == plain.entry_tactic
    assert with_ai.entry_price_range == plain.entry_price_range
    assert with_ai.take_profit_target == plain.take_profit_target
    assert with_ai.stop_loss_line == plain.stop_loss_line
    assert with_ai.max_position_pct == plain.max_position_pct
    assert with_ai.scenario_note == "AI 的情景描述"


def test_playbook_abstained_ai_leaves_note_empty():
    ai = AIEnrichment(module="tactic", abstained=True, reason="无证据")
    pb = PlaybookBuilder().build(quote=_quote(), momentum=_momentum(),
                                 matched_personas=[], action="BUY", ai={"tactic": ai})
    assert pb.scenario_note == ""


def test_execution_playbook_scenario_note_defaults_empty():
    assert ExecutionPlaybook(
        action="WAIT", action_label="l", entry_tactic="t", entry_price_range="r",
        base_position_pct=0, add_position_pct=0, max_position_pct=0,
        take_profit_target="tp", stop_loss_line="sl", invalidation_rule="ir",
    ).scenario_note == ""


# ---------------------------------------------------------------- 共用上下文
@pytest.fixture
def offline_evidence(monkeypatch):
    """切断公告语料网络依赖 —— 本节只测上下文组装，不测取数。"""
    monkeypatch.setattr(
        ai_context, "build_evidence",
        lambda *a, **k: ("[P4] 年报：客户认证周期 24 个月", "- 2026-03-01 关于问询函回复的公告"),
    )


def test_build_context_fills_all_prompt_slots(offline_evidence):
    ctx = ai_context.build_context(
        "600519.SH", "贵州茅台",
        concepts=["白酒", "消费"],
        mainbz_list=[{"name": "茅台酒", "revenue_ratio": "86%"}],
        derived_data={"profitability": {"gross_margin": "91%", "net_margin": "52%", "roe": "34%"}},
    )
    for slot in ("name", "ticker", "concepts", "business_composition",
                 "gross_margin", "net_margin", "roe", "evidence", "announcements",
                 "gear", "seats", "market_regime", "state_verdict"):
        assert slot in ctx and ctx[slot]
    assert "茅台酒 86%" in ctx["business_composition"]
    assert ctx["concepts"] == "白酒、消费"


def test_build_context_extra_overrides_defaults(offline_evidence):
    ctx = ai_context.build_context("000001", "X", gear="核心仓", market_regime="冰点")
    assert ctx["gear"] == "核心仓" and ctx["market_regime"] == "冰点"


def test_build_context_missing_values_are_placeholders(offline_evidence):
    ctx = ai_context.build_context("000001", "")
    assert ctx["name"] == "（未提供）"
    assert ctx["concepts"] == "（未提供）"
    assert ctx["business_composition"] == "（未提供）"


def test_build_context_keeps_provided_evidence(offline_evidence):
    ctx = ai_context.build_context("000001", "X")
    assert "客户认证周期 24 个月" in ctx["evidence"]
    assert "问询函回复" in ctx["announcements"]


def test_build_evidence_returns_empty_string_on_failure(monkeypatch):
    """语料取不到就给空证据，让 AI 依「无证据即弃权」自行弃权，绝不伪造语料。"""
    import data.announcement_corpus as corpus_mod

    def _boom(*a, **k):
        raise RuntimeError("网络不可用")

    monkeypatch.setattr(corpus_mod, "build_corpus", _boom)
    evidence, anns = ai_context.build_evidence("000001")
    assert evidence == "" and anns == ""
