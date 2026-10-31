"""判断链五节点接线测试 —— 回答一个问题：**verdict 到底来自模型还是规则？**

本文件的存在意义：此前五节点基础设施（`prompts/node_*.md`、`run_nodes`、
`build_node_context`）全部建好但**没有任何调用方**，判断链仍是 if-else。
这组测试锁定「模型产出判定、规则退为 fallback」这条纪律，防止再次退化。
"""
from __future__ import annotations

import pytest

import config
from core.ai_coprocessor import context as ai_ctx
from core.ai_coprocessor import nodes as ai_nodes
from core.ai_enrichment import AIEnrichment, EvidenceRef
from core.judgment_chain import JudgmentChainRunner
from core.red_flags import RedFlagItem

#: 假模型给出的**悲观**判定 —— 与规则判定相反，用于证明「verdict 来自模型」
FAKE_VERDICTS = {
    "node_quality":  "不好",
    "node_state":    "↓变差",
    "node_odds":     "买完完美未来",
    "node_path":     "高尾险·不可承受",
    "node_decision": "回避",
}

#: **乐观**判定 —— 用于验证安全闸门不会被模型绕过（模型想放行也不行）
OPTIMISTIC_VERDICTS = {
    "node_quality":  "好",
    "node_state":    "↑变好+证据确认",
    "node_odds":     "便宜(有余地)",
    "node_path":     "可承受",
    "node_decision": "核心仓",
}

FAKE_ANALYSIS = {
    "derivation": "F=120亿, N=43亿",
    "critical_wait": "等 2026Q2 财报营收增速 >20%",
    "falsification": "毛利率跌破 25% 则退出",
    "cap_check": "无致命红旗，不封顶",
}


def _make_enrich(verdicts: dict[str, str]):
    """生成取代真实 AI 调用的假 enrich：返回固定判定 + 推导产物。"""

    def _fake_enrich(module, context, **kw):
        return AIEnrichment(
            module=module,
            verdict=verdicts[module],
            abstained=False,
            analysis=dict(FAKE_ANALYSIS),
            evidence=(EvidenceRef(source="metrics", quote="测试用证据"),),
        )

    return _fake_enrich


def _patch(monkeypatch, verdicts: dict[str, str]) -> JudgmentChainRunner:
    monkeypatch.setattr(config, "AI_ENABLED", True)
    monkeypatch.setattr(ai_ctx, "build_evidence", lambda *a, **k: ("", ""))
    monkeypatch.setattr(ai_nodes, "enrich", _make_enrich(verdicts))
    return JudgmentChainRunner()


@pytest.fixture
def ai_on(monkeypatch):
    """开启 AI、隔离网络（公告语料）、用**悲观**假模型取代真实调用。"""
    return _patch(monkeypatch, FAKE_VERDICTS)


@pytest.fixture
def ai_on_optimistic(monkeypatch):
    """模型给出**乐观**判定 —— 专用于验证安全闸门优先于模型。"""
    return _patch(monkeypatch, OPTIMISTIC_VERDICTS)


def _node_map(runner: JudgmentChainRunner) -> dict:
    return runner._ai_nodes(
        ticker="002850", name="科达利",
        derived_data={}, quote={"close": 162.98},
        microstructure={}, mainbz_list=[], flags=[],
        price=162.98, ma5=160.1, ma20=150.3,
    )


def _fatal_flag() -> RedFlagItem:
    return RedFlagItem(
        id="test-fatal", framework="测试框架", level="🔴", title="测试致命红旗",
        value=1, threshold=">0", evidence="测试用", node="quality",
    )


# ─────────────────────────── AI 关闭（默认路径）───────────────────────────

def test_ai_nodes_disabled_returns_empty(monkeypatch):
    """AI 关闭时必须返回空 dict —— 规则判定逐字不受影响。"""
    monkeypatch.setattr(config, "AI_ENABLED", False)
    out = JudgmentChainRunner()._ai_nodes(
        ticker="002850", name="科达利", derived_data={}, quote={},
        microstructure=None, mainbz_list=[], flags=[],
        price=100.0, ma5=99.0, ma20=98.0,
    )
    assert out == {}


def test_node_verdict_returns_none_when_disabled():
    """无节点结果时 `_node_verdict` 返回 None，规则判定原样生效。"""
    assert JudgmentChainRunner._node_verdict({}, "node_quality") is None
    assert JudgmentChainRunner._node_verdict(None, "node_quality") is None


# ─────────────────────────── 模型产出判定 ───────────────────────────

def test_ai_nodes_returns_all_five_verdicts(ai_on):
    nm = _node_map(ai_on)
    assert set(nm) == set(FAKE_VERDICTS)
    for m, v in FAKE_VERDICTS.items():
        assert JudgmentChainRunner._node_verdict(nm, m) == v


def test_quality_verdict_comes_from_model(ai_on):
    """★ 规则判定「部分好」被模型判定「不好」覆盖 —— verdict 来自模型。"""
    nm = _node_map(ai_on)
    _, verdict, _ = ai_on._build_pillar_1_quality(
        derived_data={}, flags=[], governance_info=None, concept_list=[],
        is_fatal=False, fatal_flags=[], data_health=None, nodes=nm,
    )
    assert verdict == "不好"


