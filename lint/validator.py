"""Lint gating and verification rules for AST-Trader decision cards.
Strictly aligned with Ashare-researchreport/scripts/lint_v8.py.
"""
from __future__ import annotations

import logging
import re
from typing import Any

# 致命红旗标识 (解耦与 core.red_flags 的反向循环依赖，lint 作为纯净独立门控模块)
LEVEL_FATAL = "🔴"

logger = logging.getLogger("ast_trader.lint")


class LintError(ValueError):
    """违反质量门控硬约束异常 (保留用于兼容语义；生产环境优先采用'以纠代抛'自动降级清零门控机制)。"""


class LintValidator:
    """质量门控校验器 (全面对齐 Ashare-researchreport/scripts/lint_v8.py)."""

    # R9 无记忆性反例关键词库 (禁把"跌多了该涨/估值压久了该修复"当买入逻辑)
    FORBIDDEN_MEMORYLESS_PHRASES = (
        "跌久了该涨",
        "跌多了该涨",
        "估值压久了该修复",
        "超跌必反弹",
        "连跌必涨",
        "位置低安全",
        "不可能再跌了",
    )

    def __init__(self) -> None:
        pass

    def validate(self, decision_card: dict[str, Any], flags: list[RedFlagItem]) -> tuple[bool, list[str]]:
        """执行全套门控机检。返回 (passed: bool, findings: list[str])。"""
        findings = []

        fatal_flags = [f for f in flags if f.level == LEVEL_FATAL]
        gear = str(decision_card.get("decision_gear") or "")
        pos = float(decision_card.get("position_cap", 0.0) or 0.0)

        # ─── R7: 决策字段齐全 + 致命红旗强制封顶 ───
        if fatal_flags and gear != "回避":
            findings.append(
                f"[R7 致命红旗未回避] 存在 {len(fatal_flags)} 条 🔴 致命红旗 "
                f"({', '.join(f.title for f in fatal_flags[:2])})，"
                f"但行动档位被写成 '{gear}'，必须强制封顶为 '回避'！"
            )

        if fatal_flags and pos > 0.0:
            findings.append(
                f"[R7 致命红旗仓位未清零] 存在致命红旗时，单票仓位上限必须为 0.0，实际给出了 {pos*100:.1f}%！"
            )

        # ─── R8: 越权发声检查 (仓位/买卖指令只能出现在⑤决策中，严禁在支柱①~④正文中越权出现) ───
        nodes_to_check = [
            ("pillar_1_quality", "①质地正文"),
            ("pillar_2_state", "②状态正文"),
            ("pillar_3_odds", "③赔率正文"),
            ("pillar_4_path", "④路径正文"),
            ("quality_verdict", "①质地判定"),
            ("state_verdict", "②状态判定"),
            ("odds_verdict", "③赔率判定"),
            ("path_verdict", "④路径判定"),
        ]
        action_forbidden_terms = ["建议买入", "立即买入", "建议建仓", "立即建仓", "开始建仓", "满仓", "半仓", "清仓离场", "立即清仓", "逢低加仓", "建议加仓"]
        for node_key, label in nodes_to_check:
            text = str(decision_card.get(node_key, "") or "")
            for term in action_forbidden_terms:
                if term in text:
                    findings.append(f"[R8 越权发声] {label} 包含行动/买卖指令 '{term}'，违背职责分离原则！")
                    break

        # ─── R9: 无记忆性反例 ───
        all_text = " ".join(str(v) for v in decision_card.values())
        is_buy_gear = any(k in gear for k in ["买入", "做多", "核心", "期权仓"])
        for phrase in self.FORBIDDEN_MEMORYLESS_PHRASES:
            if phrase in all_text and is_buy_gear:
                findings.append(f"[R9 无记忆性反例] 出现禁止的反例推论 '{phrase}'，严禁作为买入依据！")

        # ─── R13: 证伪清单同源 ───
        inv_line = str(decision_card.get("invalidation_line", "")).strip()
        if not inv_line:
            findings.append("[R13 缺失绝对证伪线] 决断卡必须在买入前写死具体退出线！")

        passed = len(findings) == 0
        return passed, findings
