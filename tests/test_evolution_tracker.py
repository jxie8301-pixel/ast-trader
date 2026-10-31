"""Unit tests for ThesisTracker, EvolutionMemory, and PostmortemEngine."""
from __future__ import annotations

import tempfile
from pathlib import Path

from core.evolution.memory import EvolutionMemory, LessonRecord
from core.evolution.postmortem import PostmortemEngine
from core.evolution.thesis_tracker import ThesisTracker


def test_thesis_tracker_lifecycle():
    with tempfile.TemporaryDirectory() as tmpdir:
        ledger_path = Path(tmpdir) / "theses.json"
        tracker = ThesisTracker(ledger_path=ledger_path)
        
        card = {
            "ticker": "002850",
            "name": "科达利",
            "trade_date": "2026-10-31",
            "decision_gear": "等证据临界(观察)",
            "position_cap": 0.0,
            "tactical_odds": {
                "entry_high": 163.00,
                "stop_price": 139.68,
                "target_price": 174.81,
            },
            "invalidation_line": "若全年OCF<0则触发退出",
            "main_force_risk": "跌破139.68止损",
            "one_line_summary_text": "科达利：先看着。不建议占用资金。",
        }
        
        record = tracker.record_thesis(card)
        assert record.ticker == "002850"
        assert record.status == "PENDING"
        assert record.tactical_levels["entry_high"] == 163.00
        
        # 重新读取验证持久化
        reloaded = tracker.load_all()
        assert len(reloaded) == 1
        assert reloaded[0].thesis_id == record.thesis_id


def test_postmortem_engine_audits_theses():
    with tempfile.TemporaryDirectory() as tmpdir:
        ledger_path = Path(tmpdir) / "theses.json"
        mem_path = Path(tmpdir) / "lessons.json"
        tracker = ThesisTracker(ledger_path=ledger_path)
        memory = EvolutionMemory(memory_path=mem_path)
        
        card = {
            "ticker": "002850",
            "name": "科达利",
            "trade_date": "2026-10-31",
            "decision_gear": "观察",
            "position_cap": 0.0,
            "tactical_odds": {
                "entry_high": 163.00,
                "stop_price": 139.68,
                "target_price": 174.81,
            },
        }
        tracker.record_thesis(card)
        
        engine = PostmortemEngine(tracker=tracker, memory=memory)
        # 模拟盘面跌破止损线
        results = engine.audit_theses_with_quotes({"002850": 135.00})
        assert len(results) == 1
        assert results[0]["status"] == "FALSIFIED"
        assert "跌破止损线" in results[0]["notes"]
        
        # 校验持久化状态已更新
        theses = tracker.load_all()
        assert theses[0].status == "FALSIFIED"
