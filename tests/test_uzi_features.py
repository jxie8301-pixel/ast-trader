"""Unit tests for newly integrated UZI-Skill core features in AST-Trader."""
from __future__ import annotations

import json
from pathlib import Path

from core.execution_playbook import PlaybookBuilder
from core.investor_panel import InvestorPanelJury
from core.red_flags import RedFlagItem, LEVEL_FATAL
from screener.ladder_analyzer import LadderAnalyzer, ThemeAggregate
from screener.tracker import record_screen_picks, load_tracker_records


def test_investor_panel_jury_veto_on_fatal_flag():
    """验证当标的命中致命财务红旗时，陪审团巴菲特、芒格、伯里触发 VETO 否决。"""
    jury = InvestorPanelJury()
    fatal_flag = RedFlagItem(
        id="beneish_manipulation",
        framework="Beneish M-Score",
        level=LEVEL_FATAL,
        title="Beneish M-Score 财务操纵预警",
        value=-1.2,
        threshold="M > -1.78",
        evidence="M-Score=-1.2 > -1.78",
        node="quality",
    )
    result = jury.evaluate(
        quote={"close": 25.0, "pe": 15.0, "pb": 2.0, "turnover_ratio": 6.0},
        momentum={"is_bullish_ma": True, "volume_ratio": 2.0},
        flags=[fatal_flag],
        trap_warnings=[],
        matched_personas=["章盟主"],
        concepts=["半导体"],
    )

    assert result.veto_votes >= 3
    assert "一票否决" in result.panel_verdict
    assert result.consensus_pct < 50.0


def test_investor_panel_jury_strong_buy():
    """验证优质白马在无红旗、高动能且契合游资战法时，陪审团给出高赞成率。"""
    jury = InvestorPanelJury()
    result = jury.evaluate(
        quote={"close": 50.0, "pe": 22.0, "pb": 3.0, "turnover_ratio": 8.0},
        momentum={"is_bullish_ma": True, "volume_ratio": 2.2},
        flags=[],
        trap_warnings=[],
        matched_personas=["孙哥", "炒股养家"],
        concepts=["人形机器人", "AI算力"],
    )

    assert result.veto_votes == 0
    assert result.buy_votes >= 4
    assert result.consensus_pct >= 65.0
    assert "强烈多头共识" in result.panel_verdict


def test_execution_playbook_buy_tactics():
    """验证主升做多 BUY 状态生成符合实战纪律的战术卡与仓位配比。"""
    builder = PlaybookBuilder()
    pb = builder.build(
        quote={"close": 20.0, "pre_close": 19.0},
        momentum={"support_level": 19.0, "resistance_level": 22.0},
        matched_personas=["赵老哥"],
        action="BUY",
        ladder_info={"is_leader": True, "board_level": 3},
        fatal_flag=False,
    )

    assert pb.action == "BUY"
    assert pb.base_position_pct == 15
    assert pb.add_position_pct == 10
    assert pb.max_position_pct == 25
    assert "龙头加速打板" in pb.entry_tactic
    assert "死锁退出线" in pb.invalidation_rule


def test_execution_playbook_avoid_on_fatal():
    """验证命中致命风险时强制锁定 AVOID 档位且仓位归零。"""
    builder = PlaybookBuilder()
    pb = builder.build(
        quote={"close": 10.0, "pre_close": 10.0},
        momentum={"support_level": 9.0, "resistance_level": 11.0},
        matched_personas=[],
        action="BUY",
        ladder_info=None,
        fatal_flag=True,
    )

    assert pb.action == "AVOID"
    assert pb.base_position_pct == 0
    assert pb.max_position_pct == 0
    assert "严禁任何形式的买入" in pb.entry_tactic


def test_tracker_record_and_load(tmp_path, monkeypatch):
    """验证 Paper-Trading 选股追踪账本的原子追加与读取。"""
    test_file = tmp_path / "test_tracker.jsonl"
    monkeypatch.setattr("screener.tracker.TRACKER_PATH", test_file)

    sample_picks = [
        {
            "code": "002273",
            "name": "水晶光电",
            "close": 22.50,
            "pct_chg": 5.20,
            "action": "buyable",
            "main_net_wan": 15000.0,
            "matched_personas": ["孙哥"],
        }
    ]

    count = record_screen_picks(sample_picks, mode="close")
    assert count == 1
    assert test_file.exists()

    records = load_tracker_records()
    assert len(records) == 1
    assert records[0]["code"] == "002273"
    assert records[0]["close"] == 22.50
