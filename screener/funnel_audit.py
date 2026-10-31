"""筛选漏斗的逐层淘汰归因矩阵。

★ 为什么必须有这个模块
------------------------
改造前的三层漏斗只有 ``filter_liquidity`` 打了几个 ``dropped_*`` 计数日志，
``filter_audit`` / ``rank_composite`` 完全没有口径。后果是：

* 无法回答「这只票为什么没进池」—— 只有天知道；
* 无法回答「这次跑批到底扫了多少只」—— 所谓"全市场"无法自证；
* **无法发现死规则**。Tier 1 的换手率门槛（8%~25%）因为取错了字段恒为 0，
  潜伏至今无人察觉，就是因为没有「某规则淘汰数恒为 0 就告警」的机制。

本模块提供三件事：
1. **守恒断言**：每层 ``input == Σ dropped_by_reason + output``；
2. **归因矩阵**：每个 ``reason_code`` 的淘汰计数，可渲染、可断言；
3. **死规则检测**：声明了却从不触发的规则自动告警（白名单除外）。

★ 用法约定
----------
每个筛选层在**执行前**先 ``register_expected_rules(stage, rules)`` 声明自己有哪些
判据，再在执行中 ``record_drop(stage, reason)``。只声明不触发 → 死规则告警。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

import config

#: 标准层名（顺序即漏斗顺序）
STAGE_UNIVERSE = "L0_universe"
STAGE_PROFILE = "L1_profile"
STAGE_LIQUIDITY = "T1_liquidity"
STAGE_AUDIT = "T2_audit"
STAGE_RANK = "T3_rank"
# 第二/三批：四轨分流后各轨独立的阶段（轨道 A 即上面的 T1/T2/T3 链路）
STAGE_TRACK_B = "TrackB"
STAGE_TRACK_C = "TrackC"
STAGE_TRACK_D = "TrackD"

STAGE_ORDER: tuple[str, ...] = (
    STAGE_UNIVERSE, STAGE_PROFILE,
    STAGE_LIQUIDITY, STAGE_AUDIT, STAGE_RANK,          # 轨道 A
    STAGE_TRACK_B, STAGE_TRACK_C, STAGE_TRACK_D,       # 轨道 B / C / D
)


@dataclass
class StageAudit:
    """单层的淘汰台账。"""

    stage: str
    input_count: int = 0
    output_count: int = 0
    dropped: dict[str, int] = field(default_factory=dict)
    #: 该层声明的判据集合（用于死规则检测）
    expected_rules: set[str] = field(default_factory=set)

    def bump(self, reason: str, n: int = 1) -> None:
        if n <= 0:
            return
        self.dropped[reason] = self.dropped.get(reason, 0) + n

    def rebate(self, reason: str, n: int = 1) -> None:
        """回冲某判据的淘汰计数（**只用于**"先被淘汰、后被重新纳入"的场景）。

        ★ 20261029 审计 P1-9：Tier 2 排雷队列被限流截断的标的，在精选池没填满时
          会被**重新纳入排雷**（补排雷补位）。它们当初已计入
          ``AUDIT_QUEUE_TRUNCATED``，回补时必须回冲，否则同一个标的既算"被截断"
          又算"通过"，归因矩阵重复计数 → 漏斗不守恒。回冲不会让计数变成负数。
        """
        if n <= 0:
            return
        cur = self.dropped.get(reason, 0)
        self.dropped[reason] = max(0, cur - n)

    @property
    def dropped_total(self) -> int:
        return sum(self.dropped.values())

    @property
    def conserved(self) -> bool:
        """守恒：``input == Σ dropped + output``。"""
        return self.input_count == self.dropped_total + self.output_count

    @property
    def gap(self) -> int:
        """不守恒时的差额（正=少了，负=多了）。"""
        return self.input_count - (self.dropped_total + self.output_count)

    def dead_rules(self, whitelist: frozenset[str] | set[str] | None = None) -> list[str]:
        """本层「声明了但一次都没触发」的规则。

        白名单同时支持裸 ``reason_code`` 与 ``"层名/reason_code"`` 两种写法 ——
        同一判据在不同层的"应不应该触发"可能不同（例如 ST 剔除在 L0 是主判据，
        在 T1 只是兜底防线，恒 0 完全正常）。
        """
        wl = whitelist if whitelist is not None else _default_whitelist()
        out = []
        for r in self.expected_rules:
            if self.dropped.get(r, 0) > 0:
                continue
            if r in wl or f"{self.stage}/{r}" in wl:
                continue
            out.append(r)
        return sorted(out)

    def to_dict(self) -> dict[str, Any]:
        return {
            "stage": self.stage,
            "input_count": self.input_count,
            "output_count": self.output_count,
            "dropped": dict(self.dropped),
            "dropped_total": self.dropped_total,
            "conserved": self.conserved,
            "gap": self.gap,
            "expected_rules": sorted(self.expected_rules),
        }


def _default_whitelist() -> frozenset[str]:
    return frozenset(getattr(config, "UNIVERSE_DEAD_RULE_WHITELIST", frozenset()))


class FunnelAudit:
    """漏斗全层的归因矩阵。"""

    def __init__(self) -> None:
        self.stages: dict[str, StageAudit] = {}

    # ───────────────────────────────────────── 登记
    def stage(self, name: str) -> StageAudit:
        """获取（或创建）某层台账。"""
        st = self.stages.get(name)
        if st is None:
            st = StageAudit(stage=name)
            self.stages[name] = st
        return st

    def register_expected_rules(self, stage: str, rules: Iterable[str]) -> None:
        """声明某层拥有哪些判据（用于死规则检测）。"""
        self.stage(stage).expected_rules.update(r for r in rules if r)

    def record_input(self, stage: str, n: int) -> None:
        self.stage(stage).input_count = int(n)

    def record_output(self, stage: str, n: int) -> None:
        self.stage(stage).output_count = int(n)

    def record_drop(self, stage: str, reason: str, n: int = 1) -> None:
        self.stage(stage).bump(reason, n)

    def rebate_drop(self, stage: str, reason: str, n: int = 1) -> None:
        """回冲某层某判据的淘汰计数（见 `StageAudit.rebate` 的 P1-9 说明）。"""
        self.stage(stage).rebate(reason, n)

    # ───────────────────────────────────────── 查询
    def ordered(self) -> list[StageAudit]:
        """按漏斗顺序返回（未登记的层跳过）。"""
        out = [self.stages[s] for s in STAGE_ORDER if s in self.stages]
        extra = [v for k, v in self.stages.items() if k not in STAGE_ORDER]
        return out + sorted(extra, key=lambda s: s.stage)

    @property
    def all_conserved(self) -> bool:
        return all(s.conserved for s in self.ordered())

    def violations(self) -> list[str]:
        """不守恒的层（说明有标的被"无声丢弃"，归因链断了）。"""
        return [
            f"{s.stage}: input={s.input_count} dropped={s.dropped_total} "
            f"output={s.output_count} (差额 {s.gap:+d})"
            for s in self.ordered() if not s.conserved
        ]

    def dead_rules(self, whitelist: frozenset[str] | set[str] | None = None) -> list[str]:
        """全漏斗的死规则（形如 ``"T1_liquidity/TURNOVER_OUT_OF_RANGE"``）。"""
        out: list[str] = []
        for s in self.ordered():
            for r in s.dead_rules(whitelist):
                out.append(f"{s.stage}/{r}")
        return out

    def total_dropped(self) -> dict[str, int]:
        agg: dict[str, int] = {}
        for s in self.ordered():
            for reason, n in s.dropped.items():
                agg[reason] = agg.get(reason, 0) + n
        return agg

    def to_dict(self) -> dict[str, Any]:
        return {
            "all_conserved": self.all_conserved,
            "violations": self.violations(),
            "dead_rules": self.dead_rules(),
            "total_dropped": self.total_dropped(),
            "stages": [s.to_dict() for s in self.ordered()],
        }

    # ───────────────────────────────────────── 渲染
    def render_lines(self, *, max_reasons: int = 12) -> list[str]:
        """生成终端面板用的文本行。"""
        lines: list[str] = []
        for s in self.ordered():
            flag = "" if s.conserved else f"  ⚠️不守恒(差额 {s.gap:+d})"
            lines.append(f"{s.stage}: {s.input_count} 进 → {s.output_count} 出 (淘汰 {s.dropped_total}){flag}")
            if s.dropped:
                items = sorted(s.dropped.items(), key=lambda kv: -kv[1])[:max_reasons]
                lines.append("    " + " | ".join(f"{k}:{v}" for k, v in items))
        dead = self.dead_rules()
        if dead:
            lines.append(f"⚠️ 死规则（声明了但本次零命中）: {', '.join(dead)}")
        return lines


def merge_dropped(audit: FunnelAudit, stage: str, dropped: dict[str, int]) -> None:
    """把外部筛选器批量统计的 ``{reason: count}`` 并入台账。

    用于 ``filter_liquidity`` 这类一次性返回批量统计的筛选器。
    """
    for reason, n in (dropped or {}).items():
        audit.record_drop(stage, reason, n)
