"""全市场四轨分流引擎：轨道 B / C / D 的判据与战术剧本。

（轨道 A「超短连板与题材接力」沿用既有 Tier1→Tier2→Tier3 链路，在
:mod:`screener.pipeline` 里与本模块的分流结果汇合。）

★ 三条硬约束来自 20261028 实测，不是设计偏好
----------------------------------------------
1. **日 K 26ms/只，全市场 5225 只 ≈ 130s** ⇒ 轨道 B/C 必须先用
   ``stock_profile_table`` 的**免费字段**（市值/换手/成交额/涨跌幅）预筛压缩，
   再懒加载日 K。任何"全市场拉日 K"的实现都会被成本否决。
2. **``corporate.finance_batch`` 静默截断在 100 只**（请求 300 只只返回 100 只），
   但 100 只仅 0.03s ⇒ 轨道 D 反而可以**近乎免费地全市场扫描**（5225 只 ≈ 2s）。
3. **``f10.valuation`` 无 PE/PB、``f10.finance_diagnosis`` 返回 0 行、
   ``ranking_detail`` 行业排名 section 为空** ⇒ 估值与盈利质量一律由
   ``finance_batch`` 自算；行业排名降级为可选增强，市值分位由本项目对全池自算。

★ 数据纪律 (NFR-02)
-------------------
"不可核验"与"不合格"必须是**两个不同的 reason_code**：
    ``*_BARS_MISSING`` / ``*_VALUATION_UNVERIFIED`` vs ``*_PE_TOO_HIGH``
前者是通道问题（可重试、可降级），后者是标的真不合格。混在一起会让
「数据断流」伪装成「市场里没有低估值的票」。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import config
from core.execution_playbook import ExecutionPlaybook

logger = logging.getLogger("ast_trader.screener.tracks")

TRACK_A = "A"
TRACK_B = "B"
TRACK_C = "C"
TRACK_D = "D"

TRACK_NAMES: dict[str, str] = {
    TRACK_A: "超短连板与题材接力",
    TRACK_B: "弱转强 / 首阴反包",
    TRACK_C: "产业中军与趋势白马",
    TRACK_D: "困境反转与价值成长",
}

# ─── 轨道 B 剔除码 ───
B_NOT_WEAK_TODAY = "B_NOT_WEAK_TODAY"              # 今日未收阴/未炸板 → 无"弱"可转
B_TOO_WEAK_TODAY = "B_TOO_WEAK_TODAY"              # ★ P1-1：今日跌过头（破位）→ 不是"弱转强"是崩塌
B_NO_RECENT_LIMIT_UP = "B_NO_RECENT_LIMIT_UP"      # 近 N 日未曾涨停
B_VOLUME_NOT_SHRUNK = "B_VOLUME_NOT_SHRUNK"        # 放量下跌 = 派发，不是洗盘
B_BELOW_MA5 = "B_BELOW_MA5"                        # 跌破 5 日线
B_VWAP_WEAK = "B_VWAP_WEAK"                        # 大幅低于均价 → 承接差
B_BARS_MISSING = "B_BARS_MISSING"                  # 日 K 不可核验
B_PREFILTER_OUT = "B_PREFILTER_OUT"                # 免费字段预筛即出局（非炸板且未收阴/不活跃）

# ─── 轨道 C 剔除码 ───
C_MARKET_CAP_TOO_SMALL = "C_MARKET_CAP_TOO_SMALL"
C_MARKET_CAP_PCTILE_LOW = "C_MARKET_CAP_PCTILE_LOW"
C_TURNOVER_OUT_OF_RANGE = "C_TURNOVER_OUT_OF_RANGE"
C_PCT_OUT_OF_RANGE = "C_PCT_OUT_OF_RANGE"
C_AVG_AMOUNT_BELOW = "C_AVG_AMOUNT_BELOW"
C_MA_NOT_BULLISH = "C_MA_NOT_BULLISH"
C_BARS_MISSING = "C_BARS_MISSING"
C_PREFILTER_OUT = "C_PREFILTER_OUT"                # 市值/换手/涨幅不达预筛线
C_PREFILTER_TRUNCATED = "C_PREFILTER_TRUNCATED"    # 预筛后仍超限，按市值降序截断

# ─── 轨道 D 剔除码 ───
D_AMOUNT_BELOW = "D_AMOUNT_BELOW"
D_PE_TOO_HIGH = "D_PE_TOO_HIGH"
D_PB_TOO_HIGH = "D_PB_TOO_HIGH"
D_ROE_TOO_LOW = "D_ROE_TOO_LOW"
D_OCF_WEAK = "D_OCF_WEAK"
D_VALUATION_UNVERIFIED = "D_VALUATION_UNVERIFIED"  # eps/净资产缺失 → 估值不可核验
D_FINANCE_MISSING = "D_FINANCE_MISSING"
# ─── 轨道 D 边际拐点（多期财报，20261028 后**可核验**）──────────
D_TREND_DETERIORATING = "D_TREND_DETERIORATING"    # 可核验且边际恶化 → 否决
D_TREND_UNVERIFIED = "D_TREND_UNVERIFIED"          # 期数不足/取数失败 → 放行但标注

TRACK_RULES: dict[str, tuple[str, ...]] = {
    TRACK_B: (B_PREFILTER_OUT, B_NOT_WEAK_TODAY, B_TOO_WEAK_TODAY, B_NO_RECENT_LIMIT_UP,
              B_VOLUME_NOT_SHRUNK, B_BELOW_MA5, B_VWAP_WEAK, B_BARS_MISSING),
    TRACK_C: (C_PREFILTER_OUT, C_PREFILTER_TRUNCATED, C_MARKET_CAP_TOO_SMALL,
              C_MARKET_CAP_PCTILE_LOW, C_TURNOVER_OUT_OF_RANGE,
              C_PCT_OUT_OF_RANGE, C_AVG_AMOUNT_BELOW, C_MA_NOT_BULLISH, C_BARS_MISSING),
    # ★ ``D_TREND_UNVERIFIED`` **不在**这里：它不是判据，是数据质量标记。
    #   不可核验的标的**保留**在输出里，若把它算进归因矩阵的"淘汰"，
    #   就会出现「同一只票既被记淘汰又在输出中」的不守恒（20261028 首跑复现差额 -6）。
    TRACK_D: (D_AMOUNT_BELOW, D_PE_TOO_HIGH, D_PB_TOO_HIGH, D_ROE_TOO_LOW,
              D_OCF_WEAK, D_VALUATION_UNVERIFIED, D_FINANCE_MISSING,
              D_TREND_DETERIORATING),
}

#: 轨道 C 机构持股的加权档位（**不参与准入**，只影响排序）
INST_TIER_QUALIFIED = 1     # 可核验且 ≥ 门槛
INST_TIER_BELOW = 2         # 可核验但低于门槛
INST_TIER_UNVERIFIED = 3    # 不可核验


@dataclass
class TrackScreenResult:
    """单轨筛选结果。"""

    track: str
    passed: list[dict[str, Any]] = field(default_factory=list)
    dropped: dict[str, int] = field(default_factory=dict)

    def bump(self, reason: str, n: int = 1) -> None:
        if n <= 0:
            return
        self.dropped[reason] = self.dropped.get(reason, 0) + n

    @property
    def input_count(self) -> int:
        return len(self.passed) + sum(self.dropped.values())


def _opt_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def turnover_band(market_cap: float | None) -> tuple[float, float]:
    """按市值分档返回换手率合理区间 ``(下限, 上限)``。

    ★ 20261028 实测校准：大市值中军换手天然低（美的 0.345%）。统一门槛会把
      轨道 C 的目标标的整体误杀，故按市值分档。
    """
    mv = market_cap or 0.0
    for floor, lo, hi in getattr(config, "TRACK_C_TURNOVER_BANDS", ()):
        if mv >= floor:
            return lo, hi
    return 1.0, 8.0


def _market_cap_percentiles(candidates: list[dict[str, Any]]) -> dict[str, float]:
    """对**当前母池**自算总市值分位（0~1）。

    ★ 不依赖第三方分位：本项目手上就有 5000+ 只的真实市值，自算分位比任何
      外部"行业排名"都准，而且 20261028 实测 ``ranking_detail`` 的行业排名
      section 返回空 —— 依赖它会导致规则恒定不触发。
    """
    caps: list[tuple[str, float]] = []
    for c in candidates:
        mv = _opt_float(c.get("total_mv"))
        if mv is not None and mv > 0:
            caps.append((c["full_code"], mv))
    if not caps:
        return {}
    caps.sort(key=lambda kv: kv[1])
    n = len(caps)
    return {code: (i + 1) / n for i, (code, _) in enumerate(caps)}


# ══════════════════════════════════════════════════════════ 轨道 B
def prefilter_track_b(
    candidates: list[dict[str, Any]],
    broken_codes: set[str] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """轨道 B 免费字段预筛 —— 目的是把日 K 拉取量从 5000 压到数百只。

    入选条件（任一）：
      * 当日**炸板**（天梯 ``broken_rows``，约 70 只）—— 最典型的"弱"；
      * 当日涨幅 ≤ ``TRACK_B_MAX_PCT_CHG`` 且成交额 ≥ ``TRACK_B_MIN_AMOUNT``
        —— 收阴/滞涨但仍有承接的活跃票。

    返回 ``(存活集, 逐判据淘汰计数)``。
    ★ 必须**逐判据**归因：若把所有失败合并成 ``B_PREFILTER_OUT``，内部判据
      在归因矩阵里永远为 0，会被死规则检测误报（20261028 首跑即复现 9 条误报）。
    """
    broken_codes = broken_codes or set()
    out: list[dict[str, Any]] = []
    dropped: dict[str, int] = {}

    def drop(reason: str) -> None:
        dropped[reason] = dropped.get(reason, 0) + 1

    for c in candidates:
        if c.get("code") in broken_codes:
            out.append(c)
            continue
        pct = _opt_float(c.get("change_pct"))
        amount = _opt_float(c.get("amount"))
        if pct is None or amount is None:
            drop(B_PREFILTER_OUT)
            continue
        # 判据顺序 = 归因顺序：先看"有没有弱"，再看"弱得有没有人管"
        if pct > config.TRACK_B_MAX_PCT_CHG:
            drop(B_NOT_WEAK_TODAY)
            continue
        # ★ P1-1：弱转强要的是**浅回调**。跌破下限属破位下跌（接飞刀），不是洗盘。
        if pct < config.TRACK_B_MIN_PCT_CHG:
            drop(B_TOO_WEAK_TODAY)
            continue
        if amount < config.TRACK_B_MIN_AMOUNT:
            drop(B_PREFILTER_OUT)
            continue
        out.append(c)
    return out, dropped


def screen_track_b(
    candidates: list[dict[str, Any]],
    kline_map: dict[str, list[Any]],
    broken_codes: set[str] | None = None,
) -> TrackScreenResult:
    """轨道 B 准入：近 3 日曾涨停 + 今日走弱 + 缩量 + 未破 MA5 + 承接尚可。

    ★ 判据顺序即归因顺序：先判"有没有弱"，再判"弱得健不健康"。
    """
    from .kline_batch import ma, recent_limit_up_days, volume_ratio, vwap_deviation

    broken_codes = broken_codes or set()
    res = TrackScreenResult(track=TRACK_B)

    for c in candidates:
        code = c.get("code", "")
        full_code = c.get("full_code", "")
        board_kind = c.get("board_kind")
        is_broken = code in broken_codes

        # 1. 今日必须"弱"：收阴/滞涨（炸板天然满足）
        if not is_broken:
            pct = _opt_float(c.get("change_pct"))
            if pct is None or pct > config.TRACK_B_MAX_PCT_CHG:
                res.bump(B_NOT_WEAK_TODAY)
                continue
            # ★ P1-1：跌过头 = 破位，不是"弱转强"的浅回调
            if pct < config.TRACK_B_MIN_PCT_CHG:
                res.bump(B_TOO_WEAK_TODAY)
                continue

        bars = kline_map.get(full_code) or []
        if not bars:
            res.bump(B_BARS_MISSING)
            continue

        # 2. 近 N 日内曾涨停 —— 没有前序的"强"，就谈不上"弱转强"
        lu = recent_limit_up_days(bars, config.TRACK_B_LOOKBACK_DAYS, board_kind)
        if lu is None:
            res.bump(B_BARS_MISSING)
            continue
        if lu <= 0 and not is_broken:
            res.bump(B_NO_RECENT_LIMIT_UP)
            continue

        # 3. 缩量回踩（放量下跌是派发，不是洗盘）
        vr = volume_ratio(bars)
        if vr is None:
            res.bump(B_BARS_MISSING)
            continue
        if vr > config.TRACK_B_MAX_VOLUME_RATIO:
            res.bump(B_VOLUME_NOT_SHRUNK)
            continue

        # 4. 不得跌破 MA5
        ma5 = ma(bars, config.TRACK_B_MA_PERIOD)
        if ma5 is None:
            res.bump(B_BARS_MISSING)
            continue
        if bars[-1].close < ma5:
            res.bump(B_BELOW_MA5)
            continue

        # 5. 承接：现价不得大幅低于当日均价
        dev = vwap_deviation(bars)
        if dev is not None and dev < -config.TRACK_B_MAX_VWAP_DEVIATION:
            res.bump(B_VWAP_WEAK)
            continue

        out = dict(c)
        out["track"] = TRACK_B
        out["track_name"] = TRACK_NAMES[TRACK_B]
        out["is_broken_today"] = is_broken
        out["recent_limit_up_days"] = lu
        out["volume_ratio"] = vr
        out["ma5"] = ma5
        out["vwap_deviation"] = dev
        out.update(_track_b_playbook(out, bars))
        res.passed.append(out)

    return res


def _track_b_playbook(c: dict[str, Any], bars: list[Any]) -> dict[str, Any]:
    """轨道 B 战术：次日反包试错仓（当日不建仓，等次日确认）。"""
    close = _opt_float(c.get("close")) or (bars[-1].close if bars else 0.0) or 0.0
    ma5 = _opt_float(c.get("ma5"))
    trial = int(round(config.TRACK_B_TRIAL_POSITION_PCT * 100))
    support = round(min(ma5 or close * 0.97, close * 0.97), 2)

    pb = ExecutionPlaybook(
        action="AUCTION",
        action_label="♻️ 次日弱转强反包 (条件单)",
        entry_tactic=(
            "【次日 9:25 弱转强确认】今日缩量回踩未破 5 日线，属洗盘而非派发。"
            "仅在次日 9:25 竞价高开且开盘 30 分钟内站上分时均线(VWAP)时介入；"
            "低开或直接跌破 5 日线一律废单"
        ),
        entry_price_range=f"确认后挂单区间: {round(close * 0.97, 2)} ~ {round(close * 1.02, 2)} 元",
        base_position_pct=0,
        add_position_pct=trial,
        max_position_pct=trial,
        take_profit_target=f"反包至前高附近分批止盈，余仓跌破 5 日线 {support} 元离场",
        stop_loss_line=f"跌破 5 日线 {support} 元",
        invalidation_rule=(
            f"废单线: 次日低开且不能快速收回 5 日线 {support} 元即放弃，"
            f"严禁在条件不满足时把'洗盘'自我说服成'加仓机会'"
        ),
    )
    return {
        "playbook": pb,
        "action": "wait_auction",
        "action_desc": f"弱转强反包候选 (近{config.TRACK_B_LOOKBACK_DAYS}日曾涨停，缩量回踩未破MA5)",
    }


# ══════════════════════════════════════════════════════════ 轨道 C
def prefilter_track_c(
    candidates: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], int, dict[str, int]]:
    """轨道 C 免费字段预筛：市值/换手/涨幅，按市值降序截断到 ``TRACK_C_PRE_FILTER_MAX``。

    返回 ``(预筛存活集, 截断前通过数, 逐判据淘汰计数)``。

    ★ 必须**逐判据**归因：若把所有失败合并成 ``C_PREFILTER_OUT``，则
      ``C_MARKET_CAP_TOO_SMALL`` 等判据在归因矩阵里永远为 0，会被死规则检测
      误报（20261028 首跑复现）。
    ★ 截断**按市值降序**且单独记账 —— 绝不按代码表原始顺序无声丢弃
      （那正是旧版 Tier 2 前 15 名截断的事故形态）。
    """
    pct_map = _market_cap_percentiles(candidates)
    out: list[dict[str, Any]] = []
    dropped: dict[str, int] = {}

    def drop(reason: str) -> None:
        dropped[reason] = dropped.get(reason, 0) + 1

    for c in candidates:
        pct = _opt_float(c.get("change_pct"))
        turn = _opt_float(c.get("turnover_rate"))
        mv = _opt_float(c.get("total_mv"))
        if pct is None or turn is None or mv is None:
            drop(C_PREFILTER_OUT)
            continue
        if mv < config.TRACK_C_MIN_MARKET_CAP:
            drop(C_MARKET_CAP_TOO_SMALL)
            continue
        pctile = pct_map.get(c.get("full_code", ""))
        if pctile is not None and pctile < config.TRACK_C_MIN_MARKET_CAP_PCTILE:
            drop(C_MARKET_CAP_PCTILE_LOW)
            continue
        lo, hi = turnover_band(mv)
        if not (lo <= turn <= hi):
            drop(C_TURNOVER_OUT_OF_RANGE)
            continue
        if not (config.TRACK_C_MIN_PCT_CHG <= pct <= config.TRACK_C_MAX_PCT_CHG):
            drop(C_PCT_OUT_OF_RANGE)
            continue
        item = dict(c)
        item["market_cap_pctile"] = pctile
        out.append(item)

    out.sort(key=lambda x: (_opt_float(x.get("total_mv")) or 0.0), reverse=True)
    passed_before_cap = len(out)
    return out[: config.TRACK_C_PRE_FILTER_MAX], passed_before_cap, dropped


def screen_track_c(
    candidates: list[dict[str, Any]],
    kline_map: dict[str, list[Any]],
) -> TrackScreenResult:
    """轨道 C 准入：市值分位 + 均线多头 + 20 日日均成交额 + 温和换手。

    ★ 「前十大流通股东机构持股占比 ≥15%」在 eltdx **无数据通道**（用户已裁决
      降级）：改为有则加权、无则 ``UNVERIFIED`` 降权，**不参与准入**。
    """
    from .kline_batch import avg_amount, bullish_ma_stack

    res = TrackScreenResult(track=TRACK_C)

    for c in candidates:
        full_code = c.get("full_code", "")
        bars = kline_map.get(full_code) or []
        if not bars:
            res.bump(C_BARS_MISSING)
            continue

        # 1. 交易容量：20 日日均成交额（大资金的进出场前提）
        avg_amt = avg_amount(bars, 20)
        if avg_amt is None:
            res.bump(C_BARS_MISSING)
            continue
        if avg_amt < config.TRACK_C_MIN_AVG_AMOUNT_20D:
            res.bump(C_AVG_AMOUNT_BELOW)
            continue

        # 2. 趋势结构：多头均线排列
        bull = bullish_ma_stack(bars, config.TRACK_C_MA_PERIODS)
        if bull is None:
            res.bump(C_BARS_MISSING)
            continue
        if not bull:
            res.bump(C_MA_NOT_BULLISH)
            continue

        out = dict(c)
        out["track"] = TRACK_C
        out["track_name"] = TRACK_NAMES[TRACK_C]
        out["avg_amount_20d"] = avg_amt
        out["ma_bullish"] = True
        out["institutional_holding"] = "UNVERIFIED"   # ★ 无数据通道，明确标注
        out.update(_track_c_playbook(out, bars))
        res.passed.append(out)

    return res


def apply_track_c_institutional(
    passed: list[dict[str, Any]],
    holdings: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """轨道 C 的机构持股**加权排序**（不参与准入）。

    ★ 用户裁决：机构持股「有则加权、无则 UNVERIFIED 降权，**不参与准入**」。
      所以这里**一票不淘汰**，只重排顺序并写入字段：
        · 可核验且 ≥ ``TRACK_C_INSTITUTION_MIN_RATIO`` → 第 1 档（加权）
        · 可核验但低于门槛                            → 第 2 档（降权）
        · 不可核验                                    → 第 3 档（降权）
      绝不能因为取不到股东数据就把一只合格的中军踢掉 —— 那是通道问题，
      不是标的问题（NFR-02）。

    返回 ``(重排后的列表, 档位计数)``。
    """
    threshold = float(getattr(config, "TRACK_C_INSTITUTION_MIN_RATIO", 0.15))
    tiers: dict[str, int] = {}

    for c in passed:
        hold = holdings.get(str(c.get("code") or "").zfill(6))
        if hold is None or not hold.verified:
            tier, ratio, state = INST_TIER_UNVERIFIED, None, None
            breakdown: dict[str, float] = {}
            report_date = None
        else:
            ratio = hold.institutional_ratio
            state = hold.state_ratio
            breakdown = hold.breakdown
            report_date = hold.report_date
            tier = INST_TIER_QUALIFIED if (ratio is not None and ratio >= threshold) else INST_TIER_BELOW

        c["institutional_holding"] = (f"{ratio*100:.1f}%" if ratio is not None else "UNVERIFIED")
        c["institutional_ratio"] = ratio
        c["institutional_state_ratio"] = state
        c["institutional_breakdown"] = breakdown
        c["institutional_report_date"] = report_date
        c["institutional_tier"] = tier
        tiers[str(tier)] = tiers.get(str(tier), 0) + 1

    passed.sort(key=lambda x: (int(x.get("institutional_tier", 3)),
                               -(x.get("institutional_ratio") or 0.0)))
    return passed, tiers


def _track_c_playbook(c: dict[str, Any], bars: list[Any]) -> dict[str, Any]:
    """轨道 C 战术：均线回踩右侧低吸，仓位上限放宽至 ``TRACK_C_MAX_POSITION_PCT``。"""
    from .kline_batch import ma

    close = _opt_float(c.get("close")) or (bars[-1].close if bars else 0.0) or 0.0
    ma5 = ma(bars, 5)
    ma20 = ma(bars, 20)
    max_pos = int(round(config.TRACK_C_MAX_POSITION_PCT * 100))
    base_pos = int(round(max_pos * 0.5))
    support = round(ma20 or ma5 or close * 0.95, 2)

    pb = ExecutionPlaybook(
        action="BUY",
        action_label="🏛️ 均线回踩右侧低吸",
        entry_tactic=(
            "【右侧低吸建仓】沿 5/20 日线分批吸纳，回踩不破 20 日线且缩量时为佳；"
            "严禁在单日大涨时追高，中军靠的是持仓周期而非日内弹性"
        ),
        entry_price_range=f"低吸区间: {round((ma5 or close) * 0.98, 2)} ~ {round(close * 1.01, 2)} 元",
        base_position_pct=base_pos,
        add_position_pct=max_pos - base_pos,
        max_position_pct=max_pos,
        take_profit_target="波段持有，跌破 20 日线减半，跌破 60 日线清仓",
        stop_loss_line=f"有效跌破 20 日线 {support} 元",
        invalidation_rule=(
            f"趋势破坏线: 收盘有效跌破 20 日线 {support} 元或 20 日日均成交额萎缩至 "
            f"{config.TRACK_C_MIN_AVG_AMOUNT_20D/1e8:.0f} 亿以下，减仓至半仓以下"
        ),
    )
    return {
        "playbook": pb,
        "action": "buyable",
        "action_desc": "产业中军：市值分位靠前 + 均线多头 + 大容量成交",
    }


# ══════════════════════════════════════════════════════════ 轨道 D
def screen_track_d(
    candidates: list[dict[str, Any]],
    finance_map: dict[str, Any],
) -> TrackScreenResult:
    """轨道 D 准入：估值双锚（PE+PB）+ ROE + 经营现金流造血。

    ★ 数据通道说明（20261028 实测）：
      * ``f10.valuation`` 只返回分页计数，**无 PE/PB**；
      * ``f10.finance_diagnosis`` 返回 **0 行**；
      ⇒ 全部改由 ``corporate.finance_batch`` 自算（eps / 每股净资产 / 净利润 /
        净资产 / 经营现金流）。
    ★ 「ROE 边际拐点」由 :func:`apply_track_d_trend` 单独处理：
      ``finance_batch`` 只给单期快照，但 ``CWServ.tdxf10_gg_cwfx`` 一次给
      32~114 个报告期 ⇒ 拐点**可核验**（此前误判为不可得）。
      绝对水平在本函数判，边际拐点在后置步骤判 —— 两者职责分开。
    """
    res = TrackScreenResult(track=TRACK_D)

    for c in candidates:
        full_code = c.get("full_code", "")
        fin = finance_map.get(full_code)
        if fin is None:
            res.bump(D_FINANCE_MISSING)
            continue

        amount = _opt_float(c.get("amount"))
        if amount is None or amount < config.TRACK_D_MIN_AMOUNT:
            res.bump(D_AMOUNT_BELOW)
            continue

        price = _opt_float(c.get("close"))
        pe = fin.pe(price)              # ★ P1-2：已按报告期年化 EPS 计算
        pb = fin.pb(price)
        pe_basis = fin.pe_basis()
        roe = fin.roe_pct()             # ★ P1-2：已按报告期年化净利润计算
        roe_basis = fin.roe_basis()

        # ★ 20261029 审计 P1-2：报告期不可核验 → PE/ROE 的量纲不是"年度"，
        #   与 ``TRACK_D_MAX_PE=30`` / ``TRACK_D_MIN_ROE=8`` 这类**年度**阈值不可比。
        #   此时**放行**（不做阈值否决）但如实标记 UNVERIFIED —— 宁可放过，
        #   也不能拿单期值去误杀（旧实现正是拿季度分去比年度及格线）。
        unverified_basis = (
            pe_basis == "single_period_unverified" or roe_basis == "single_period_unverified"
        )

        # ★ 估值不可核验 ≠ 低估值：把它单列，避免"通道故障"伪装成"市场无便宜货"
        if pe is None and pb is None:
            res.bump(D_VALUATION_UNVERIFIED)
            continue

        if not unverified_basis:
            if pe is not None and pe > config.TRACK_D_MAX_PE:
                res.bump(D_PE_TOO_HIGH)
                continue
            if pb is not None and pb > config.TRACK_D_MAX_PB:
                res.bump(D_PB_TOO_HIGH)
                continue
            if roe is None or roe < config.TRACK_D_MIN_ROE:
                res.bump(D_ROE_TOO_LOW)
                continue

        ocf = fin.ocf_to_profit()
        if ocf is None or ocf < config.TRACK_D_MIN_OCF_TO_PROFIT:
            res.bump(D_OCF_WEAK)
            continue

        out = dict(c)
        out["track"] = TRACK_D
        out["track_name"] = TRACK_NAMES[TRACK_D]
        out["pe"] = pe
        out["pb"] = pb
        out["roe_pct"] = roe
        out["ocf_to_profit"] = ocf
        # ★ P1-3：报告期与数据更新日期分开给 —— 旧代码把"更新日期"当"报告期"展示
        out["report_date"] = fin.report_period or fin.report_date
        out["report_period"] = fin.report_period
        out["data_updated_at"] = fin.report_date
        out["report_period_source"] = fin.report_period_source
        # ★ P1-2：口径标签（年化 / 单期未核验），呈现与账本都要如实标注
        out["pe_basis"] = pe_basis
        out["roe_basis"] = roe_basis
        out["valuation_unverified"] = unverified_basis
        out["debt_ratio_pct"] = fin.debt_ratio_pct()
        out["roe_trend"] = "UNVERIFIED"   # ★ 单期快照，环比拐点不可核验
        out.update(_track_d_playbook(out))
        res.passed.append(out)

    return res


def apply_track_d_trend(
    passed: list[dict[str, Any]],
    trends: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, int], int]:
    """轨道 D 的**边际拐点**判据：可核验时生效，不可核验一律放行。

    ★ 判定顺序即归因顺序：
      1. 取数失败 / 期数不足（次新股）→ **放行并标注** ``roe_trend=UNVERIFIED``
         —— 不可核验绝不等于"业绩零增长"（NFR-02）。
      2. 可核验且 ``trend == 'decelerating'`` → 否决（``D_TREND_DETERIORATING``）。
      3. 其余（``turning_positive`` / ``accelerating`` / ``stable``）→ 放行。

    返回 ``(存活列表, 剔除计数, 不可核验计数)``。

    ★★ 守恒陷阱（20261028 首跑踩到）
      不可核验的标的**仍在存活列表里**，因此绝不能再把它记进 ``dropped`` ——
      否则归因矩阵会出现「同一只票既被记淘汰又在输出中」的重复计数，
      表现为 ``不守恒(差额 -6)``。它只作为**第三个返回值**用于日志与面板展示。
    """
    if not getattr(config, "TRACK_D_TREND_ENABLED", True):
        for c in passed:
            c["roe_trend"] = "DISABLED"
        return passed, {}, 0

    reject = bool(getattr(config, "TRACK_D_TREND_REJECT_DETERIORATING", True))
    kept: list[dict[str, Any]] = []
    dropped: dict[str, int] = {}
    unverified = 0

    for c in passed:
        trend = trends.get(str(c.get("code") or "").zfill(6))
        if trend is None or not trend.verified:
            c["roe_trend"] = "UNVERIFIED"
            c["profit_yoy_pct"] = None
            c["profit_yoy_delta_pp"] = None
            c["roe_pct_f10"] = None
            c["trend_report_date"] = None
            unverified += 1          # ★ 只计数，不计入 dropped
            kept.append(c)
            continue

        c["roe_trend"] = trend.trend
        c["profit_yoy_pct"] = trend.yoy_pct
        c["profit_yoy_delta_pp"] = trend.yoy_delta_pp
        c["roe_pct_f10"] = trend.roe_pct
        c["trend_report_date"] = trend.report_date

        if reject and trend.trend == "decelerating":
            dropped[D_TREND_DETERIORATING] = dropped.get(D_TREND_DETERIORATING, 0) + 1
            continue
        kept.append(c)

    return kept, dropped, unverified


def _track_d_playbook(c: dict[str, Any]) -> dict[str, Any]:
    """轨道 D 战术：左侧分批建仓，安全边际优先。"""
    close = _opt_float(c.get("close")) or 0.0
    max_pos = int(round(config.TRACK_D_MAX_POSITION_PCT * 100))
    base_pos = int(round(max_pos * 0.4))

    pb = ExecutionPlaybook(
        action="BUY",
        action_label="🛡️ 安全边际左侧分批",
        entry_tactic=(
            "【左侧分批建仓】估值双锚已进入合理区间且利润有现金支撑，"
            "按 4:3:3 分三批建仓，每下跌一档加一批；不追涨、不打板"
        ),
        entry_price_range=f"建仓区间: {round(close * 0.90, 2)} ~ {round(close * 1.00, 2)} 元",
        base_position_pct=base_pos,
        add_position_pct=max_pos - base_pos,
        max_position_pct=max_pos,
        take_profit_target="估值修复至行业中位数即分批止盈，不贪最后一波",
        stop_loss_line=f"跌破建仓成本 12% 或基本面证伪（现金流转负）",
        invalidation_rule=(
            "价值陷阱防线: 若最新报告期经营现金流转负、或应收账款与存货同比暴增逾 50%，"
            "视为低估值系财务失真所致，立即清仓而非补仓"
        ),
    )
    return {
        "playbook": pb,
        "action": "buyable",
        "action_desc": "价值成长：估值双锚合理 + ROE 达标 + 利润有现金支撑",
    }
