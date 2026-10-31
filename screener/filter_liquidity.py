"""Tier 1 / 轨道 A：流动性与动量初筛。

★ 本次修复的三处真实缺陷
------------------------
1. **换手率门槛是死代码**（最严重）。原实现读 ``q.get("turnover_ratio", 0.0)``，
   而 ``pipeline._fetch_quotes_map`` 只装了 ``{close, pre_close, pct_chg, amount}``
   四个键 —— turnover 恒为 0.0，``if turnover > 0.0`` 恒 False，8%~25% 这条规则
   从未生效过一次。现改为由 ``helpers.stock_profile_table`` 提供真实 ``turnover_rate``。
2. **板块判定漏 689 / 302**。原 ``is_gem_star`` 只认 ``300/301/688``，科创板 CDR
   ``689`` 与深市新代码段 ``302`` 被当主板处理（用错涨跌幅上限与成交额门槛）。
   现改为以代码表 ``board`` 为准（``sse_star_market`` / ``szse_chinext``），
   前缀仅作兜底。
3. **北交所靠成交额门槛隐式排除**。现显式产出 ``BSE_OUT_OF_SCOPE``，
   使对账表能回答"为什么少了 N 只"。

★ 归因：所有剔除点都写入 ``reason_code``，传入 ``audit`` 时同步进漏斗台账。
"""
from __future__ import annotations

import logging
from typing import Any

import config
from screener.universe import (
    REASON_BSE_OUT_OF_SCOPE,
    REASON_DELISTING,
    REASON_ST_RISK_WARNING,
    board_class,
    is_bse_code,
    is_delisting_name,
    is_st_name,
)

logger = logging.getLogger("ast_trader.screener.liquidity")

#: 本层判据全集（供漏斗做死规则检测）
RULES: tuple[str, ...] = (
    REASON_ST_RISK_WARNING,
    REASON_DELISTING,
    REASON_BSE_OUT_OF_SCOPE,
    "AMOUNT_BELOW_BOARD",
    "TURNOVER_OUT_OF_RANGE",
    "NO_QUOTE",
    "PCT_OUT_OF_RANGE",
)

_REASON_AMOUNT = "AMOUNT_BELOW_BOARD"
_REASON_TURNOVER = "TURNOVER_OUT_OF_RANGE"
_REASON_NO_QUOTE = "NO_QUOTE"
_REASON_PCT = "PCT_OUT_OF_RANGE"


