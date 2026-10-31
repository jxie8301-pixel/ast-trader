"""白话层与展示层渲染的离线回归。

对应诉求：报告术语密度过高、读不通。白话层**只做展示翻译**，
绝不回写决断卡，因此 16 条门控规则与既有回归全部不受影响。
"""
from __future__ import annotations

import io
from pathlib import Path
from types import SimpleNamespace

import pytest
from rich.console import Console

import presentation.terminal_view as tv
from presentation.html_renderer import render_decision_card_html
from presentation.plain_language import (
    PLAIN_PILLAR_TITLES,
    SUBSTITUTIONS,
    TERMS,
    explain_terms,
    one_line_summary,
    plain,
)


def _card(**overrides) -> dict:
    card = {
        "ticker": "000001",
        "name": "平安银行",
        "price": 11.31,
        "pct_chg": 0.5,
        "decision_gear": "买入",
        "position_cap": 0.12,
        "decision_title": "买入",
        "invalidation_line": "跌破年线 9.85 元",
        "core_contradiction": "质地尚可但叙事溢价偏高，主力仍在吸筹",
        "action_tactic": "竞价挂涨停价抢筹",
        "pillar_1_quality": "质地五问：毛利率 31.2%，护城河来自客户认证周期",
        "pillar_2_state": "状态跃迁为改善，实锤来自年报，回声为传闻",
        "pillar_3_odds": "反向DCF隐含增速 18%，SOTP 分部估值 12.4 元，双锚背离",
        "pillar_4_path": "主力吸筹，筹码承载良好，微观穿透未见异常",
        "pillar_5_decision": {
            "triad_verdict": "[改善 | 合理 | 清晰]",
            "three_part_conclusion": "可买",
            "regulatory_status": "无异常",
        },
        "all_flags": [{"level": "🔴", "title": "商誉减值风险"}],
        "data_health": {},
        "lint_findings": [],
    }
    card.update(overrides)
    return card


# ---------------------------------------------------------------- plain()
def test_plain_replaces_jargon():
    assert plain("质地五问") == "基本面五问"          # 四字词可安全替换
    assert plain("反向DCF") == "按股价反推预期"
    assert plain("多空过渡区") == "多空交界"


def test_plain_does_not_expand_into_sentences():
    """★ 正文替换只能用**短**白话，不能把整句释义塞进句子里。

    这条是被真实报告打脸后加的：早先直接拿完整术语表做替换，
    「竞价」被展开成「开盘前集中撮合形成开盘价的那段时间」，句子彻底读不通。
    """
    out = plain("筹码沉淀承载良好，多空过渡区")
    assert out == "筹码分布良好，多空交界"
    assert len(out) <= 20


def test_real_report_jargon_is_translated():
    """★ 真实决断卡原文中挑出的行话，逐条确认已被翻掉。

    这些句子是从 `cli.py analyze 002850` 的实际输出里抄的，不是编的。
    """
    samples = [
        ("判定: 【↑变好+证据确认】 (变好引擎 λ: 主营内生稳健扩产)", "向好信号"),
        ("双锚同向标记: ✓ 同向共振", "两法是否同向"),
        ("判定: 【高尾险·不可承受】", "尾部风险高"),
        ("跌回 SOTP 保守底座左尾深度: -51.3%", "极端跌幅"),
        ("现价显著跌破知情均线 (148.52元)", "主力成本线"),
        ("置信度 49.5%，多空过渡区", "多空交界"),
        ("收入 CAGR 需达 17.3%", "年化增速"),
        ("区间高端 DCF=102.77元", "现金流折现"),
        ("反向 DCF (市场到底在赌什么)", "按股价反推预期"),
    ]
    for src, expect in samples:
        assert expect in plain(src), f"「{src}」未被翻译成含「{expect}」"


def test_numbers_survive_real_report_translation():
    """翻译不得吃掉任何数字 —— 价位与比例是决策依据。"""
    src = "现价(162.98元) = 低端 2.06x / 高端 1.59x；CAGR 17.3%；OCF 同比由负转正"
    out = plain(src)
    for num in ("162.98", "2.06x", "1.59x", "17.3%"):
        assert num in out, f"{num} 被翻译吃掉了"


def test_abbreviation_is_not_expanded_when_chinese_already_present():
    """★ 真实文本是「经营现金流 (OCF)」—— 中文已在前面，再翻缩写就成了
    「经营现金流 (经营现金流)」，纯粹添乱。"""
    src = "经营现金流 (OCF) 能否实现同比由负转正"
    assert plain(src) == src


def test_short_terms_do_not_mangle_compound_words():
    """★ 中文没有词边界：两字短词必须以完整词身份出现，不得命中别的词的子串。

    真实事故（跑了 002850 才暴露）：「游资」命中「下**游资**本」，
    把「等待行业下游资本开支指引」改成「等待行业下短线活跃资金本开支」。
    """
    protected = [
        "等待行业下游资本开支指引拐点",   # 含「游资」子串
        "早盘集合竞价平稳",               # 含「竞价」子串
        "上方套牢盘 64.1%",
    ]
    for src in protected:
        assert plain(src) == src, f"「{src}」被误伤成「{plain(src)}」"


def test_two_char_cjk_terms_are_not_substituted():
    """替换表里不允许出现纯两字中文词 —— 这是上面那条事故的根因防线。"""
    import re

    for jargon, _ in SUBSTITUTIONS:
        if re.fullmatch(r"[\u4e00-\u9fff]{1,2}", jargon):
            pytest.fail(f"'{jargon}' 是两字以内的中文词，会误伤复合词，不得进替换表")


