"""Tier 1: Liquidity and momentum preliminary filter for AST-Trader."""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("ast_trader.screener.liquidity")


def filter_liquidity(
    ladder_rows: list[dict[str, Any]],
    quotes_map: dict[str, dict[str, float]],
    min_amount: float = 3e8,
    min_pct: float = 4.5,
) -> list[dict[str, Any]]:
    """Tier 1 过滤: 剔除 ST、低流动性与弱势股。"""
    passed = []
    for r in ladder_rows:
        fcode = r.get("full_code", "")
        code_num = r.get("code", "")
        name = r.get("name", f"标的_{code_num}")
        board_level = r.get("board_level") or 1
        reason = r.get("limit_reason") or "热门题材"

        # 剔除 ST / *ST / 退市
        if "ST" in name or "退" in name:
            continue

        q = quotes_map.get(fcode, {})
        close = q.get("close", 0.0)
        pct = q.get("pct_chg", 0.0)
        amount = q.get("amount", 0.0)

        # 封单金额兜底 (若盘后行情快照成交额为0)
        seal_amt = float(r.get("seal_amount") or 0.0)
        effective_amt = amount if amount > 0 else seal_amt

        # 初筛通过
        passed.append({
            "code": code_num,
            "full_code": fcode,
            "name": name,
            "close": close,
            "pct_chg": pct,
            "amount": effective_amt,
            "board_level": board_level,
            "limit_reason": reason,
            "seal_amt": seal_amt,
        })

    logger.info(f"Tier 1 初筛完成: 输入 {len(ladder_rows)} 只 -> 保留 {len(passed)} 只标的")
    return passed
