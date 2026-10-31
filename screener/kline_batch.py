"""日 K 线批量吞吐与技术指标派生。

★ 为什么单独成模块
-------------------
轨道 B（近 3 日曾涨停 + 缩量不破 MA5）与轨道 C（均线多头 + 20 日日均成交额）
都需要日 K，而日 K 是本项目**最贵的数据源**：

    20261028 实测：bars.get 约 **26ms/只，且与请求根数无关**
      · 200 只 × count=6  → 5.22s
      · 200 只 × count=70 → 5.38s
      ⇒ 全市场 5225 只 ≈ **130s**

所以本模块的第一职责不是"取数"，而是**把 26ms/只 的成本挡在候选压缩之后**：
调用方必须先用 `stock_profile_table` 的免费字段（市值/换手/成交额/涨跌幅）把
候选压到数百只，再调本模块懒加载。任何"全市场拉日 K"的设计都会被成本否决。

★ 数据纪律 (NFR-02)
-------------------
* K 线不足（次新、长期停牌、取数失败）时技术指标一律返回 ``None``，
  **绝不返回 0.0 或伪装的 MA** —— 否则"MA5=0"会让"收盘 > MA5"恒真，
  把数据缺失伪装成利好信号。
* 批次失败的标的记为 ``BARS_MISSING``，由调用方计入归因矩阵，不静默丢弃。
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import Any, Iterable, Sequence

import config

logger = logging.getLogger("ast_trader.screener.kline")


@dataclass(frozen=True)
class Bar:
    """归一化后的日 K（屏蔽 eltdx 的 milli / raw 计价差异）。"""

    date: str
    open: float
    high: float
    low: float
    close: float
    #: 前收盘（用于判定当日是否涨停）
    pre_close: float
    #: 成交额（元）
    amount: float
    #: 成交量（手）
    volume_lots: float

    @property
    def pct_chg(self) -> float | None:
        """当日涨跌幅 (%)。前收盘不可得时为 ``None``。"""
        if not self.pre_close:
            return None
        return (self.close / self.pre_close - 1.0) * 100.0

    @property
    def vwap(self) -> float | None:
        """当日均价（VWAP 代理值）= 成交额 / (手数 × 100)。"""
        if not self.volume_lots:
            return None
        return self.amount / (self.volume_lots * 100.0)


def _opt_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(f) or math.isinf(f) else f


def _to_bar(raw: Any) -> Bar | None:
    """把 eltdx ``KlineBar`` 归一化；关键字段缺失则返回 ``None``。"""
    close = _opt_float(getattr(raw, "close", None))
    if close is None:
        return None
    # 优先用 milli 计价还原前收盘（close_price_milli = price * 1000）
    pre_milli = _opt_float(getattr(raw, "last_close_price_milli", None))
    pre_close = pre_milli / 1000.0 if pre_milli else None

    t = getattr(raw, "time", None)
    date_txt = t.date().isoformat() if hasattr(t, "date") else str(t or "")

    return Bar(
        date=date_txt,
        open=_opt_float(getattr(raw, "open", None)) or close,
        high=_opt_float(getattr(raw, "high", None)) or close,
        low=_opt_float(getattr(raw, "low", None)) or close,
        close=close,
        pre_close=pre_close or 0.0,
        amount=_opt_float(getattr(raw, "amount", None)) or 0.0,
        volume_lots=_opt_float(getattr(raw, "volume_lots", None)) or 0.0,
    )


def chunk_codes(codes: Sequence[str], batch_size: int) -> list[list[str]]:
    size = max(1, int(batch_size))
    return [list(codes[i:i + size]) for i in range(0, len(codes), size)]


def fetch_daily_bars(
    full_codes: Iterable[str],
    *,
    count: int = 70,
    batch_size: int | None = None,
    adjust: str | None = "qfq",
    health: Any | None = None,
) -> tuple[dict[str, list[Bar]], dict[str, Any]]:
    """批量拉取日 K（升序，末位为最新交易日）。

    返回 ``(full_code -> [Bar], stats)``。
    批次失败 / 单只返回空序列 → 该代码不出现在结果中，计入 ``stats["missing_codes"]``。
    """
    from data.eltdx_client import open_client, with_retry

    codes = [str(c).strip().lower() for c in full_codes if c]
    size = batch_size or getattr(config, "KLINE_BATCH_SIZE", 50)
    batches = chunk_codes(codes, size)

    stats: dict[str, Any] = {
        "requested": len(codes),
        "returned": 0,
        "missing": 0,
        "missing_codes": [],
        "failed_batches": 0,
        "batches": len(batches),
        "count": count,
    }
    result: dict[str, list[Bar]] = {}
    if not codes:
        return result, stats

    try:
        with open_client() as client:
            for idx, batch in enumerate(batches, start=1):
                try:
                    series_map = with_retry(
                        lambda b=batch: client.bars.get(b, period="day", count=count, adjust=adjust),
                        what=f"bars.get(batch {idx}/{len(batches)}, n={len(batch)}, count={count})",
                    )
                except Exception as exc:  # noqa: BLE001
                    stats["failed_batches"] += 1
                    stats["missing_codes"].extend(batch)
                    logger.warning(
                        f"日K批次 {idx}/{len(batches)} 拉取失败（{len(batch)} 只记为 "
                        f"{config.KLINE_MISSING_REASON}，不静默剔除）: {type(exc).__name__}: {exc}"
                    )
                    continue

                for code, series in (series_map or {}).items():
                    raw_bars = list(getattr(series, "bars", None) or [])
                    bars: list[Bar] = []
                    for raw in raw_bars:
                        b = _to_bar(raw)
                        if b is not None:
                            bars.append(b)
                    if bars:
                        result[str(code).strip().lower()] = bars
                    else:
                        stats["missing_codes"].append(str(code).strip().lower())
    except Exception as exc:  # noqa: BLE001
        logger.error(f"日K吞吐整体失败: {type(exc).__name__}: {exc}", exc_info=True)
        stats["missing_codes"] = list(codes)

    seen = set(result)
    stats["missing_codes"] = [c for c in codes if c not in seen]
    stats["returned"] = len(result)
    stats["missing"] = len(stats["missing_codes"])

    if health is not None and stats["returned"]:
        try:
            if stats["failed_batches"]:
                health.record_degraded(
                    "全市场日K", "eltdx.bars.get",
                    f"{stats['failed_batches']}/{stats['batches']} 批次失败，{stats['missing']} 只未取到日K",
                )
            else:
                health.record_success("全市场日K", "eltdx.bars.get", stats["returned"])
        except Exception:  # noqa: BLE001
            logger.debug("日K健康度记账失败（已忽略）")

    logger.info(
        f"日K吞吐完成: 请求 {stats['requested']} 只 / 取到 {stats['returned']} 只 / "
        f"缺失 {stats['missing']} 只 (失败批次 {stats['failed_batches']}/{stats['batches']})"
    )
    return result, stats


# ───────────────────────────────────────────────────── 技术指标
def ma(bars: Sequence[Bar], period: int) -> float | None:
    """简单移动平均。K 线根数不足时返回 ``None``（**不是 0.0**）。"""
    if not bars or period <= 0 or len(bars) < period:
        return None
    window = bars[-period:]
    vals = [b.close for b in window if b.close is not None]
    if len(vals) < period:
        return None
    return sum(vals) / float(period)


def avg_amount(bars: Sequence[Bar], period: int) -> float | None:
    """近 ``period`` 日日均成交额。根数不足返回 ``None``。"""
    if not bars or period <= 0 or len(bars) < period:
        return None
    window = [b.amount for b in bars[-period:] if b.amount is not None]
    if len(window) < period:
        return None
    return sum(window) / float(period)


def volume_ratio(bars: Sequence[Bar]) -> float | None:
    """今日量 / 昨日量。昨日无量（0）时返回 ``None``（除零会伪装成"无量"）。"""
    if len(bars) < 2:
        return None
    prev = bars[-2].volume_lots
    if not prev:
        return None
    return bars[-1].volume_lots / prev


def was_limit_up(bar: Bar, board_kind: str | None = None) -> bool:
    """是否达到封板涨幅（主板 9.5% / 双创 19.5%）。"""
    pct = bar.pct_chg
    if pct is None:
        return False
    return pct >= (19.5 if board_kind == "growth" else 9.5)


def recent_limit_up_days(bars: Sequence[Bar], lookback: int, board_kind: str | None = None) -> int | None:
    """近 ``lookback`` 个交易日（不含今日）中出现封板的天数。

    K 线不足 → ``None``（不可核验），**不是 0**。
    """
    if not bars or lookback <= 0:
        return None
    # 末位为今日，往前推 lookback 根
    window = bars[-(lookback + 1):-1] if len(bars) > lookback else bars[:-1]
    if not window:
        return None
    return sum(1 for b in window if was_limit_up(b, board_kind))


def bullish_ma_stack(bars: Sequence[Bar], periods: Sequence[int] = (5, 20, 60)) -> bool | None:
    """多头排列：``Close > MA(p1) > MA(p2) > ...``。任一均线不可得 → ``None``（弃权）。"""
    if not bars:
        return None
    close = bars[-1].close
    if close is None:
        return None
    mas: list[float] = []
    for p in periods:
        v = ma(bars, p)
        if v is None:
            return None
        mas.append(v)
    if close <= mas[0]:
        return False
    return all(mas[i] > mas[i + 1] for i in range(len(mas) - 1))


def vwap_deviation(bars: Sequence[Bar]) -> float | None:
    """``现价 / 当日均价 - 1``。正=高于均价（承接强），负=低于均价（抛压重）。"""
    if not bars:
        return None
    last = bars[-1]
    vwap = last.vwap
    if not vwap:
        return None
    return last.close / vwap - 1.0
