"""nodes —— 判断链五节点的 AI 调度（对齐上游 `scripts/node_graph.py` 的波次）。

## 为什么要单独一层

上游把五个节点交给五个 LLM 子代理，由 `node_graph.py` 按**依赖图**算波次：

    Phase 3  第一波  ①质地 ∥ ③赔率
             第二波  ④路径 ∥ ②状态     （两者的分母/第④关都要引用③）
             第三波  ⑤决策              （吃前四个 verdict）

本项目没有 agent 宿主，改为**函数按波次串行调用**，但保留同样的依赖顺序
与「跨节点只引用、不重新推导」的硬边界。

## 与旧 if-else 判定的关系

旧实现用一串 `if / elif` 把 verdict 硬切出来（如 `if x>0.6: "好" else: "部分好"`）。
这种方式的问题不是阈值对不对，而是**取值被写死成那几条分支** ——
市场换了形态，代码里没有对应分支，就只能落到 `else` 里凑一个。

现在 verdict 由模型读判据手册得出，判据是**可调的业务资产**（`prompts/node-*.md`），
不是代码里的常量。规则版仍保留为 **fallback**：

    · AI 关闭 / 调用失败 / verdict 越界 / 无证据 → 该节点返回 None
    · 调用方原样使用规则判定 —— 保证 AI 关闭时输出与现状**逐字一致**
"""
from __future__ import annotations

import logging
import time
from typing import Any

import config

from core.ai_enrichment import AIEnrichment, NODE_VERDICT_DOMAIN

from . import enrich

logger = logging.getLogger("ast_trader.ai.nodes")

__all__ = ["NODE_MODULES", "run_nodes", "verdict_of"]

#: 五个判断链节点模块
NODE_MODULES: tuple[str, ...] = (
    "node_quality", "node_state", "node_odds", "node_path", "node_decision",
)

#: 上游 Phase 3 的波次划分（依赖图算出来的顺序，不手写）
WAVES: tuple[tuple[str, ...], ...] = (
    ("node_quality", "node_odds"),      # 第一波：①③ 互不依赖
    ("node_state", "node_path"),        # 第二波：②④ 都要引用③
    ("node_decision",),                 # 第三波：⑤ 吃前四个
)


def verdict_of(results: dict[str, AIEnrichment | None], module: str) -> str | None:
    """取某节点的 verdict；不可用（None / 弃权）时返回 None。"""
    r = results.get(module)
    if r is None or r.abstained or not r.verdict:
        return None
    return r.verdict


def run_nodes(
    context: dict[str, Any],
    *,
    budget: float | None = None,
) -> dict[str, AIEnrichment | None]:
    """按波次跑判断链五个节点，返回 `{module: AIEnrichment | None}`。

    ★ 跨节点只引用：`node_state` / `node_path` 的上下文会注入③的 verdict，
      `node_decision` 会注入前四个的 verdict —— 模型**引用**它们，不重新推导。

    ★ 预算熔断：单只标的的 AI 开销必须可控，超预算的剩余节点一律返回
      None（弃权回退规则判定），避免 `analyze` 从秒级退化到分钟级。
    """
    if not config.AI_ENABLED:
        return {m: None for m in NODE_MODULES}

    limit = budget if budget is not None else config.AI_NODE_TOTAL_BUDGET
    started = time.monotonic()
    results: dict[str, AIEnrichment | None] = {}
    ctx = dict(context)

    for wave in WAVES:
        # 波次开始前注入上游节点的 verdict（一处权威：下游只引用）
        if "node_odds" in results:
            ctx["odds_verdict"] = verdict_of(results, "node_odds") or "（③赔率未核验）"
        if "node_state" in results:
            ctx["state_verdict"] = verdict_of(results, "node_state") or "（②状态未核验）"
        if "node_path" in results:
            ctx["path_verdict"] = verdict_of(results, "node_path") or "（④路径未核验）"
        if "node_quality" in results:
            ctx["quality_verdict"] = verdict_of(results, "node_quality") or "（①质地未核验）"

        # ★ 一处权威的下游传递：⑤必须**引用**②④的独有产出，不许自己新编。
        #   临界点只在②产、证伪清单只在④产 —— 从 analysis 里取出来喂给⑤。
        st = results.get("node_state")
        if st is not None and st.analysis:
            ctx["critical_wait"] = str(
                st.analysis.get("critical_wait") or "（②未给出临界点）"
            )
        pa = results.get("node_path")
        if pa is not None and pa.analysis:
            ctx["falsification"] = str(
                pa.analysis.get("falsification") or "（④未给出证伪清单）"
            )

        for m in wave:
            if time.monotonic() - started >= limit:
                logger.warning("AI 节点总预算 %.1fs 用尽，剩余节点弃权: %s", limit, m)
                results[m] = None
                continue
            # ★ 节点是**分析**而非填表：给足输出空间承载推导过程
            results[m] = enrich(
                m, ctx,
                allowed_verdicts=NODE_VERDICT_DOMAIN[m],
                max_tokens=config.AI_MAX_TOKENS_NODE,
                timeout=config.AI_TIMEOUT_NODE,
            )
            v = verdict_of(results, m)
            if v:
                logger.info("AI 节点[%s] verdict = %s", m, v)
            else:
                logger.info("AI 节点[%s] 弃权/不可用，回退规则判定", m)

    return results
