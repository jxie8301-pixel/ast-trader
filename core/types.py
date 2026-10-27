"""Data models and interfaces for AST-Trader matching Section 6 of SRS/SAD."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .red_flags import RedFlagItem


@dataclass
class SingleStockContext:
    """个股深度穿透上下文容器。"""
    ticker: str
    name: str
    trade_date: str
    quote: dict[str, Any] = field(default_factory=dict)
    financials: dict[str, Any] = field(default_factory=dict)
    concept_blocks: list[str] = field(default_factory=list)
    audit_flags: list[RedFlagItem] = field(default_factory=list)
    youzi_matched: list[dict[str, Any]] = field(default_factory=list)
    trap_score: int = 0
    trap_warnings: list[str] = field(default_factory=list)


@dataclass
class DecisionCardData:
    """五节点因果决断卡数据模型。"""
    ticker: str
    name: str
    trade_date: str
    price: float
    pct_chg: float
    quality_verdict: str
    state_verdict: str
    odds_verdict: str
    path_verdict: str
    decision_gear: str  # 买入 / 观察 / 回避
    position_cap: float
    invalidation_line: str
    top3_risks: list[dict[str, Any]] = field(default_factory=list)
    all_flags: list[dict[str, Any]] = field(default_factory=list)
    matched_youzi: list[dict[str, Any]] = field(default_factory=list)
    trap_warnings: list[str] = field(default_factory=list)


@dataclass
class ScreenerCandidate:
    """全市场短线漏斗筛选候选标的数据结构。"""
    code: str
    full_code: str
    name: str
    close: float
    pct_chg: float
    amount: float
    board_level: int
    limit_reason: str
    seal_amt: float
    main_net_wan: float = 0.0
    main_ratio: float = 0.0
    rank_score: float = 0.0
    concepts: list[str] = field(default_factory=list)
    plan_high_open: str = ""
    plan_stop_loss: str = ""