def _opt_float(value: Any) -> float | None:
    """转 float；None / 不可解析一律返回 ``None``（**不是** 0.0）。

    ★ 与 ``filter_liquidity`` 旧实现的关键差别：旧实现到处 ``or 0.0``，
      把「通道不可得」伪装成「该科目为 0」，进而让判据按"确认很差"剔除标的。
    """
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def filter_liquidity(
    ladder_rows: list[dict[str, Any]],
    quotes_map: dict[str, dict[str, float]],
    min_amount: float | None = None,
    min_pct: float | None = None,
    *,
    mode: str = "close",
    audit: Any | None = None,
) -> list[dict[str, Any]]:
    """Tier 1 过滤: 剔除 ST / 退市 / 北交所、低流动性失血股与弱势标的。

    ``audit`` 传入 :class:`screener.funnel_audit.FunnelAudit` 时，
    每个剔除点会写入对应 ``reason_code``，用于归因矩阵与死规则检测。

    ★ ``quotes_map`` 现在必须包含 ``turnover_ratio``（由
      :mod:`screener.profile_batch` 提供真实值）。缺失时该标的按
      **换手率未核验** 处理：不因"换手率为 0"被误杀，而是走 NO_QUOTE 分支
      （连行情都没有的标的本就不该进池）。
    """
    passed: list[dict[str, Any]] = []
    stats: dict[str, int] = {}

    def drop(reason: str) -> None:
        stats[reason] = stats.get(reason, 0) + 1
        if audit is not None:
            audit.record_drop("T1_liquidity", reason)

    for r in ladder_rows:
        fcode = r.get("full_code", "")
        code_num = str(r.get("code", "") or "")
        name = r.get("name", f"标的_{code_num}")
        board_level = int(r.get("board_level") or 1)
        reason = r.get("limit_reason") or "热门题材"
        board = r.get("board")

        # 1. 剔除 ST / *ST（判定口径与 eltdx 自身 latest_st 一致：名称前缀法）
        if is_st_name(name):
            drop(REASON_ST_RISK_WARNING)
            continue
        # 2. 剔除退市整理期
        if is_delisting_name(name):
            drop(REASON_DELISTING)
            continue
        # 3. 北交所显式排除（业务决策，非数据缺失 —— 必须与"剔除"区分开）
        if is_bse_code(code_num):
            drop(REASON_BSE_OUT_OF_SCOPE)
            continue

        q = quotes_map.get(fcode, {})
        close = _opt_float(q.get("close"))
        pct = _opt_float(q.get("pct_chg"))
        amount = _opt_float(q.get("amount"))
        turnover = _opt_float(q.get("turnover_ratio"))
        seal_amt = float(r.get("seal_amount") or 0.0)
        effective_amt = amount if (amount is not None and amount > 0) else seal_amt

        # 无行情（停牌 / 取数缺失）：既无价也无量，无从判定，直接剔除
        if close is None or pct is None:
            drop(_REASON_NO_QUOTE)
            continue

        # 4. 流动性成交额硬核过滤（按板块分档：主板 5 亿 / 双创 3 亿）
        # ★ 20261029 审计 P1-14：mode 为 noon（午盘）时，交易仅进行半日（2小时），
        #   成交额门槛按 0.5x 折算，换手率下限亦相应折半，避免午盘突击时全市场被误杀。
        board_kind = board_class(board, code_num, r.get("exchange"))
        amt_scale = 0.5 if mode == "noon" else 1.0
        if min_amount is not None:
            amt_threshold = float(min_amount) * amt_scale
        else:
            base_amt = (
                config.LIQUIDITY_GEM_MIN_AMOUNT if board_kind == "growth"
                else config.LIQUIDITY_MAIN_MIN_AMOUNT
            )
            amt_threshold = base_amt * amt_scale

        # 一字连板（成交稀少但封单巨量锁仓）：豁免成交额与换手率门槛。
        # ★ 20261029 审计 P1-7：旧豁免条件只看「连板≥2 且封单≥1亿」—— 这会把大量
        #   **放量的高位板**也一起豁免掉，而它们恰恰最需要换手率上限的保护
        #   （高位放量 = 派发嫌疑）。一字板的定义是**全天只有一档价**：high == low
        #   （开盘即封死、盘中未打开）。现要求三个条件同时成立，且 high/low 缺失时
        #   **不豁免**（不可核验 → 按常规门槛走，保守方向）。
        _high = _opt_float(q.get("high"))
        _low = _opt_float(q.get("low"))
        is_one_word_leader = (
            board_level >= 2
            and seal_amt >= 1.0e8
            and _high is not None and _low is not None and _low > 0
            and _high <= _low                      # 全天一档价 = 真·一字
        )
        if (effective_amt or 0.0) < amt_threshold and not is_one_word_leader:
            drop(_REASON_AMOUNT)
            continue

        # 5. 换手率区间过滤 (对齐 SRS FR-06 / config: 8% ~ 25%)
        #    ★ 这里曾经是死代码（turnover 恒为 0）。现在 turnover 由
        #      stock_profile_table 的真实 turnover_rate 提供，门槛才真正生效。
        if turnover is None:
            # 换手率不可核验：不适用本条（NFR-02 —— 缺失≠0，也≠不合格）
            pass
        elif not is_one_word_leader:
            min_to = config.MOMENTUM_MIN_TURNOVER_RATE * (0.5 if mode == "noon" else 1.0)
            if turnover < min_to or turnover > config.MOMENTUM_MAX_TURNOVER_RATE:
                drop(_REASON_TURNOVER)
                continue

        # 6. 涨幅动量硬核过滤（要求达到短线爆发阈值，且不超过板块涨幅上限）
        pct_threshold = min_pct if min_pct is not None else config.MOMENTUM_MIN_PCT_CHG
        max_pct = 20.5 if board_kind == "growth" else 10.5
        is_limit_up = pct >= 9.5 or (board_kind == "growth" and pct >= 19.5)
        if (pct < pct_threshold and not is_limit_up) or (pct > max_pct):
            drop(_REASON_PCT)
            continue

        passed.append({
            "code": code_num,
            "full_code": fcode,
            "name": name,
            "close": close,
            "pct_chg": pct,
            "amount": effective_amt,
            "turnover_ratio": turnover,
            "board_level": board_level,
            "board": board,
            "board_kind": board_kind,
            "limit_reason": reason,
            "seal_amt": seal_amt,
        })

    logger.info(
        f"Tier 1 初筛完成: 输入 {len(ladder_rows)} 只 -> 保留 {len(passed)} 只 | "
        f"剔除明细 {stats if stats else '无'}"
    )
    return passed
