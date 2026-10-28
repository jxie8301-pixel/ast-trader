"""Tier 1: Liquidity and momentum preliminary filter for AST-Trader."""
from __future__ import annotations

import logging
from typing import Any

import config

logger = logging.getLogger("ast_trader.screener.liquidity")


def filter_liquidity(
    ladder_rows: list[dict[str, Any]],
    quotes_map: dict[str, dict[str, float]],
    min_amount: float | None = None,
    min_pct: float | None = None,
) -> list[dict[str, Any]]:
    """Tier 1 过滤: 严格按买方标准剔除 ST、低流动性失血股与弱势标的。"""
    passed = []
    dropped_st = 0
    dropped_liq = 0
    dropped_pct = 0

    for r in ladder_rows:
        fcode = r.get("full_code", "")
        code_num = r.get("code", "")
        name = r.get("name", f"标的_{code_num}")
        board_level = int(r.get("board_level") or 1)
        reason = r.get("limit_reason") or "热门题材"

        # 1. 剔除 ST / *ST / 退市
        if "ST" in name or "退" in name:
            dropped_st += 1
            continue

        q = quotes_map.get(fcode, {})
        close = float(q.get("close", 0.0) or 0.0)
        pct = float(q.get("pct_chg", 0.0) or 0.0)
        amount = float(q.get("amount", 0.0) or 0.0)
        seal_amt = float(r.get("seal_amount") or 0.0)
        effective_amt = amount if amount > 0 else seal_amt

        # 2. 流动性成交额硬核过滤 (区分主板 5 亿与双创 3 亿)
        is_gem_star = code_num.startswith(("300", "301", "688"))
        if min_amount is not None:
            amt_threshold = min_amount
        else:
            amt_threshold = config.LIQUIDITY_GEM_MIN_AMOUNT if is_gem_star else config.LIQUIDITY_MAIN_MIN_AMOUNT

        # 一字连板 (成交稀少但封单巨量锁仓) 允许一字板巨量封单达标 (>=1亿) 豁免
        is_one_word_leader = board_level >= 2 and seal_amt >= 1.0e8
        if effective_amt < amt_threshold and not is_one_word_leader:
            dropped_liq += 1
            continue

        # 3. 涨幅动量硬核过滤 (要求达到短线爆发阈值)
        pct_threshold = min_pct if min_pct is not None else config.MOMENTUM_MIN_PCT_CHG
        # 若是涨停封板 (>=9.5% 或 >=19.5%) 或涨幅达到阈值才放行
        is_limit_up = pct >= 9.5 or (is_gem_star and pct >= 19.5)
        if pct < pct_threshold and not is_limit_up:
            dropped_pct += 1
            continue

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

    logger.info(
        f"Tier 1 初筛完成: 输入 {len(ladder_rows)} 只 -> "
        f"剔除 ST {dropped_st} 只 / 流动性不足 {dropped_liq} 只 / 涨幅弱势 {dropped_pct} 只 -> "
        f"保留 {len(passed)} 只合格标的"
    )
    return passed
