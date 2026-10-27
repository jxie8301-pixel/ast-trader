"""Red flag definition, aggregation and prioritization for AST-Trader."""
from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass
from typing import Any, Literal

LEVEL_FATAL = "🔴"
LEVEL_HIGH = "🟠"
LEVEL_MEDIUM = "🟡"
LEVEL_LOW = "🟢"

LEVEL_ORDER = {LEVEL_FATAL: 0, LEVEL_HIGH: 1, LEVEL_MEDIUM: 2, LEVEL_LOW: 3}
NODE_ORDER = {"path": 0, "odds": 1, "quality": 2, "state": 3}


@dataclass
class RedFlagItem:
    id: str                                  # 稳定标识
    framework: str                           # 审计框架名
    level: Literal["🔴", "🟠", "🟡", "🟢"]     # 级别
    title: str                               # 信号标题
    value: Any                               # 触发数值
    threshold: str                           # 阈值
    evidence: str                            # 凭据描述
    node: Literal["quality", "state", "odds", "path"] # 归属节点

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def make_flag_id(framework: str, title: str) -> str:
    slug = "".join(c if c.isalnum() else "_" for c in framework.lower()).strip("_")
    h = hashlib.md5(title.encode("utf-8")).hexdigest()[:6]
    return f"{slug}_{h}"


def get_top3_risks(flags: list[RedFlagItem]) -> list[RedFlagItem]:
    """按杀伤力排序获取 Top3 核心致命风险。
    
    排序规则：
    1. 级别：🔴 > 🟠 > 🟡 > 🟢
    2. 归属节点杀伤力：path (本金永久损失) > odds (估值透支) > quality (财务成色) > state (拐点)
    """
    sorted_flags = sorted(
        flags,
        key=lambda f: (
            LEVEL_ORDER.get(f.level, 99),
            NODE_ORDER.get(f.node, 99),
        )
    )
    return sorted_flags[:3]


def has_fatal_red_flags(flags: list[RedFlagItem]) -> bool:
    """是否包含 🔴 致命红旗。"""
    return any(f.level == LEVEL_FATAL for f in flags)
