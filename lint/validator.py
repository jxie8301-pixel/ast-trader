"""Lint gating and verification rules for AST-Trader decision cards.
Strictly aligned with Ashare-researchreport quality gate specifications.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any

import config
from core.red_flags import LEVEL_FATAL

LEVEL_FAIL = "fail"
LEVEL_WARN = "warn"

LEVELS = (LEVEL_FATAL, "🟠", "🟡", "⚪", "🟢")

logger = logging.getLogger("ast_trader.lint")


@dataclass(frozen=True)
class Finding:
    """质量门控检查发现项。"""
    rule: str
    level: str
    message: str

    def __str__(self) -> str:
        return self.message if self.level == LEVEL_FAIL else f"[WARN] {self.message}"


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

    VERDICT_DOMAINS: dict[str, tuple[str, ...]] = {
        "quality_verdict": (
            "好",
            "部分好",
            "不好",
            "差",
            "未核验(净利润为负)",
            "未核验(微观缺失)",
            "未核验(制造业模型弃权)",
        ),
        "state_verdict": (
            "↑变好+证据确认",
            "↑变好但仅注意力·未确认",
            "在变好+证据未确认",
            "在变好+证据确认",
            "↑变好(无证据/需再观察)",
            "横盘",
            "↓变差",
            "↓走弱",
            "走弱",
            "未核验(微观缺失)",
        ),
        "odds_verdict": (
            "便宜(有余地)",
            "合理",
            "贵",
            "买完完美未来",
            "已被价格计入",
            "未核验(净利润为负)",
            "未核验(财务缺失)",
            "未核验(微观缺失)",
        ),
        "path_verdict": ("可承受", "高尾险·不可承受", "未核验(微观缺失)"),
    }

    # R11 单点真理越界：❶质地/❷状态 正文严禁出现仓位类表述
    POSITION_LEAK_TERMS = (
        "仓位", "建仓", "持仓", "满仓", "半仓", "加仓", "清仓", "成仓", "底仓",
    )

    def __init__(self) -> None:
        pass

    def _severity(self, rule: str) -> str:
        return config.LINT_RULE_SEVERITY.get(rule, "warn")

    def _finding(self, rule: str, message: str) -> Finding:
        return Finding(rule=rule, level=self._severity(rule), message=message)

    # ---------------------------------------------------------------- R1: 契约校验
    def _check_r1_contract(self, card: dict[str, Any]) -> list[Finding]:
        try:
            from core.schema_validator import SchemaNotFoundError, validate as schema_validate
        except ImportError:
            return []
        try:
            errors = schema_validate(card, "decision_card")
        except SchemaNotFoundError:
            return []
        return [self._finding("R1", f"[R1 契约校验] {e}") for e in errors[:20]]

    # ---------------------------------------------------------------- R2: 红旗闭环
    def _check_r2_red_flag_closure(self, card: dict[str, Any], flags: list[Any]) -> list[Finding]:
        out: list[Finding] = []
        top3 = card.get("top3_risks") or []
        all_flags = card.get("all_flags") or []
        all_titles = {
            f.get("title") if isinstance(f, dict) else getattr(f, "title", "")
            for f in all_flags
        }
        for f in flags or []:
            all_titles.add(getattr(f, "title", ""))

        for item in top3:
            t = item.get("title") if isinstance(item, dict) else getattr(item, "title", "")
            if t and t not in all_titles:
                out.append(self._finding("R2", f"[R2 红旗闭环] Top3 红旗 '{t}' 不在全量红旗清单中！"))

        pillars_text = " ".join([
            str(card.get("pillar_1_quality") or ""),
            str(card.get("pillar_2_state") or ""),
            str(card.get("pillar_3_odds") or ""),
            str(card.get("pillar_4_path") or ""),
        ])

        fatal_items: list[Any] = [f for f in (flags or []) if getattr(f, "level", None) == LEVEL_FATAL]
        for f in all_flags:
            if isinstance(f, dict) and f.get("level") == LEVEL_FATAL:
                fatal_items.append(f)

        for f in fatal_items:
            t = f.get("title") if isinstance(f, dict) else getattr(f, "title", "")
            if t and t not in pillars_text:
                out.append(self._finding("R2", f"[R2 红旗闭环] 🔴 致命红旗 '{t}' 未归家（未在任何支柱正文中出现）！"))

        return out

    # ---------------------------------------------------------------- R3: 单点真理
    def _check_r3_single_truth(self, card: dict[str, Any]) -> list[Finding]:
        out: list[Finding] = []
        p5 = card.get("pillar_5_decision")
        if isinstance(p5, dict):
            g_top = str(card.get("decision_gear") or "")
            g_p5 = str(p5.get("decision_gear") or "")
            if g_top and g_p5 and g_top != g_p5:
                out.append(self._finding("R3", f"[R3 数值单点真理] 顶层行动档位 '{g_top}' 与 ⑤决策行动档位 '{g_p5}' 双写不一致！"))

            inv_top = str(card.get("invalidation_line") or "")
            inv_p5 = str(p5.get("invalidation_line") or "")
            if inv_top and inv_p5 and inv_top != inv_p5:
                out.append(self._finding("R3", f"[R3 数值单点真理] 顶层证伪线 '{inv_top}' 与 ⑤决策证伪线 '{inv_p5}' 双写不一致！"))
        return out

    # ---------------------------------------------------------------- R4': 支柱预算
    def _check_r4_pillar_budget(self, card: dict[str, Any]) -> list[Finding]:
        out: list[Finding] = []
        for k, name in [
            ("pillar_1_quality", "①质地正文"),
            ("pillar_2_state", "②状态正文"),
            ("pillar_3_odds", "③赔率正文"),
            ("pillar_4_path", "④路径正文"),
        ]:
            text = str(card.get(k) or "")
            if len(text) > 3000:
                out.append(self._finding("R4", f"[R4 支柱正文预算] {name} 字符超限 ({len(text)} > 3000)！"))
        return out

    # ---------------------------------------------------------------- R5: 锚自洽
    def _check_r5_anchor_consistency(self, card: dict[str, Any]) -> list[Finding]:
        out: list[Finding] = []
        price = card.get("price")
        odds = str(card.get("odds_verdict") or "")
        anchor = card.get("anchor_range")
        if isinstance(price, (int, float)) and price > 0 and isinstance(anchor, dict):
            high = anchor.get("high")
            h_val = high.get("value") if isinstance(high, dict) else high
            if isinstance(h_val, (int, float)) and h_val > 0:
                if price > h_val and "便宜" in odds:
                    out.append(self._finding("R5", f"[R5 区间锚自洽] 方向矛盾：现价 {price} 高于估值区间上沿 {h_val}，但赔率判定为 '{odds}'！"))
        return out

    # ---------------------------------------------------------------- R10: 判定域合法
    def _check_r10_verdict_domain(self, card: dict[str, Any]) -> list[str]:
        findings: list[str] = []
        for key, domain in self.VERDICT_DOMAINS.items():
            val = card.get(key)
            if val is not None and str(val).strip() != "":
                if str(val) not in domain:
                    findings.append(f"[R10 判定域越界] {key} 取值 '{val}' 不在合法域 {domain} 中！")
        return findings

    # ---------------------------------------------------------------- R11: 单点真理越界
    def _check_r11_single_truth_leak(self, card: dict[str, Any]) -> list[str]:
        findings: list[str] = []
        for k, label in [("pillar_1_quality", "①质地正文"), ("pillar_2_state", "②状态正文")]:
            text = str(card.get(k) or "")
            for term in self.POSITION_LEAK_TERMS:
                if term in text:
                    findings.append(f"[R11 单点真理越界] {label} 出现仓位类表述 '{term}'，仓位信息只能由 ⑤决策节点给出！")
                    break
        return findings

    # ---------------------------------------------------------------- R12: 算术闭包
    def _check_r12_arithmetic_closure(self, card: dict[str, Any]) -> list[str]:
        findings: list[str] = []
        pos_top = card.get("position_cap")
        p5 = card.get("pillar_5_decision")
        if isinstance(pos_top, (int, float)) and isinstance(p5, dict):
            pos_p5 = p5.get("position_cap")
            if isinstance(pos_p5, (int, float)):
                if abs(float(pos_top) - float(pos_p5)) > 1e-4:
                    findings.append(f"[R12 算术闭包] 顶层仓位 ({pos_top}) 与 ⑤决策仓位 ({pos_p5}) 双写不一致！")
        if isinstance(pos_top, (int, float)):
            if float(pos_top) > getattr(config, "MAX_SINGLE_POSITION_EXTREME", 0.30) + 1e-4:
                findings.append(f"[R12 算术闭包] 仓位越界：单票仓位上限 {pos_top*100:.1f}% 超过极端档上限！")
        anchor = card.get("anchor_range")
        if isinstance(anchor, dict):
            low = anchor.get("low", {})
            high = anchor.get("high", {})
            l_val = low.get("value") if isinstance(low, dict) else low
            h_val = high.get("value") if isinstance(high, dict) else high
            if isinstance(l_val, (int, float)) and isinstance(h_val, (int, float)):
                if float(l_val) > float(h_val):
                    findings.append(f"[R12 算术闭包] 区间倒置：估值低端 ({l_val}) 高于高端 ({h_val})！")
        price = card.get("price")
        if price is not None:
            try:
                if float(price) <= 0:
                    findings.append(f"[R12 算术闭包] 现价非正：price = {price}，不可参与运算！")
            except (TypeError, ValueError):
                pass
        return findings

    # ---------------------------------------------------------------- R14: 无过程注释
    def _check_r14_no_process_notes(self, card: dict[str, Any]) -> list[Finding]:
        out: list[Finding] = []
        forbidden = ["待定", "暂定", "TODO", "草案", "待进一步核实", "待确认"]
        for k in ["critical_wait", "decision_title", "decision_gear"]:
            text = str(card.get(k) or "")
            for term in forbidden:
                if term in text:
                    out.append(self._finding("R14", f"[R14 无过程注释] 包含过程态/临时标记 '{term}'！"))
                    break
        return out

    # ---------------------------------------------------------------- R15: 三元组同源
    def _check_r15_triad_source(self, card: dict[str, Any]) -> list[Finding]:
        p5 = card.get("pillar_5_decision")
        if not isinstance(p5, dict):
            return []
        triad = str(p5.get("triad_verdict") or "").strip()
        if not triad:
            return []
        v2 = str(card.get("state_verdict") or "")
        v3 = str(card.get("odds_verdict") or "")
        v4 = str(card.get("path_verdict") or "")
        if not (v2 and v3 and v4):
            return []
        expected = f"[{v2} | {v3} | {v4}]"
        if triad != expected:
            return [self._finding(
                "R15",
                f"[R15 三元组不同源] ⑤ triad '{triad}' 与 ②③④ 判定 "
                f"'{expected}' 不一致，上游改了判定句就要重抄！",
            )]
        return []

    # ---------------------------------------------------------------- R16: 锚引用过期
    def _check_r16_stale_anchor(self, card: dict[str, Any]) -> list[Finding]:
        out: list[Finding] = []
        anchor = card.get("anchor_range")
        if not isinstance(anchor, dict):
            return out
        low = anchor.get("low", {})
        high = anchor.get("high", {})
        l_val = low.get("value") if isinstance(low, dict) else low
        h_val = high.get("value") if isinstance(high, dict) else high
        if isinstance(l_val, (int, float)) and isinstance(h_val, (int, float)):
            anchor_str = f"{float(l_val):.1f}~{float(h_val):.1f}"
            p3_text = str(card.get("pillar_3_odds") or "")
            matches = re.findall(r"(\d+(?:\.\d+)?)\s*~\s*(\d+(?:\.\d+)?)", p3_text)
            for m_low, m_high in matches:
                found_range = f"{float(m_low):.1f}~{float(m_high):.1f}"
                raw_range = f"{m_low}~{m_high}"
                if found_range != anchor_str:
                    out.append(self._finding(
                        "R16",
                        f"[R16 锚引用过期] ③赔率正文出现的价区 '{raw_range}' 与估值锚范围 '{anchor_str}' 不符！",
                    ))
        return out

    # ---------------------------------------------------------------- R18: 红旗台账同步
    def _check_r18_flag_registry(self, card: dict[str, Any]) -> list[Finding]:
        out: list[Finding] = []
        all_flags = card.get("all_flags") or []
        seen_ids: set[str] = set()
        for f in all_flags:
            if isinstance(f, dict):
                fid = f.get("id")
                lvl = f.get("level")
            else:
                fid = getattr(f, "id", None)
                lvl = getattr(f, "level", None)
            if fid:
                if fid in seen_ids:
                    out.append(self._finding("R18", f"[R18 红旗台账同步] 红旗 id '{fid}' 重复出现！"))
                seen_ids.add(fid)
            if lvl and lvl not in LEVELS:
                out.append(self._finding("R18", f"[R18 红旗台账同步] 红旗级别非法：'{lvl}' 不在合规红旗等级中！"))
        return out

    # ---------------------------------------------------------------- R19: 证据引用保真
    def _check_r19_evidence_citation_authenticity(self, card: dict[str, Any]) -> list[Finding]:
        out: list[Finding] = []
        valid_citations = set(card.get("evidence_citations") or [])
        if valid_citations:
            p5 = card.get("pillar_5_decision") or {}
            text_p5 = str(p5.get("core_contradiction", "")) + " " + str(p5.get("action_tactic", ""))
            cited_tags = re.findall(r"\[(?:公告|机构调研|业绩预告|媒体报道|博查研报)[^\]]+\]", text_p5)
            for tag in cited_tags:
                if not any(tag[:12] in v or v[:12] in tag for v in valid_citations):
                    out.append(self._finding(
                        "R19",
                        f"[R19 证据引用未在证据池核验] 正文引用了 '{tag}'，但该条目未在本次检索证据池中定标！",
                    ))
        return out

    def validate_findings(self, decision_card: dict[str, Any], flags: list[Any]) -> list[Finding]:
        """执行全套门控机检，返回带严重度的结构化发现。"""
        findings: list[Finding] = []
        fatal_flags = [f for f in (flags or []) if getattr(f, "level", None) == LEVEL_FATAL]
        gear = str(decision_card.get("decision_gear") or "")
        pos = float(decision_card.get("position_cap", 0.0) or 0.0)

        # ─── R7: 决策字段齐全 + 致命红旗强制封顶 ───
        if fatal_flags and gear != "回避":
            findings.append(Finding(
                rule="R7", level=LEVEL_FAIL,
                message=f"[R7 致命红旗未回避] 存在 {len(fatal_flags)} 条 🔴 致命红旗 "
                        f"({', '.join(getattr(f, 'title', '') for f in fatal_flags[:2])})，"
                        f"但行动档位被写成 '{gear}'，必须强制封顶为 '回避'！",
            ))

        if fatal_flags and pos > 0.0:
            findings.append(Finding(
                rule="R7", level=LEVEL_FAIL,
                message=f"[R7 致命红旗仓位未清零] 存在致命红旗时，单票仓位上限必须为 0.0，实际给出了 {pos*100:.1f}%！",
            ))

        # ─── R8: 越权发声 ───
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
        action_forbidden_terms = [
            "建议买入", "立即买入", "建议建仓", "立即建仓", "开始建仓", "满仓",
            "半仓", "清仓离场", "立即清仓", "逢低加仓", "建议加仓",
        ]
        for node_key, label in nodes_to_check:
            text = str(decision_card.get(node_key, "") or "")
            for term in action_forbidden_terms:
                if term in text:
                    findings.append(Finding(
                        rule="R8", level=LEVEL_FAIL,
                        message=f"[R8 越权发声] {label} 包含行动/买卖指令 '{term}'，违背职责分离原则！",
                    ))
                    break

        # ─── R9: 无记忆性反例 ───
        all_text = " ".join(str(v) for v in decision_card.values())
        is_buy_gear = any(k in gear for k in ["买入", "做多", "核心", "期权仓"])
        for phrase in self.FORBIDDEN_MEMORYLESS_PHRASES:
            if phrase in all_text and is_buy_gear:
                findings.append(Finding(
                    rule="R9", level=LEVEL_FAIL,
                    message=f"[R9 无记忆性反例] 出现禁止的反例推论 '{phrase}'，严禁作为买入依据！",
                ))

        # ─── R13: 证伪清单同源 ───
        inv_line = str(decision_card.get("invalidation_line", "")).strip()
        if not inv_line:
            findings.append(Finding(
                rule="R13", level=LEVEL_FAIL,
                message="[R13 缺失绝对证伪线] 决断卡必须在买入前写死具体退出线！",
            ))

        # ─── R10 / R11 / R12: 既有三条（fail 级）───
        for msg in self._check_r10_verdict_domain(decision_card):
            findings.append(Finding(rule="R10", level=LEVEL_FAIL, message=msg))
        for msg in self._check_r11_single_truth_leak(decision_card):
            findings.append(Finding(rule="R11", level=LEVEL_FAIL, message=msg))
        for msg in self._check_r12_arithmetic_closure(decision_card):
            findings.append(Finding(rule="R12", level=LEVEL_FAIL, message=msg))

        # ─── 新增规则挂载 ───
        findings.extend(self._check_r1_contract(decision_card))
        findings.extend(self._check_r2_red_flag_closure(decision_card, flags))
        findings.extend(self._check_r3_single_truth(decision_card))
        findings.extend(self._check_r4_pillar_budget(decision_card))
        findings.extend(self._check_r5_anchor_consistency(decision_card))
        findings.extend(self._check_r14_no_process_notes(decision_card))
        findings.extend(self._check_r15_triad_source(decision_card))
        findings.extend(self._check_r16_stale_anchor(decision_card))
        findings.extend(self._check_r18_flag_registry(decision_card))
        findings.extend(self._check_r19_evidence_citation_authenticity(decision_card))

        return findings

    def validate(self, decision_card: dict[str, Any], flags: list[Any]) -> tuple[bool, list[str]]:
        """执行全套门控机检。返回 (passed: bool, findings: list[str])。"""
        findings = self.validate_findings(decision_card, flags)
        fail_findings = [f for f in findings if f.level == LEVEL_FAIL]
        passed = len(fail_findings) == 0
        return passed, [str(f) for f in findings]
