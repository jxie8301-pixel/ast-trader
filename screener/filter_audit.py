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
    """Tier 2 排雷: 针对候选标的执行一票否决硬核排雷 (严格 Fail-Closed 防御原则)."""
    targets = candidates[:top_audit_count]
    passed = []

    def _audit_item(item: dict[str, Any]) -> dict[str, Any] | None:
        code_num = item["code"]
        name = item.get("name", code_num)
        try:
            gov = collector.get_f10_governance_and_concept(code_num)
            pledge_ratio = float(gov.get("pledge_ratio", 0.0) or 0.0)
            if pledge_ratio > config.PLEDGE_FATAL_RATIO:
                logger.warning(
                    f"一票否决: 剔除大股东高质押高危标的 {code_num} {name} "
                    f"(质押率 {pledge_ratio*100:.1f}% > 阈值 {config.PLEDGE_FATAL_RATIO*100:.0f}%)"
                )
                return None
            item["concepts"] = gov.get("concepts", [item["limit_reason"]])
            item["pledge_ratio"] = pledge_ratio
            item["audit_status"] = "VERIFIED_SAFE"
            return item
        except Exception as e:
            # 严格贯彻 Fail-Closed 买方风控: 无法核验排雷数据的标的绝不放行进入推荐池
            logger.warning(
                f"一票否决 (Fail-Closed 安全剔除): 标的 {code_num} {name} 治理排雷接口异常，"
                f"在途质押与减持风险未获证实，执行保守剔除: {type(e).__name__}: {e}"
            )
            return None

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_map = {executor.submit(_audit_item, c): c for c in targets}
        for fut in concurrent.futures.as_completed(future_map):
            res = fut.result()
            if res is not None:
                passed.append(res)

    logger.info(f"Tier 2 机械排雷完成: 检查 {len(targets)} 只 -> 安全通过 {len(passed)} 只标的")
    return passed
