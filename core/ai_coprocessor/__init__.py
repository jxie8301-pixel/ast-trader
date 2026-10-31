"""ai_coprocessor —— AI 语义协处理器（判断层）。

**定位**：量化中台算完之后，补齐它算不出来的定性判断。
借鉴上游「脚本算、LLM 写、跨节点只引不推」，但把子代理编排改为函数调用。

**三条硬边界**（实现在 `guard.py`，任何接入方不得绕过）：
1. 只能降级，不能升级；
2. 只能加风险（红旗提名），没有加信心的通道；
3. 失败即弃权，回退规则判定，严禁伪装结论。

**使用前提**：`config.AI_ENABLED` 默认 `False`，需显式开启。
未启用时 `enrich()` 直接返回 `None`，调用方拿到的就是规则判定原值 ——
**保证 AI 关闭时输出与现状逐字一致**。

★ AI 只在 `analyze` 单股路径启用，绝不进 `screen` / Tier1-3
（会破坏全市场 ≤15s 验收）。
"""
from __future__ import annotations

import logging
import time
from typing import Any, Sequence

import config

from core.ai_enrichment import AIEnrichment, MODULES

from . import cache, guard, prompts
from .guard import (
    apply_enrichment,
    apply_text,
    apply_verdict_downgrade_only,   # ★ P0-2：五节点 verdict 级降级单向阀
    nominations_to_dicts,
)
from .provider import AIUnavailable, chat_json

logger = logging.getLogger("ast_trader.ai")

__all__ = [
    "enrich", "enrich_many", "apply_enrichment", "apply_text",
    "apply_verdict_downgrade_only", "nominations_to_dicts",
    "MODULES", "AIUnavailable",
]


def enrich(
    module: str,
    context: dict[str, Any],
    *,
    use_cache: bool = True,
    allowed_verdicts: tuple[str, ...] | None = None,
    max_tokens: int | None = None,
    timeout: float | None = None,
) -> AIEnrichment | None:
    """对单个模块做语义增强。

    `max_tokens` 用于判断链五节点 —— 它们要输出**推导过程**而非单个判定，
    默认 800 token 会把推导截成半截 JSON 导致解析失败。

    返回：
    · `None` —— AI 未启用或调用失败（调用方应原样使用规则判定）；
    · `AIEnrichment(abstained=True)` —— AI 主动/被动弃权，理由见 `reason`；
    · `AIEnrichment(abstained=False)` —— 可用结果，仍须过 `guard.apply_*` 才能写卡。

    ★ 本函数**不修改任何判定**，只产出结论；改写必须由 `guard` 执行。
    """
    if module not in MODULES:
        raise ValueError(f"未知模块: {module}（可用: {', '.join(MODULES)}）")
    if not config.AI_ENABLED:
        return None

    prompt = prompts.render(module, **context)
    key = cache.make_key(module, prompt)

    payload = cache.get(key) if use_cache else None
    if payload is None:
        try:
            payload = chat_json(
                prompt,
                # ★ 按模块选系统提示词：五节点用「分析师」版，旧模块用「否决者」版
                system=prompts.system_prompt(module),
                max_tokens=max_tokens,
                timeout=timeout,
            )
        except AIUnavailable as exc:
            logger.warning("AI[%s] 调用失败，回退规则: %s", module, exc)
            return None
        except Exception as exc:                            # noqa: BLE001
            logger.warning("AI[%s] 未知异常，回退规则: %s", module, exc)
            return None
        if use_cache:
            cache.put(key, payload)

    result = guard.parse_payload(payload, module, allowed_verdicts)
    if result.abstained:
        logger.info("AI[%s] 弃权: %s", module, result.reason)
    return result


def enrich_many(
    context: dict[str, Any],
    modules: Sequence[str] = MODULES,
    *,
    budget: float | None = None,
) -> dict[str, AIEnrichment | None]:
    """按预算并发/有序跑多个模块。

    使用 ThreadPoolExecutor 进行线程级并发请求加速，在总耗时熔断限制内返回所有可用模块结论。
    """
    if not config.AI_ENABLED:
        return {m: None for m in modules}

    limit = budget if budget is not None else config.AI_TOTAL_BUDGET
    started = time.monotonic()
    out: dict[str, AIEnrichment | None] = {}

    import concurrent.futures

    workers = min(4, max(1, len(modules)))
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        future_map = {
            executor.submit(enrich, m, context, timeout=limit): m
            for m in modules
        }
        for future in concurrent.futures.as_completed(future_map):
            m = future_map[future]
            try:
                elapsed = time.monotonic() - started
                if elapsed >= limit:
                    logger.warning("AI 总预算 %.1fs 用尽，模块弃权: %s", limit, m)
                    out[m] = None
                else:
                    out[m] = future.result()
            except Exception as exc:
                logger.warning("AI[%s] 并发执行异常: %s", m, exc)
                out[m] = None

    # 保持入参 modules 的顺序
    return {m: out.get(m) for m in modules}
