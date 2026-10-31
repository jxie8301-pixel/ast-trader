"""Postmortem Engine (事后反思与回测核销引擎).
Validates historical theses against subsequent market prices and generates reflection logs.
"""
from __future__ import annotations

import logging
from typing import Any

from core.evolution.memory import EvolutionMemory, LessonRecord
from core.evolution.thesis_tracker import ThesisRecord, ThesisTracker

logger = logging.getLogger("ast_trader.core.evolution.postmortem")


class PostmortemEngine:
    """个股研报假说回测核销与归因反思引擎."""

    def __init__(
        self,
        tracker: ThesisTracker | None = None,
        memory: EvolutionMemory | None = None,
    ) -> None:
        self.tracker = tracker or ThesisTracker()
        self.memory = memory or EvolutionMemory()

    def audit_theses_with_quotes(
        self,
        current_quotes: dict[str, float],
    ) -> list[dict[str, Any]]:
        """用当前最新市场报价核销所有 PENDING 的历史假设."""
        all_theses = self.tracker.load_all()
        results: list[dict[str, Any]] = []

        for t in all_theses:
            if t.status != "PENDING":
                continue
            cur_price = current_quotes.get(t.ticker)
            if not cur_price or cur_price <= 0:
                continue

            stop_price = t.tactical_levels.get("stop", 0.0)
            target_price = t.tactical_levels.get("target", 0.0)
            res_price = t.tactical_levels.get("entry_high", 0.0)

            # 校验是否破位止损
            if stop_price > 0 and cur_price < stop_price:
                t.status = "FALSIFIED"
                t.verification_notes = f"现价 {cur_price:.2f} 跌破止损线 {stop_price:.2f}，假说被证伪"
            # 校验是否达成目标位
            elif target_price > 0 and cur_price >= target_price:
                t.status = "VERIFIED"
                t.verification_notes = f"现价 {cur_price:.2f} 达成目标价 {target_price:.2f}，买方逻辑兑现"
            # 校验是否放量突破近端压力位
            elif res_price > 0 and cur_price >= res_price and t.decision_gear in ("等证据临界(观察)", "观察"):
                t.verification_notes = f"现价 {cur_price:.2f} 突破近端压力位 {res_price:.2f}，触发右侧跟踪信号"

            results.append({
                "thesis_id": t.thesis_id,
                "ticker": t.ticker,
                "status": t.status,
                "notes": t.verification_notes,
            })

        self.tracker.save_all(all_theses)
        return results
