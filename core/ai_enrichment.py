"""ai_enrichment —— AI 语义增强的数据结构。

**三条硬边界**（贯穿整个判断层，任何模块不得绕过）：

1. **AI 只能降级，不能升级**
   判定只允许从优向劣迁移（✓ → ⚠️ → ✗），禁止反向。
   理由：`quality_verdict` 直接驱动仓位，AI 幻觉出一个护城河 ✓ 的代价是
   **真金白银**；而漏掉一个升级最多是错过机会。

2. **AI 只能加风险，不能加信心**
   唯一影响通道是 `nominations`（红旗提名），
   与脚本红旗同池排序。**没有任何字段能表达"这只票更好"**。

3. **AI 失败即弃权**
   超时 / 校验失败 / 无证据 → 返回 `None` 或 `abstained=True`，
   由调用方回退到现有规则判定，**严禁**输出"中性""无法判断"这类伪装结论
   （遵守 NFR-02：缺失置 None，不伪装成有效信号）。

★ 与上游的差别：上游的写手是 LLM 子代理，直接产出 markdown 正文；
本项目是 Python 库，AI 是被调函数，因此输出是**结构化 dataclass**，
可被 `core/schemas/ai_enrichment.schema.json` 机检。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

__all__ = ["EvidenceRef", "RedFlagNomination", "AIEnrichment", "MODULES"]

#: 接入模块（与 `ai_enrichment.schema.json` 的 enum 严格一致）
#: ★ `mainforce` 是唯一做**自洽性校验**的模块：其余模块判断"标的好不好"，
#:   它判断"脚本给出的阶段定性是否与当日微观证据自相矛盾"。
#: ★ `node-*` 五个模块是**判断链的五个节点本身**（对应上游 agents/ 的四个节点
#:   写手 + decision-writer）：五支柱的 verdict 由它们产出，不再由 if-else 硬切。
MODULES = (
    "moat", "catalyst", "theme_purity", "governance", "tactic", "mainforce",
    "node_quality", "node_state", "node_odds", "node_path", "node_decision",
)

#: 各节点模块的 verdict 取值域（**越界即弃权**，系统回退规则判定）。
#: 对齐上游 `references/judgment-chain.md` §1.3 —— 只能取枚举值，禁止自造中间档。
NODE_VERDICT_DOMAIN: dict[str, tuple[str, ...]] = {
    "node_quality":  ("好", "部分好", "不好"),
    "node_state":    ("↑变好+证据确认", "↑变好但仅注意力·未确认", "横盘", "↓变差"),
    "node_odds":     ("便宜(有余地)", "合理", "已被价格计入", "买完完美未来"),
    "node_path":     ("可承受", "高尾险·不可承受"),
    "node_decision": (
        "核心仓", "期权仓(小)", "等证据临界(观察)",
        "不追高(贵但优质)", "减仓", "回避",
    ),
}


@dataclass(frozen=True)
class EvidenceRef:
    """证据引用。AI 结论必须绑定可核验证据，**无引用即弃权**。"""

    source: str                 # announcement | metrics | news | report | filing
    quote: str                  # 原文片段；★ 必须是原文，不是转述
    url: str = ""               # 公告 PDF 原始链接
    page: int | None = None     # PDF 物理页码
    title: str = ""
    issue_date: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "quote": self.quote,
            "url": self.url or None,
            "page": self.page,
        }


@dataclass(frozen=True)
class RedFlagNomination:
    """写手提名的红旗 —— AI 影响结论的**唯一**通道（单向阀）。"""

    id: str
    level: str                  # 🔴 | 🟠 | 🟡
    title: str
    evidence: str
    node: str = "quality"       # quality | state | odds | path
    source: str = "nomination"  # 恒为 nomination，与脚本红旗区分

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "level": self.level,
            "title": self.title,
            "evidence": self.evidence,
            "node": self.node,
            "source": self.source,
        }


@dataclass(frozen=True)
class AIEnrichment:
    """AI 语义增强结果。任一环节失败即 `abstained=True`（fail-closed）。"""

    module: str
    judgment: str | None = None
    #: 节点判定（判断链五节点专用）。取值受 `NODE_VERDICT_DOMAIN` 约束，
    #: **越界即弃权** —— 绝不把枚举外的自造值当结论（上游：禁止自造中间档）。
    verdict: str | None = None
    #: ★ 节点的**分析产物**（推导过程，不是结论）。
    #: 判断链五节点要求模型**自己分析**（读数据、选方法、做推导），
    #: 而不是从枚举里挑一个。推导过程落在这里，供脚本做算术闭合与一致性机检。
    #: 字段由各节点判据手册约定（derivation / sub_verdicts / critical_wait /
    #: left_tail_list / falsification / cap_check / action_detail …），
    #: **不写死在代码里** —— 判据是业务资产，代码只做容器与校验。
    analysis: dict[str, Any] = field(default_factory=dict)
    evidence: tuple[EvidenceRef, ...] = ()
    nominations: tuple[RedFlagNomination, ...] = ()
    abstained: bool = False
    reason: str = ""
    confidence: float | None = None     # 仅供日志观测，不参与任何计算

    @property
    def usable(self) -> bool:
        """可用于改写判定：未弃权 **且** 有证据。"""
        return not self.abstained and bool(self.evidence)

    def to_dict(self) -> dict[str, Any]:
        return {
            "module": self.module,
            "judgment": self.judgment,
            "verdict": self.verdict,
            "analysis": self.analysis,
            "evidence": [e.to_dict() for e in self.evidence],
            "nominations": [n.to_dict() for n in self.nominations],
            "abstained": self.abstained,
            "reason": self.reason,
            "confidence": self.confidence,
        }


def abstain(module: str, reason: str) -> AIEnrichment:
    """构造一个弃权结果。所有失败路径都必须走这里，禁止返回半成品。"""
    return AIEnrichment(module=module, abstained=True, reason=reason)
