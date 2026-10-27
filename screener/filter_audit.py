"""Tier 2: Governance and audit red flags one-vote veto screener."""
from __future__ import annotations

import concurrent.futures
import logging
from typing import Any

import config
from data.eltdx_collector import EltdxCollector

logger = logging.getLogger("ast_trader.screener.audit")


def filter_audit(
    candidates: list[dict[str, Any]],
    collector: EltdxCollector,
    max_workers: int = 5,
    top_audit_count: int = 15,
) -> list[dict[str, Any]]:
    """Tier 2 排雷: 针对优质候选标的进行并发治理排雷（一票否决高质押与暴雷标的）。"""
    targets = candidates[:top_audit_count]
    passed = []

    def _audit_item(item: dict[str, Any]) -> dict[str, Any] | None:
        code_num = item["code"]
        try:
            gov = collector.get_f10_governance_and_concept(code_num)
            pledge_ratio = gov.get("pledge_ratio", 0.0)
            if pledge_ratio > config.PLEDGE_FATAL_RATIO:
                logger.warning(f"一票否决: 剔除高质押标的 {code_num} {item['name']} (质押率 {pledge_ratio*100:.1f}%)")
                return None
            item["concepts"] = gov.get("concepts", [item["limit_reason"]])
            return item
        except Exception as e:
            logger.debug(f"治理排雷跳过 {code_num}: {e}")
            return item

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_map = {executor.submit(_audit_item, c): c for c in targets}
        for fut in concurrent.futures.as_completed(future_map):
            res = fut.result()
            if res is not None:
                passed.append(res)

    logger.info(f"Tier 2 机械排雷完成: 检查 {len(targets)} 只 -> 通过 {len(passed)} 只")
    return passed
