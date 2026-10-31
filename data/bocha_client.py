"""Bocha AI Search Client (博查 AI 搜索引擎客户端).

专为大模型与 RAG 打造的产业与财经 AI 语义检索增强接口。
· 当未配置 BOCHA_API_KEY 时静默降级（返回空列表），绝不阻断单股分析主干流水线；
· 当配置了 API Key 时，支持检索全网券商深度研报、产业供应链跟踪与纪要。
"""
from __future__ import annotations

import logging
from typing import Any

import config
import requests

logger = logging.getLogger("ast_trader.data.bocha")


def search_bocha(
    query: str,
    count: int = 5,
    freshness: str = "oneYear",
    timeout: float = 10.0,
) -> list[dict[str, Any]]:
    """调用博查 Web Search API 进行金融产业语义搜索。

    返回结构:
    [
        {
            "title": str,
            "url": str,
            "snippet": str,
            "date": str,
        },
        ...
    ]
    """
    if not config.BOCHA_ENABLED or not config.BOCHA_API_KEY:
        return []

    url = f"{config.BOCHA_API_BASE.rstrip('/')}/web-search"
    headers = {
        "Authorization": f"Bearer {config.BOCHA_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "query": query,
        "freshness": freshness,
        "summary": True,
        "count": min(max(count, 1), 10),
    }

    try:
        r = requests.post(url, json=payload, headers=headers, timeout=timeout)
        if r.status_code == 200:
            resp_json = r.json()
            # 兼容标准结构与包裹结构
            web_pages = (
                resp_json.get("data", {}).get("webPages", {}).get("value")
                or resp_json.get("webPages", {}).get("value")
                or []
            )
            out: list[dict[str, Any]] = []
            for item in web_pages:
                title = str(item.get("name") or item.get("title") or "").strip()
                link = str(item.get("url") or "").strip()
                snippet = str(item.get("summary") or item.get("snippet") or "").strip()
                date_val = str(item.get("dateLastCrawled") or item.get("datePublished") or "")[:10]
                if title and (snippet or link):
                    out.append({
                        "title": title,
                        "url": link,
                        "snippet": snippet,
                        "date": date_val,
                    })
            logger.info("博查 AI 搜索成功命中 %d 条结果 (Query: %s)", len(out), query)
            return out
        logger.warning("博查 AI 搜索失败: HTTP %d - %s", r.status_code, r.text[:200])
    except Exception as e:
        logger.warning("博查 AI 搜索异常: %s", e)
    return []
