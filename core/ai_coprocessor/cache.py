"""cache —— AI 结果持久缓存（按内容哈希）。

**为什么要缓存**：
· 确定性 —— 同一输入必得同一输出，回归测试才能用固定 fixture；
· 成本与延迟 —— 公告语料在两次运行之间通常不变，没必要重复烧 token。

缓存键 = `sha256(module | model | prompt_version | prompt)`，
**prompt 一改键就变**，不会出现"改了提示词却读到旧结论"的静默错误。
"""
from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Any

import config

logger = logging.getLogger("ast_trader.ai.cache")

CACHE_DIR: Path = config.CACHE_DIR / "ai"

__all__ = ["make_key", "get", "put", "CACHE_DIR"]


def make_key(module: str, prompt: str, *, model: str | None = None, version: str = "v1") -> str:
    """生成缓存键。prompt 参与哈希，确保提示词变更后自动失效。"""
    digest = hashlib.sha256(
        "\n".join((module, model or config.AI_MODEL, version, prompt)).encode("utf-8")
    ).hexdigest()
    return f"{module}_{digest[:16]}"


def _path(key: str) -> Path:
    return CACHE_DIR / f"{key}.json"


def get(key: str) -> dict[str, Any] | None:
    """读缓存；不存在或损坏返回 None（损坏当没有，绝不抛给调用方）。"""
    p = _path(key)
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:                                       # noqa: BLE001
        logger.warning("AI 缓存损坏，按未命中处理: %s", p.name)
        return None


def put(key: str, value: dict[str, Any]) -> None:
    """写缓存。写盘失败**不影响主流程**。"""
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        _path(key).write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    except Exception as exc:                                # noqa: BLE001
        logger.warning("AI 缓存写入失败（忽略）: %s", exc)
