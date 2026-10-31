"""guard —— 降级守卫与失败闭环。这是判断层**最重要**的文件。

`apply_enrichment` 是整个 AI 接入的安全阀：它把「AI 说了什么」翻译成
「系统允许改到什么程度」。任何模块要接 AI，都必须过这里，不得直接把
AI 输出写进决断卡。
"""
from __future__ import annotations

import logging
from typing import Any, Iterable, Sequence

import config

from core.ai_enrichment import (
    AIEnrichment,
    EvidenceRef,
    RedFlagNomination,
    abstain,
)

logger = logging.getLogger("ast_trader.ai.guard")

__all__ = [
    "JUDGMENT_ORDER", "rank", "is_downgrade",
    "VERDICT_ORDER", "verdict_rank", "apply_verdict_downgrade_only",
    "apply_enrichment", "apply_text", "parse_payload", "nominations_to_dicts",
]

#: 判定由优到劣的序。数字越大越差。
JUDGMENT_ORDER: dict[str, int] = {"✓": 0, "⚠️": 1, "✗": 2}

#: 判断链五节点 verdict 的「由优到劣」序（数字越大越差）。取值与
#: `core.ai_enrichment.NODE_VERDICT_DOMAIN` 严格一一对应。
#:
#: ★ 20261029 审计 P0-2：此前四个节点（state/odds/path/decision）的 AI verdict 是
#:   **裸覆写**（``verdict = _nv``）—— 既没有方向约束，也不联动重算仓位。真实产物
#:   reports/002273_SZ_20261029.html 因此出现「档位: 期权仓(小)」+「建议仓位: 0%」
#:   + 顶部标签「🔴 回避 / 空仓」三者互相矛盾的**指令冲突**：呈现层给实盘执行者的
#:   不是结论而是冲突。pillar1 早已接 `apply_enrichment` 单向阀，其余节点却没有
#:   —— 两条路径风控口径不一致。这里把"AI 只能降级"的纪律推广到节点取值域。
VERDICT_ORDER: dict[str, dict[str, int]] = {
    "node_quality":  {"好": 0, "部分好": 1, "不好": 2},
    "node_state":    {"↑变好+证据确认": 0, "↑变好但仅注意力·未确认": 1, "横盘": 2, "↓变差": 3},
    "node_odds":     {"便宜(有余地)": 0, "合理": 1, "已被价格计入": 2, "买完完美未来": 3},
    "node_path":     {"可承受": 0, "高尾险·不可承受": 1},
    "node_decision": {
        "核心仓": 0, "期权仓(小)": 1, "等证据临界(观察)": 2, "观察": 2,
        "不追高(贵但优质)": 3, "减仓": 4, "回避": 5,
    },
}

#: 文本型结论的最大长度，防止模型长篇大论挤爆决断卡
MAX_TEXT_LEN = 300


def rank(judgment: str | None) -> int | None:
    """取判定的序值；不在三态域内返回 `None`（不可比较）。"""
    if judgment is None:
        return None
    return JUDGMENT_ORDER.get(str(judgment).strip())


def is_downgrade(rule_judgment: str, ai_judgment: str | None) -> bool:
    """AI 判定是否构成**降级**（变差）。升级一律返回 False。"""
    r_rule, r_ai = rank(rule_judgment), rank(ai_judgment)
    if r_rule is None or r_ai is None:
        return False
    return r_ai > r_rule


def apply_enrichment(rule_judgment: str, ai: AIEnrichment | None) -> str:
    """降级守卫：AI 只能把判定向**劣**迁移，禁止反向升级。

    允许：✓ → ⚠️、✓ → ✗、⚠️ → ✗
    禁止：✗ → ⚠️、⚠️ → ✓、✗ → ✓

    ★ 以下情况一律**原样返回规则判定**（即弃权回退）：
      · `ai` 为 None（未启用 / 调用失败）
      · `ai.abstained`（AI 主动弃权）
      · `ai.evidence` 为空（无引用即弃权 —— 这是防幻觉的核心闸门）
      · AI 判定不在三态域内（无法比较序值）

    规则判定是唯一可信基线 —— 它由量化中台算出，可复现、可测试。
    """
    if ai is None:
        return rule_judgment
    if ai.abstained:
        logger.info("AI[%s] 弃权，回退规则判定: %s", ai.module, ai.reason)
        return rule_judgment
    if not ai.evidence:
        logger.warning("AI[%s] 无证据引用，按弃权处理", ai.module)
        return rule_judgment
    if ai.judgment is None:
        return rule_judgment

    if is_downgrade(rule_judgment, ai.judgment):
        logger.info(
            "AI[%s] 降级判定: %s → %s（证据 %d 条）",
            ai.module, rule_judgment, ai.judgment, len(ai.evidence),
        )
        return ai.judgment

    if rank(ai.judgment) is not None and rank(rule_judgment) is not None \
            and rank(ai.judgment) < rank(rule_judgment):
        logger.warning(
            "AI[%s] 试图把判定从 %s 升级到 %s —— 已拦截（只允许降级）",
            ai.module, rule_judgment, ai.judgment,
        )
    return rule_judgment


