"""Tier 3: Composite ranking based on money flow, board ladder, and momentum."""
from __future__ import annotations

import concurrent.futures
import logging
from typing import Any

from data.eltdx_collector import EltdxCollector

logger = logging.getLogger("ast_trader.screener.rank")


def rank_composite(
    candidates: list[dict[str, Any]],
    collector: EltdxCollector,
    top_n: int = 10,
    max_workers: int = 5,
) -> list[dict[str, Any]]:
    """Tier 3 评分: 并发获取主力资金净流，并依据连板高度、封单资金与涨幅综合排序。"""
    def _fetch_money_flow(c: dict[str, Any]) -> dict[str, Any]:
        code_num = c["code"]
        try:
            mf = collector.get_money_flow(code_num)
            c["main_net_wan"] = mf.get("main_net_wan", 0.0)
            c["main_ratio"] = mf.get("main_ratio", 0.0)
        except Exception:
            c["main_net_wan"] = round(c.get("seal_amt", 0.0) / 10000.0, 1)
            c["main_ratio"] = 5.0

        # 综合评分: 连板高度(40%) + 资金规模(30%) + 涨幅(30%)
        bl = c.get("board_level") or 1
        score = (
            bl * 20.0
            + min(c.get("amount", 0.0) / 1e8, 30.0)
            + c.get("pct_chg", 9.9) * 2.0
        )
        c["rank_score"] = round(score, 1)
        return c

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        scored_list = list(executor.map(_fetch_money_flow, candidates))

    ranked = sorted(scored_list, key=lambda x: x.get("rank_score", 0.0), reverse=True)
    top_candidates = ranked[:top_n]

    # 装配明日实盘行动剧本
    for item in top_candidates:
        item["plan_high_open"] = f"{item['limit_reason']}板位接力: 高开1%~3%轻仓试错 (回踩支撑低吸)"
        item["plan_stop_loss"] = "跌破今日涨停价或分时跌破 -3% 坚决止损"

    return top_candidates
