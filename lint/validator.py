"""Lint gating and verification rules for AST-Trader decision cards."""
from __future__ import annotations

from typing import Any

from core.red_flags import LEVEL_FATAL, RedFlagItem


class LintError(ValueError):
    """违反质量门控硬约束异常。"""


class LintValidator:
    """质量门控校验器。"""

    def __init__(self) -> None:
        pass

    def validate(self, decision_card: dict[str, Any], flags: list[RedFlagItem]) -> tuple[bool, list[str]]:
        """执行全套门控检查。返回 (passed: bool, findings: list[str])。"""
        findings = []

        fatal_flags = [f for f in flags if f.level == LEVEL_FATAL]
        gear = decision_card.get("decision_gear")
        pos = decision_card.get("position_cap", 0.0)

        # 规则 1: 致命红旗封顶回避
        if fatal_flags and gear != "回避":
            findings.append(
                f"[R1 致命红旗未回避] 存在 {len(fatal_flags)} 条 🔴 致命红旗 "
                f"({', '.join(f.title for f in fatal_flags[:2])})，"
                f"但行动档位被写成 '{gear}'，必须强制封顶为 '回避'！"
            )

        # 规则 2: 致命红旗仓位归零
        if fatal_flags and pos > 0.0:
            findings.append(
                f"[R2 致命红旗仓位未清零] 存在致命红旗时，单票仓位上限必须为 0.0，实际给出了 {pos*100:.1f}%！"
            )

        # 规则 3: 退出线不可为空
        inv_line = decision_card.get("invalidation_line", "").strip()
        if not inv_line:
            findings.append("[R3 缺失绝对证伪线] 决断卡必须在买入前写死具体退出线！")

        passed = len(findings) == 0
        return passed, findings