def verdict_rank(module: str, verdict: str | None) -> int | None:
    """取节点 verdict 的序值；不在该节点取值域内返回 `None`（不可比较 → 弃权）。

    ★ 「不可比较」是**常态**而非异常：规则侧会产出取值域外的判定（如路径支柱的
      「未核验(微观缺失)」），此时任何 AI verdict 都无法与它比较序值，必须回退规则。
    """
    if verdict is None:
        return None
    return VERDICT_ORDER.get(module, {}).get(str(verdict).strip())


def apply_verdict_downgrade_only(
    rule_verdict: str,
    ai: AIEnrichment | None,
    module: str,
) -> str:
    """节点 verdict 级降级单向阀：AI 只能把判定向**劣**迁移，禁止升级。

    与 `apply_enrichment`（三态版）同源同理，但作用在**节点取值域**上：

    ★ 以下情况一律回退规则判定（弃权）：
      · `ai` 为 None（未启用 / 调用失败）
      · `ai.abstained`（AI 主动弃权）
      · `ai.evidence` 为空（无引用即弃权 —— 防幻觉核心闸门）
      · AI verdict 与规则 verdict 任一不在取值域内（无法比较序值）

    ★ AI verdict 更劣 → 采纳（降级）；更优 → 拦截并告警（升级一律禁止）。

    规则判定是唯一可信基线 —— 它由量化中台算出，可复现、可测试。
    """
    if ai is None:
        return rule_verdict
    if ai.abstained:
        logger.info("AI[%s] 弃权，回退规则判定: %s", ai.module, ai.reason)
        return rule_verdict
    if not ai.evidence:
        logger.warning("AI[%s] 无证据引用，按弃权处理", ai.module)
        return rule_verdict

    ai_verdict = getattr(ai, "verdict", None)
    if not ai_verdict:
        return rule_verdict

    r_rule = verdict_rank(module, rule_verdict)
    r_ai = verdict_rank(module, ai_verdict)
    if r_rule is None or r_ai is None:
        logger.warning(
            "AI[%s] verdict %r 与规则判定 %r 无法比较序值（至少一个不在取值域内）→ 回退规则判定",
            module, ai_verdict, rule_verdict,
        )
        return rule_verdict

    if r_ai > r_rule:
        logger.info(
            "AI[%s] 降级判定: %s → %s（证据 %d 条）",
            module, rule_verdict, ai_verdict, len(ai.evidence),
        )
        return str(ai_verdict)

    if r_ai < r_rule:
        logger.warning(
            "AI[%s] 试图把判定从 %s 升级到 %s —— 已拦截（只允许降级）",
            module, rule_verdict, ai_verdict,
        )
    return rule_verdict


def apply_text(rule_text: str, ai: AIEnrichment | None, *, max_len: int = MAX_TEXT_LEN) -> str:
    """文本型结论（如「该等什么」催化临界点）的守卫。

    与 `apply_enrichment` 的差别：文本没有序值可比，无法判降级方向。
    因此这里的闸门只有两条：**必须未弃权 + 必须有证据**，
    满足则整体替换，否则原样返回规则文案。
    """
    if ai is None or not ai.usable:
        return rule_text
    text = (ai.judgment or "").strip()
    if not text:
        return rule_text
    if len(text) > max_len:
        text = text[:max_len].rstrip() + "…"
    return text


