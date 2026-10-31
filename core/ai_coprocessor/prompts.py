"""prompts —— 提示词加载与渲染。

借鉴上游 `agents/*.md`：上游把判断链手册交给 LLM 子代理读，
本项目没有 agent 宿主，改为**把同一套判据渲染进 prompt 由函数调用**。

★ 提示词放在独立的 `.md` 文件里，而不是塞进 Python 字符串：
判据是要反复推敲的业务资产，和业务代码混在一起就没人敢改了。
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from core.ai_enrichment import MODULES

logger = logging.getLogger("ast_trader.ai.prompts")

PROMPT_DIR = Path(__file__).parent / "prompts"
MISSING = "（未提供）"

__all__ = ["system_prompt", "render", "PROMPT_DIR"]


def _read(name: str) -> str:
    p = PROMPT_DIR / name
    if not p.is_file():
        raise FileNotFoundError(f"缺少提示词文件: {p}")
    return p.read_text(encoding="utf-8")


#: 判断链五节点 —— 它们需要**另一套**系统提示词（见函数文档）。
NODE_SYSTEM_MODULES: frozenset[str] = frozenset(
    m for m in MODULES if m.startswith("node_")
)


def system_prompt(module: str | None = None) -> str:
    """系统提示词。

    ★ 为什么节点要用**另一份**（`_system_node.md`）：

    旧模块（moat / catalyst / …）的 `_system.md` 写的是
    「你没有升级权限、只能加风险、输出 judgment + nominations」—— 那是把 AI
    当**否决者**。而判断链五节点要让 AI 当**分析师**：产出 `verdict` 与推导
    `analysis`。若沿用旧提示词，模型就会照旧格式输出（实测返回
    `"module": "node-odds"`、无 `verdict`、无 `analysis`），节点必然全部弃权
    回退规则 —— 表面接上了，实际仍是规则在判定。
    """
    if module and module in NODE_SYSTEM_MODULES:
        return _read("_system_node.md")
    return _read("_system.md")


class _Defaults(dict):
    """`str.format` 的缺失键兜底 —— 上下文少给一个字段不该让整次调用崩掉。"""

    def __missing__(self, key: str) -> str:
        return MISSING


def render(module: str, **ctx: Any) -> str:
    """渲染指定模块的提示词。未知模块或文件缺失直接抛错（早失败好过静默）。

    ★ 约定：**文件名 = 模块名**（如 `mainforce.md` 对应模块 `mainforce`）。
      判断链五节点同理用下划线（`node_quality.md`）—— 上游仓库里叫
      `references/node-quality.md`，但本项目以「文件名即模块名」为准，
      避免多一层映射带来的不一致。
    """
    if module not in MODULES:
        raise ValueError(f"未知模块: {module}（可用: {', '.join(MODULES)}）")
    template = _read(f"{module}.md")
    safe = {k: ("" if v is None else v) for k, v in ctx.items()}
    return template.format_map(_Defaults(safe))
