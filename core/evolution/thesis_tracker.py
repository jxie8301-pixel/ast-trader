"""Thesis Tracker (股票分析假说追踪器).
Persists and tracks investment hypotheses, resistance/support pivots, and falsification rules.
"""
from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger("ast_trader.core.evolution.tracker")

LEDGER_DIR = Path("data/evolution")
LEDGER_FILE = LEDGER_DIR / "theses_ledger.json"


@dataclass
class ThesisRecord:
    """单一研报假说记录."""
    thesis_id: str
    ticker: str
    name: str
    trade_date: str
    decision_gear: str
    position_cap: float
    tactical_levels: dict[str, float] = field(default_factory=dict)
    falsification_lines: list[str] = field(default_factory=list)
    one_line_summary: str = ""
    status: str = "PENDING"  # PENDING / VERIFIED / FALSIFIED / EXPIRED
    created_at: float = field(default_factory=time.time)
    verified_at: float | None = None
    verification_notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ThesisRecord:
        return cls(**data)


class ThesisTracker:
    """个股假说追踪器."""

    def __init__(self, ledger_path: Path | str = LEDGER_FILE) -> None:
        self.ledger_path = Path(ledger_path)
        self.ledger_path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_file()

    def _ensure_file(self) -> None:
        if not self.ledger_path.exists():
            with open(self.ledger_path, "w", encoding="utf-8") as f:
                json.dump([], f, ensure_ascii=False, indent=2)

    def load_all(self) -> list[ThesisRecord]:
        try:
            with open(self.ledger_path, "r", encoding="utf-8") as f:
                raw = json.load(f)
                return [ThesisRecord.from_dict(item) for item in raw]
        except Exception as exc:
            logger.warning(f"读取假说账本异常: {exc}")
            return []

    def save_all(self, records: list[ThesisRecord]) -> None:
        try:
            with open(self.ledger_path, "w", encoding="utf-8") as f:
                json.dump([r.to_dict() for r in records], f, ensure_ascii=False, indent=2)
        except Exception as exc:
            logger.error(f"保存假说账本失败: {exc}")

    def record_thesis(self, card: dict[str, Any]) -> ThesisRecord:
        """从决断卡自动抽取核心假设并登记归档."""
        ticker = str(card.get("ticker", "000000"))
        trade_date = str(card.get("trade_date", time.strftime("%Y-%m-%d")))
        name = str(card.get("name", "未命名"))
        gear = str(card.get("decision_gear", "未给出"))
        cap = float(card.get("position_cap", 0.0) or 0.0)
        
        import re
        def _parse_float(val: Any) -> float:
            if val is None:
                return 0.0
            if isinstance(val, (int, float)):
                return float(val)
            m = re.search(r"[-+]?\d*\.?\d+", str(val))
            return float(m.group(0)) if m else 0.0

        # 抽取战术点位
        levels: dict[str, float] = {}
        odds = card.get("tactical_odds")
        if isinstance(odds, dict):
            if "entry_low" in odds:
                levels["entry_low"] = _parse_float(odds["entry_low"])
            if "entry_high" in odds:
                levels["entry_high"] = _parse_float(odds["entry_high"])
            if "stop_price" in odds:
                levels["stop"] = _parse_float(odds["stop_price"])
            if "target_price" in odds:
                levels["target"] = _parse_float(odds["target_price"])

        # 证伪与退出清单
        falsification: list[str] = []
        inv = card.get("invalidation_line")
        if inv and isinstance(inv, str):
            falsification.append(inv.strip())
        mf_risk = card.get("main_force_risk")
        if mf_risk and isinstance(mf_risk, str):
            falsification.append(mf_risk.strip())

        one_line = str(card.get("one_line_summary_text") or "")

        thesis_id = f"{ticker}_{trade_date.replace('-', '')}_{int(time.time()) % 10000:04d}"
        record = ThesisRecord(
            thesis_id=thesis_id,
            ticker=ticker,
            name=name,
            trade_date=trade_date,
            decision_gear=gear,
            position_cap=cap,
            tactical_levels=levels,
            falsification_lines=falsification,
            one_line_summary=one_line,
        )

        all_records = self.load_all()
        # 若已有同标的同日期的记录，更新之；否则追加
        existing_idx = next(
            (i for i, r in enumerate(all_records) if r.ticker == ticker and r.trade_date == trade_date),
            None,
        )
        if existing_idx is not None:
            all_records[existing_idx] = record
        else:
            all_records.append(record)

        self.save_all(all_records)
        logger.info(f"成功归档个股分析假说 [{thesis_id}]")
        return record