def parse_payload(
    payload: Any,
    module: str,
    allowed_verdicts: tuple[str, ...] | None = None,
) -> AIEnrichment:
    """把模型返回的 dict 解析成 `AIEnrichment`，**失败即弃权**。

    这是防幻觉的最后一道机检：
    · 过 `core/schemas/ai_enrichment.schema.json`；
    · `allowed_verdicts` 给出时，`verdict` **越界即弃权**；
    · 未弃权却无证据 → 弃权（无引用即弃权）；
    · 任何异常 → 弃权，**绝不返回半成品**。

    ★ `allowed_verdicts` 是判断链五节点的取值域闸门（对齐上游 §4.3）：
      模型只能取枚举值，自造中间档一律按弃权回退规则判定。
    """
    from core.schema_validator import validate

    if not isinstance(payload, dict):
        return abstain(module, f"输出不是对象: {type(payload).__name__}")

    try:
        errors = validate(payload, "ai_enrichment")
    except Exception as exc:                                # noqa: BLE001
        return abstain(module, f"契约校验异常: {type(exc).__name__}: {exc}")
    if errors:
        return abstain(module, f"契约校验未通过: {errors[0]}")

    if payload.get("abstained"):
        return abstain(module, str(payload.get("reason") or "AI 主动弃权"))

    evidence: list[EvidenceRef] = []
    for e in payload.get("evidence") or []:
        if not isinstance(e, dict):
            continue
        quote = str(e.get("quote") or "").strip()
        source = str(e.get("source") or "").strip()
        if not quote or not source:
            continue
        page = e.get("page")
        evidence.append(EvidenceRef(
            source=source,
            quote=quote[:2000],
            url=str(e.get("url") or ""),
            page=int(page) if isinstance(page, int) else None,
        ))
    if not evidence:
        return abstain(module, "无有效证据引用（无引用即弃权）")

    # 级别越靠前越严重；AI 提名封顶由 config 控制（默认 🟠）
    severity_order = ("🔴", "🟠", "🟡")
    cap = str(getattr(config, "AI_MAX_NOMINATION_LEVEL", "🟠"))
    cap_rank = severity_order.index(cap) if cap in severity_order else 1

    nominations: list[RedFlagNomination] = []
    for n in payload.get("nominations") or []:
        if not isinstance(n, dict):
            continue
        try:
            level = str(n.get("level") or "🟡")
            if level in severity_order and severity_order.index(level) < cap_rank:
                # ★ 比封顶更严重 → 压回封顶级，AI 不得直接触发致命封顶
                level = cap
            nominations.append(RedFlagNomination(
                id=str(n.get("id") or f"nomination-{module}-{len(nominations)}"),
                level=level,
                title=str(n.get("title") or ""),
                evidence=str(n.get("evidence") or ""),
                node=str(n.get("node") or "quality"),
                source="nomination",
            ))
        except Exception:                                   # noqa: BLE001
            continue
    # 标题为空的提名没有意义，直接丢弃
    nominations = [n for n in nominations if n.title.strip()]

    # ★★ 节点判定取值域闸门：越界即弃权，绝不把自造值当结论
    verdict_s: str | None = None
    if allowed_verdicts:
        raw_v = payload.get("verdict")
        verdict_s = str(raw_v).strip() if raw_v else None
        if verdict_s not in allowed_verdicts:
            return abstain(
                module,
                f"verdict 越界（须属于 {list(allowed_verdicts)}）: {verdict_s!r}",
            )

    # ★ 节点分析产物：模型自己推导的过程（估值推导 / 子判定 / 左尾 / 证伪 …）。
    #   代码只做容器，**不解释内容** —— 判据在手册里，结构由手册约定。
    raw_analysis = payload.get("analysis")
    analysis_d: dict[str, Any] = (
        dict(raw_analysis) if isinstance(raw_analysis, dict) else {}
    )

    judgment = payload.get("judgment")
    conf = payload.get("confidence")
    return AIEnrichment(
        module=module,
        judgment=str(judgment).strip() if judgment else None,
        verdict=verdict_s,
        analysis=analysis_d,
        evidence=tuple(evidence),
        nominations=tuple(nominations),
        abstained=False,
        confidence=float(conf) if isinstance(conf, (int, float)) else None,
    )


def nominations_to_dicts(enrichments: Sequence[AIEnrichment | None] | Iterable[AIEnrichment | None]) -> list[dict[str, Any]]:
    """汇总多个模块的红旗提名，供 red_flags 与脚本红旗同池合并。

    ★ 这是 AI 影响结论的**唯一**通道 —— 只能加风险。
    """
    out: list[dict[str, Any]] = []
    for e in enrichments:
        if e is None:
            continue
        out.extend(n.to_dict() for n in e.nominations)
    return out


def nominations_to_flags(ai_map: dict[str, Any]) -> list[Any]:
    """把多个模块的 AI 提名转成 `RedFlagItem`，供红旗池合并（单向阀）。

    ★ 级别已在 `parse_payload` 按 `config.AI_MAX_NOMINATION_LEVEL` 封顶，
      因此 AI 永远无法直接触发 🔴 致命封顶与清零仓位 —— 最严重的后果
      仍由脚本红旗掌握。

    延迟 import `core.red_flags`：本模块被 `ai_coprocessor` 包初始化时即加载，
    不该因此把红旗层拉进依赖图。
    """
    from core.red_flags import RedFlagItem

    # ★ 封顶在这里**再拦一次**：parse_payload 已经压过，但那道只覆盖「模型返回」
    #   这条路径。任何绕过解析直接构造 AIEnrichment 的调用点都不得突破上限。
    severity_order = ("🔴", "🟠", "🟡")
    cap = str(getattr(config, "AI_MAX_NOMINATION_LEVEL", "🟠"))
    cap_rank = severity_order.index(cap) if cap in severity_order else 1

    flags: list[Any] = []
    for n in nominations_to_dicts(ai_map.values()):
        try:
            level = n.get("level") or "🟡"
            if level in severity_order and severity_order.index(level) < cap_rank:
                level = cap
            flags.append(RedFlagItem(
                id=str(n["id"]),
                framework="AI 语义提名",
                level=level,
                title=str(n["title"]),
                value=None,
                threshold="—",
                evidence=str(n.get("evidence") or ""),
                node=(n.get("node") if n.get("node") in ("quality", "state", "odds", "path") else "quality"),
            ))
        except Exception as exc:                            # noqa: BLE001
            logger.warning("AI 提名转红旗失败（跳过）: %s", exc)
    return flags