def test_state_verdict_and_critical_wait_come_from_model(ai_on):
    """★ ②的 verdict 与「该等什么」都由模型给（后者是全链唯一出处）。"""
    nm = _node_map(ai_on)
    _, verdict, critical_wait, _ = ai_on._build_pillar_2_state(
        derived_data={}, concept_list=[], ladder_info=None,
        mainbz_list=[], nodes=nm,
    )
    assert verdict == "↓变差"
    assert critical_wait == FAKE_ANALYSIS["critical_wait"]


def test_odds_verdict_comes_from_model(ai_on):
    """★ ③由模型产出判定（含估值推导），规则的双锚比较退为 fallback。"""
    nm = _node_map(ai_on)
    _, verdict, *_ = ai_on._build_pillar_3_odds(
        price=100.0, total_shares_yi=1.0, pe_val=20.0, total_mv=100.0,
        derived_data={}, is_tech=False, mainbz_list=[], nodes=nm,
    )
    assert verdict == "买完完美未来"


def test_path_verdict_comes_from_model(ai_on):
    """★ 规则判定「可承受」被模型判定「高尾险」覆盖。"""
    nm = _node_map(ai_on)
    out = ai_on._build_pillar_4_path(
        price=100.0, overhead_chips=30.0, sotp_ps=90.0,
        microstructure={}, is_fatal=False, trade_date=None, nodes=nm,
    )
    assert out[1] == "高尾险·不可承受"


# ─────────────────────────── 安全闸门优先于模型 ───────────────────────────

def test_fatal_blocks_quality_upgrade(ai_on_optimistic):
    """★ 致命红旗时模型说「好」也不行 —— 规则的安全结论不可被推翻。"""
    nm = _node_map(ai_on_optimistic)
    _, verdict, _ = ai_on_optimistic._build_pillar_1_quality(
        derived_data={}, flags=[], governance_info=None, concept_list=[],
        is_fatal=True, fatal_flags=[_fatal_flag()], data_health=None, nodes=nm,
    )
    assert verdict == "不好"


def test_fatal_blocks_path_upgrade(ai_on_optimistic):
    """★ 致命红旗时模型说「可承受」也不行 —— ④的规则结论保留。"""
    nm = _node_map(ai_on_optimistic)
    out = ai_on_optimistic._build_pillar_4_path(
        price=100.0, overhead_chips=30.0, sotp_ps=90.0,
        microstructure={}, is_fatal=True, trade_date=None, nodes=nm,
    )
    assert out[1] == "高尾险·不可承受"


# ─────────────────────────── 推导产物可审计 ───────────────────────────

def test_node_analysis_carries_derivation(ai_on):
    """模型推导过程必须可被汇总上报告 —— 这是「真在分析」的证据。"""
    nm = _node_map(ai_on)
    analysis = JudgmentChainRunner._node_analysis(nm)
    assert set(analysis) == set(FAKE_VERDICTS)
    assert analysis["node_odds"]["derivation"] == FAKE_ANALYSIS["derivation"]
    assert analysis["node_path"]["falsification"] == FAKE_ANALYSIS["falsification"]


def test_node_analysis_empty_when_no_nodes():
    assert JudgmentChainRunner._node_analysis(None) == {}
    assert JudgmentChainRunner._node_analysis({}) == {}


def test_report_shows_model_derivation(capsys):
    """★ 报告必须能看到模型推导 —— 否则「大模型判定」是无法验证的空头承诺。

    支柱①的判定行写着「推导过程见报告 🧠 AI 分析 段」，
    若报告里没有这一段，那句话就是假的。
    """
    from presentation.terminal_view import _print_ai_analysis

    _print_ai_analysis({})                       # AI 关闭时整段不出现，且不抛
    assert capsys.readouterr().out == ""

    _print_ai_analysis({"ai_analysis": {
        "node_odds": {"derivation": "F=120亿, N=43亿",
                      "sub_verdicts": [{"question": "贵吗", "judgment": "✗"}]},
    }})
    out = capsys.readouterr().out
    assert "推导过程" in out
    assert "F=120亿" in out
    assert "③ 赔率" in out
    assert "贵吗" in out


def test_fmt_block_survives_numpy_containers():
    """★ 回归：真实 microstructure 含 ndarray/Series，判空不得抛 ValueError。

    端到端 `analyze 002850` 时曾在此崩溃 —— `_fmt_block` 用
    `v not in (None, "", [], {})` 会触发 numpy 元素级比较。
    """
    import numpy as np

    from core.ai_coprocessor.context import _fmt_block

    out = _fmt_block({"empty": np.array([]), "arr": np.array([1.0, 2.0]),
                      "num": 1.5, "blank": "", "none": None})
    assert "empty" not in out      # 空数组应被过滤
    assert "arr" in out
    assert "num" in out
    assert "blank" not in out
    assert "none" not in out
