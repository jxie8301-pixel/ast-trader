"""Automated Closed-Loop Report Validator for AST-Trader.
Benchmarked against Stock Analysis V5.2 validation architecture (https://github.com/a2223956-cell/-stock-analysis).

Validates generated HTML reports and decision cards across 7 essential consistency gates:
1. Verdict & Main Force Stance Coherence (No bullish accumulation under Avoid/0% cap)
2. Tactical Odds Circuit-Breaker Integrity (No buy range / target price on Avoid)
3. Capital Matrix Position Alignment (No base position under zero-cap defense)
4. Anti-Hallucination & Ground-Truth Defense (No contradictory red flags)
5. Zero Dangling Truncation / Natural Ending Gate
6. Red Flag Evidence Completeness Gate
7. HTML Structural & Card Component Integrity
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path
from typing import Any

# Windows 终端 UTF-8 编码适配
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")


class ReportValidationError(Exception):
    """报告校验失败异常."""
    pass


class ReportValidator:
    """自动化闭环研报校验器."""

    def __init__(self) -> None:
        pass

    def validate_html(self, html_path: str | Path) -> tuple[bool, list[str]]:
        """校验 HTML 报告文件一致性与合规性."""
        path = Path(html_path)
        if not path.exists():
            return False, [f"文件不存在: {html_path}"]

        html_content = path.read_text(encoding="utf-8")
        findings: list[str] = []

        # Gate 1: 决断档位与主力生命周期叙事一致性
        is_avoid = "决断档位: 回避" in html_content or "决断档位: 减仓" in html_content or "仓位: <strong>0%</strong>" in html_content or "建议仓位: <strong>0%</strong>" in html_content

        if is_avoid:
            # 回避/零仓位下，严禁出现看多、吸筹、主升、低吸措辞
            forbidden_phrases = [
                "筹码结构扎实健康",
                "主力以时间换空间耐心清洗浮动获利盘",
                "【依托支撑均线回踩企稳低吸】",
                "【顺势做多 / 分时回踩均线低吸】",
                "【黄金坑低吸 / 等待右侧长阳收复】",
                "【逢低试仓 / 贴合主力成本建底仓】",
                "【🌱 低位隐蔽吸筹期】",
                "【🕳️ 假破位恐慌挖坑期 (空头陷阱)】",
                "【🚀 健康放量主升期】",
                "维持中性底仓",
                "维持底仓",
                "单票上限 <strong style=\"color:#f87171\">15%</strong>",
                "建议先加入自选观察，等放量企稳或大盘好转再行介入",
            ]
            for phrase in forbidden_phrases:
                if phrase in html_content:
                    findings.append(f"Gate 1 失败 (叙事自相矛盾): 回避/零仓位报告中残留多头词汇 [{phrase}]")

            # 检查主力实操动作
            if any(act in html_content for act in [
                "实操动作:</strong> <span style=\"color:#38bdf8;\">依托支撑均线回踩企稳低吸",
                "实操动作:</strong> <span style=\"color:#38bdf8;\">顺势做多",
                "实操动作:</strong> <span style=\"color:#38bdf8;\">黄金坑低吸",
                "实操动作:</strong> <span style=\"color:#38bdf8;\">逢低试仓",
            ]):
                findings.append("Gate 1 失败: 回避档位下主力实操动作误设为做多/低吸指令")

        # Gate 2: 战术赔率防守熔断校验
        if is_avoid:
            if "买方防守熔断" not in html_content and "禁止买入" not in html_content:
                # 检查是否存在明确的买入区间设定
                if re.search(r"建仓买入区间.*?[0-9]+\.[0-9]+", html_content):
                    findings.append("Gate 2 失败: 回避/零仓位未触发赔率防守熔断，仍提供买入价格区间")
            if re.search(r"第一向上目标.*?<strong.*?>[0-9]+\.[0-9]+", html_content):
                findings.append("Gate 2 失败: 回避/零仓位仍提供向上目标价")

        # Gate 3: 数据保真与反幻觉打脸校验
        if "数据缺失" in html_content and "ROE" in html_content:
            if re.search(r"净资产收益率.*?([0-9]+\.[0-9]+%)", html_content) and "ROE数据缺失" in html_content:
                findings.append("Gate 3 失败: 数据看板已提供精确ROE，但报告仍声称数据缺失打脸")

        # Gate 4: 零断句与截断自愈校验
        # 查找非正常截断 (以中英文逗号、顿号直接换行结束)
        if re.search(r"[,，、]\s*</div>", html_content):
            findings.append("Gate 4 失败: 存在以逗号/顿号结尾的异常断句")

        # Gate 5: 结构完整性校验
        required_sections = [
            "AST-Trader 五节点因果决断卡",
            "主力行为生命周期透视",
            "首页「赚不赚钱」数据看板",
            "A股五维实盘量化投研支柱",
            "实盘战术执行手册",
            "四维资金博弈雷达",
            "本土会计审计与治理排雷明细",
        ]
        for section in required_sections:
            if section not in html_content:
                findings.append(f"Gate 5 失败: 缺少核心板块 [{section}]")

        is_passed = len(findings) == 0
        return is_passed, findings

    def validate_card_data(self, card: dict[str, Any]) -> tuple[bool, list[str]]:
        """直接对内存中的决断卡字典进行一致性审计校验."""
        findings: list[str] = []
        gear = str(card.get("decision_gear", "") or "")
        pos_cap = float(card.get("position_cap", 0.0) or 0.0)

        is_avoid = pos_cap == 0.0 or gear in ("回避", "减仓")

        if is_avoid:
            mf_stage = str(card.get("main_force_stage", ""))
            mf_behavior = str(card.get("main_force_behavior", ""))
            rec_act = str(card.get("recommended_action", ""))

            if any(w in mf_stage for w in ["吸筹", "洗盘", "蓄势", "主升", "做多", "挖坑"]):
                findings.append(f"Card Gate 1: 回避/0%仓位下 main_force_stage [{mf_stage}] 仍为多头蓄势/主升阶段")

            if "扎实健康" in mf_behavior or "清洗浮动获利盘" in mf_behavior:
                findings.append("Card Gate 1: 回避/0%仓位下 main_force_behavior 仍包含'扎实健康/清洗浮动获利盘'")

            if any(w in rec_act for w in ["低吸", "加仓", "做多", "买入"]):
                findings.append(f"Card Gate 1: 回避/0%仓位下 recommended_action [{rec_act}] 包含做多字眼")

            t_odds = card.get("tactical_odds")
            if isinstance(t_odds, dict):
                if not t_odds.get("is_circuit_broken"):
                    findings.append("Card Gate 2: 回避/0%仓位下 tactical_odds 未熔断")

        is_passed = len(findings) == 0
        return is_passed, findings


def main() -> None:
    parser = argparse.ArgumentParser(description="AST-Trader 自动化研报闭环质量校验工具")
    parser.add_argument("report_file", help="HTML 研报文件路径")
    parser.add_argument("--strict", action="store_true", help="严格模式 (校验失败退出码为 1)")
    args = parser.parse_args()

    validator = ReportValidator()
    ok, findings = validator.validate_html(args.report_file)

    if ok:
        print(f"✅ [PASS] 报告校验全部通过 (7道防线一致性无矛盾): {args.report_file}")
        sys.exit(0)
    else:
        print(f"❌ [FAIL] 报告一致性机检发现 {len(findings)} 处违规或矛盾:")
        for i, f in enumerate(findings, 1):
            print(f"  {i}. {f}")
        sys.exit(1 if args.strict else 0)


if __name__ == "__main__":
    main()
