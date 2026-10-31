"""provider —— OpenAI 兼容 HTTP 客户端（超时 / 重试 / 异常归一）。

★ 刻意**不引入 openai SDK**：本项目只需要 `/chat/completions` 一个端点，
用标准库 `urllib` 就够，少一个重型依赖就少一个版本地雷。
★ 所有失败一律归一为 `AIUnavailable` —— 调用方只需 catch 一个异常，
且**必须**据此弃权回退，严禁拿异常当"结论不明"继续往下走。
"""
from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from typing import Any

import config

logger = logging.getLogger("ast_trader.ai.provider")

__all__ = ["AIUnavailable", "chat", "chat_json", "extract_json"]


class AIUnavailable(RuntimeError):
    """AI 不可用（未启用 / 无 Key / 超时 / HTTP 错误 / 返回非法）。"""


def _endpoint() -> str:
    base = (config.AI_API_BASE or "").rstrip("/")
    return f"{base}/chat/completions"


def chat(
    prompt: str,
    *,
    system: str = "",
    model: str | None = None,
    timeout: float | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
) -> str:
    """发起一次对话补全，返回**文本内容**。失败抛 `AIUnavailable`。"""
    if not config.AI_ENABLED:
        raise AIUnavailable("AI 未启用（config.AI_ENABLED=False）")
    if not config.AI_API_KEY:
        raise AIUnavailable("未配置 AST_AI_API_KEY")

    messages: list[dict[str, str]] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    payload = {
        "model": model or config.AI_MODEL,
        "messages": messages,
        "temperature": config.AI_TEMPERATURE if temperature is None else temperature,
        "max_tokens": max_tokens or config.AI_MAX_TOKENS,
    }

    req = urllib.request.Request(
        _endpoint(),
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {config.AI_API_KEY}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        # ★ 用 `is not None` 而非 `or`：`timeout=0` 会被 `or` 吞掉而误用默认值。
        with urllib.request.urlopen(
            req, timeout=timeout if timeout is not None else config.AI_TIMEOUT
        ) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise AIUnavailable(f"HTTP {exc.code}: {exc.reason}") from exc
    except urllib.error.URLError as exc:
        raise AIUnavailable(f"网络错误: {exc.reason}") from exc
    except TimeoutError as exc:
        raise AIUnavailable("请求超时") from exc
    except json.JSONDecodeError as exc:
        raise AIUnavailable(f"响应非 JSON: {exc}") from exc
    except Exception as exc:                                # noqa: BLE001
        raise AIUnavailable(f"{type(exc).__name__}: {exc}") from exc

    try:
        return body["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError, TypeError) as exc:
        raise AIUnavailable(f"响应结构非法: {exc}") from exc


def extract_json(raw: str) -> dict[str, Any]:
    """从模型输出里抠出 JSON 对象。

    模型常把 JSON 包在 ```json 代码块里或前后加解释文字，
    这里取**首尾花括号**之间的内容，容错但不猜内容。
    """
    text = (raw or "").strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end <= start:
        raise AIUnavailable("输出中找不到 JSON 对象")
    try:
        return json.loads(text[start:end + 1])
    except json.JSONDecodeError as exc:
        raise AIUnavailable(f"JSON 解析失败: {exc}") from exc


def chat_json(prompt: str, *, system: str = "", retries: int = 1, **kw: Any) -> dict[str, Any]:
    """对话并要求 JSON 输出，直接返回解析后的 dict。

    ★ 为什么要重试：实测上游端点会返回**截断的半截内容**
      （曾有 max_tokens=3000 却只回 110 字符的情况），并非模型没按格式输出。
      单次失败就弃权会让 AI 判定大面积退化成规则判定，故重试一次。
      重试仍失败**照旧抛 `AIUnavailable`** —— 失败即弃权的边界不变。
    """
    last_raw = ""
    for attempt in range(retries + 1):
        last_raw = chat(prompt, system=system, **kw)
        try:
            return extract_json(last_raw)
        except AIUnavailable as exc:
            if attempt >= retries:
                raise
            logger.warning(
                "第 %d 次响应不可解析（%s），重试一次。原文前 80 字: %r",
                attempt + 1, exc, last_raw[:80],
            )
    raise AIUnavailable("响应不可解析")  # pragma: no cover
