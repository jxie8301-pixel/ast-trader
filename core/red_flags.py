"""Red flag definition, aggregation, grouping and prioritization for AST-Trader.
Strictly aligned with Ashare-researchreport/scripts/red_flags.py.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

LEVEL_FATAL = "🔴"
LEVEL_HIGH = "🟠"
LEVEL_MEDIUM = "🟡"
LEVEL_LOW = "🟢"
LEVEL_INFO = "ℹ️"

LEVELS = (LEVEL_FATAL, LEVEL_HIGH, LEVEL_MEDIUM, LEVEL_LOW, LEVEL_INFO)
LEVEL_ORDER = {lvl: i for i, lvl in enumerate(LEVELS)}

MARK_BY_LEVEL = {LEVEL_FATAL: "red", LEVEL_HIGH: "red", LEVEL_MEDIUM: "yellow", LEVEL_LOW: None, LEVEL_INFO: None}
MARKED_LEVELS = tuple(lvl for lvl, mark in MARK_BY_LEVEL.items() if mark)

NODES = ("quality", "state", "odds", "path")
NODE_LABELS = {"quality": "①质地", "state": "②状态", "odds": "③赔率", "path": "④路径"}
NODE_ORDER = {"path": 0, "odds": 1, "quality": 2, "state": 3}


@dataclass
class RedFlagItem:
    id: str                                  # 稳定标识 (framework slug + title hash)
    framework: str                           # 审计框架名
    level: Literal["🔴", "🟠", "🟡", "🟢", "ℹ️"] # 级别
    title: str                               # 信号标题
    value: Any                               # 触发数值
    threshold: str                           # 阈值
    evidence: str                            # 凭据描述
    node: Literal["quality", "state", "odds", "path"] # 归属节点
    metric_refs: list[str] = field(default_factory=list) # 首要关联指标 (用于分组与红标反查)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def make_flag_id(framework: str, title: str) -> str:
    """生成合规的 ASCII slug + 稳定短哈希 id。"""
    slug = re.sub(r"[^A-Za-z0-9]+", "-", framework).strip("-").lower() or "flag"
    h = hashlib.md5(title.encode("utf-8")).hexdigest()[:6]
    return f"{slug}_{h}"


def group_key(flag: RedFlagItem) -> str:
    """分组键 = 首要关联指标; 无关联指标的条目自成一组 (不与任何风险合并)。"""
    return flag.metric_refs[0] if flag.metric_refs else f"id:{flag.id}"


def group_flags(flags: list[RedFlagItem]) -> list[dict[str, Any]]:
    """按首要关联指标聚成风险组, 保持首次出现序。组级 level = 组内最严重。
    完全对齐 Ashare-researchreport/scripts/red_flags.py:201
    """
    groups: dict[str, dict[str, Any]] = {}
    for idx, flag in enumerate(flags):
        k = group_key(flag)
        g = groups.get(k)
        if g is None:
            groups[k] = {"key": k, "flags": [flag], "first_index": idx}
        else:
            g["flags"].append(flag)

    out = []
    for g in groups.values():
        rep = min(g["flags"], key=lambda f: LEVEL_ORDER.get(f.level, 99))
        out.append({
            "key": g["key"],
            "flags": g["flags"],
            "representative": rep,
            "level": rep.level,
            "size": len(g["flags"]),
            "node": rep.node,
            "first_index": g["first_index"],
        })
    return out


def _group_sort_key(g: dict[str, Any]) -> tuple:
    """同级同条数时的杀伤力序: 能让本金永久损失的(路径左尾) > 定价透支(赔率) > 经营质量 > 状态。
    完全对齐 Ashare-researchreport/scripts/red_flags.py:226
    """
    return (
        LEVEL_ORDER.get(g["level"], 99),
        -g["size"],
        NODE_ORDER.get(g["node"], 99),
        g["first_index"],
    )


def get_top3_risks(flags: list[RedFlagItem]) -> list[RedFlagItem]:
    """Top3 风险 = 红旗清单机器带出。同组多条红旗合并为一条代表。
    完全对齐 Ashare-researchreport/scripts/red_flags.py:230
    """
    if not flags:
        return []
    candidates = [g for g in group_flags(flags) if g["level"] in MARKED_LEVELS]
    if not candidates:
        candidates = group_flags(flags)
    ranked = sorted(candidates, key=_group_sort_key)[:3]
    return [g["representative"] for g in ranked]


def has_fatal_red_flags(flags: list[RedFlagItem]) -> bool:
    """是否包含 🔴 致命红旗。"""
    return any(f.level == LEVEL_FATAL for f in flags)