def test_every_substitution_stays_short():
    """替换后的词必须够短，否则会把句子撑成一团解释文字。"""
    for jargon, meaning in SUBSTITUTIONS:
        assert len(meaning) <= 12, f"'{jargon}' 的替换 '{meaning}' 过长，会让句子读不通"


def test_plain_never_touches_numbers():
    """★ 最关键的不变量：翻译只动文字，价位/仓位/比例一律原样。"""
    src = "止损 9.85 元，仓位 12%，PE 33.5x，区间 8.60~10.20"
    assert plain(src) == src


def test_plain_handles_empty():
    assert plain("") == ""
    assert plain(None) == ""


def test_longest_jargon_wins_over_short():
    """「质地五问」不能被「质地」先命中切成半个词。"""
    assert plain("质地五问") == "基本面五问"


def test_terms_ordered_longest_first():
    """顺序是有意义的约束：若 A 包含 B，A 必须排在 B 前面，否则短词会先把长词切坏。"""
    for table in (TERMS, SUBSTITUTIONS):
        for i, (earlier, _) in enumerate(table):
            for later, _ in table[i + 1:]:
                assert earlier not in later, f"'{earlier}' 被包含在更靠后的 '{later}' 中，顺序反了"


# ---------------------------------------------------------------- 一句话结论
def test_one_line_summary_buy_gear():
    s = one_line_summary(_card())
    assert "平安银行" in s
    assert "12%" in s
    assert "退出" in s or "跌破" in s


def test_one_line_summary_zero_cap():
    s = one_line_summary(_card(decision_gear="回避", position_cap=0.0))
    assert "不建议占用资金" in s


def test_one_line_summary_flags_fatal_risk():
    s = one_line_summary(_card())
    assert "致命风险" in s


def test_one_line_summary_no_crash_on_empty_card():
    assert one_line_summary({})


def test_one_line_summary_does_not_stutter():
    """证伪线原文常以「跌破」开头，摘要不得再叠一个「跌破」前缀。"""
    s = one_line_summary(_card(invalidation_line="跌破年线 9.85 元无条件离场"))
    assert "跌破/跌破" not in s
    assert "9.85" in s


# ---------------------------------------------------------------- 术语按需
def test_explain_terms_only_hits_present():
    hits = explain_terms("这里的质地不错")
    assert [j for j, _ in hits] == ["质地"]


def test_explain_terms_respects_limit():
    assert len(explain_terms("质地 反向DCF 叙事溢价 主力", limit=2)) == 2


def test_explain_terms_empty():
    assert explain_terms("") == []


def test_pillar_titles_cover_all_five():
    for k in ("1", "2", "3", "4", "5"):
        title, desc = PLAIN_PILLAR_TITLES[k]
        assert title and desc


# ---------------------------------------------------------------- scenario_note 已接进展示层
def _pb(note: str = "") -> SimpleNamespace:
    return SimpleNamespace(
        action_label="买入",
        entry_tactic="竞价挂涨停价抢筹",
        entry_price_range="11.20~11.45",
        base_position_pct=4,
        add_position_pct=4,
        max_position_pct=12,
        take_profit_target="12.80",
        invalidation_rule="跌破 9.85 元无条件离场",
        scenario_note=note,
    )


def _render_html(card: dict, tmp_path) -> str:
    """`render_decision_card_html` 落盘并返回**路径**，测试需回读内容。"""
    out = tmp_path / "report.html"
    path = render_decision_card_html(card, output_path=str(out))
    return Path(path).read_text(encoding="utf-8")


def test_html_renders_scenario_note(tmp_path):
    html = _render_html(_card(playbook=_pb("高开 3% 以上且成都帮在场，需防冲高回落")), tmp_path)
    assert "盘中情景应对" in html
    assert "成都帮" in html
    assert "不含价位" in html


def test_html_omits_scenario_block_when_empty(tmp_path):
    """AI 关闭时 scenario_note 为空串，不该留下一个空表头。"""
    html = _render_html(_card(playbook=_pb("")), tmp_path)
    assert "盘中情景应对" not in html


def test_html_keeps_entry_tactic_intact(tmp_path):
    """★ 价位单点真理：白话化不得改动任何数字。"""
    html = _render_html(_card(playbook=_pb()), tmp_path)
    assert "11.20~11.45" in html
    assert "9.85" in html


def test_html_renders_one_line_summary_and_glossary(tmp_path):
    html = _render_html(_card(playbook=_pb()), tmp_path)
    assert "一句话结论" in html
    assert "术语速查" in html


def test_terminal_renders_scenario_note():
    buf = io.StringIO()
    original = tv.console
    tv.console = Console(file=buf, width=220, force_terminal=False)
    try:
        tv.print_decision_card(_card(playbook=_pb("炸板率近半，不宜解读为转强")))
    finally:
        tv.console = original
    out = buf.getvalue()
    assert "盘中情景应对" in out
    # 术语已被白话层翻译，因此断言的是翻译后的说法而非原词
    assert "涨停被砸开的比例" in out


def test_terminal_renders_one_line_summary():
    buf = io.StringIO()
    original = tv.console
    tv.console = Console(file=buf, width=220, force_terminal=False)
    try:
        tv.print_decision_card(_card(playbook=_pb()))
    finally:
        tv.console = original
    out = buf.getvalue()
    assert "一句话结论" in out
    assert "这公司靠不靠谱" in out


def test_terminal_does_not_crash_on_minimal_card():
    buf = io.StringIO()
    original = tv.console
    tv.console = Console(file=buf, width=220, force_terminal=False)
    try:
        tv.print_decision_card({})
    finally:
        tv.console = original
