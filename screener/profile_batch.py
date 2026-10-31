"""沪深全市场的行情画像批量吞吐器 (L1)。

★ 为什么必须有这个模块（以及为什么不能用 ``quotes.get_snapshots``）
--------------------------------------------------------------------
改造前 Tier 1 的换手率门槛（8%~25%）是一条**死代码**：``pipeline._fetch_quotes_map``
只把 ``{close, pre_close, pct_chg, amount}`` 四个键装进快照字典，而
``filter_liquidity`` 读的是 ``turnover_ratio`` —— 恒为 0.0，``if turnover > 0.0``
恒 False，这条规则写了、配了、打日志了，却从未拦下过任何一只票。

根因是 ``eltdx.models.quote.QuoteSnapshot`` **根本没有** ``turnover_ratio`` /
``total_mv`` / 量比字段，不是调用方取错了键。

``helpers.stock_profile_table`` 一次调用即可给出：
``turnover_rate / total_market_value / circulating_market_value / ipo_date /
board / category / amount / change_pct / OHLC`` —— 正是阶段1 需要的全部字段。

★ 20261028 压测：单次 200 只耗时 0.32s，返回 200 行（199 行换手率与上市日期非空，
  1 行确为停牌）。全市场 5225 只 ≈ 26 批，实测整体 10~30s。

★ 数据纪律 (NFR-02)
-------------------
* 缺失字段一律 ``None``，严禁 ``or 0.0``。
* 批次失败 ≠ 该批标的"不合格"：记为 ``PROFILE_MISSING`` 并计入覆盖率缺口，
  **绝不静默缩小母池**——否则"全市场"会悄悄退化成"跑成功的那部分市场"。
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

import config

logger = logging.getLogger("ast_trader.screener.profile_batch")


@dataclass(frozen=True)
class ProfileSnapshot:
    """一只标的的行情画像快照。所有字段均可为 ``None``（未核验）。"""

    full_code: str
    code: str | None = None
    name: str | None = None
    exchange: str | None = None
    board: str | None = None
    category: str | None = None

    last_price: float | None = None
    pre_close: float | None = None
    open_price: float | None = None
    high_price: float | None = None
    low_price: float | None = None
    change_pct: float | None = None
    amount: float | None = None
    volume_hand: float | None = None

    #: 换手率（%）。★ 这是修好 Tier 1 死代码的关键字段。
    turnover_rate: float | None = None
    circulating_shares: float | None = None
    total_shares: float | None = None
    circulating_market_value: float | None = None
    total_market_value: float | None = None
    eps: float | None = None
    #: 上市日期。代码表不提供，只有这里能拿到，次新剔除依赖它。
    ipo_date: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "full_code": self.full_code,
            "code": self.code,
            "name": self.name,
            "change_pct": self.change_pct,
            "amount": self.amount,
            "turnover_rate": self.turnover_rate,
            "total_market_value": self.total_market_value,
            "circulating_market_value": self.circulating_market_value,
            "board": self.board,
            "ipo_date": self.ipo_date,
        }


def _opt_float(value: Any) -> float | None:
    """转 float；None / 不可解析 / NaN 一律返回 ``None``（严禁 ``or 0.0``）。"""
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(f) or math.isinf(f) else f


def _opt_str(value: Any) -> str | None:
    if value is None:
        return None
    txt = str(value).strip()
    return txt or None


def _row_to_snapshot(row: Any) -> ProfileSnapshot | None:
    """把 ``StockProfile`` 转成 :class:`ProfileSnapshot`；无完整代码则丢弃。"""
    full_code = _opt_str(getattr(row, "full_code", None))
    if not full_code:
        return None
    return ProfileSnapshot(
        full_code=full_code.lower(),
        code=_opt_str(getattr(row, "code", None)),
        name=_opt_str(getattr(row, "name", None)),
        exchange=_opt_str(getattr(row, "exchange", None)),
        board=_opt_str(getattr(row, "board", None)),
        category=_opt_str(getattr(row, "category", None)),
        last_price=_opt_float(getattr(row, "last_price", None)),
        pre_close=_opt_float(getattr(row, "pre_close_price", None)),
        open_price=_opt_float(getattr(row, "open_price", None)),
        high_price=_opt_float(getattr(row, "high_price", None)),
        low_price=_opt_float(getattr(row, "low_price", None)),
        change_pct=_opt_float(getattr(row, "change_pct", None)),
        amount=_opt_float(getattr(row, "amount", None)),
        volume_hand=_opt_float(getattr(row, "volume_hand", None)),
        turnover_rate=_opt_float(getattr(row, "turnover_rate", None)),
        circulating_shares=_opt_float(getattr(row, "circulating_shares", None)),
        total_shares=_opt_float(getattr(row, "total_shares", None)),
        circulating_market_value=_opt_float(getattr(row, "circulating_market_value", None)),
        total_market_value=_opt_float(getattr(row, "total_market_value", None)),
        eps=_opt_float(getattr(row, "eps", None)),
        ipo_date=_opt_str(getattr(row, "ipo_date", None)),
    )


def chunk_codes(codes: Sequence[str], batch_size: int) -> list[list[str]]:
    """按 ``batch_size`` 切批（纯函数，离线可测）。"""
    size = max(1, int(batch_size))
    return [list(codes[i:i + size]) for i in range(0, len(codes), size)]


def fetch_profiles(
    full_codes: Iterable[str],
    *,
    batch_size: int | None = None,
    health: Any | None = None,
) -> tuple[dict[str, ProfileSnapshot], dict[str, Any]]:
    """批量拉取行情画像。

    返回 ``(full_code -> ProfileSnapshot, stats)``。

    ``stats`` 键：
        ``requested`` / ``returned`` / ``missing`` / ``missing_codes`` /
        ``failed_batches`` / ``batches``

    ★ 批次失败时对应代码**不出现在返回字典中**，由调用方按 ``stats["missing"]``
      计入覆盖率缺口并打 ``PROFILE_MISSING`` 剔除码 —— 严禁静默缩小母池。
    """
    from data.eltdx_client import open_client, with_retry

    codes = [str(c).strip().lower() for c in full_codes if c]
    size = batch_size or getattr(config, "UNIVERSE_PROFILE_BATCH_SIZE", 200)
    batches = chunk_codes(codes, size)

    stats: dict[str, Any] = {
        "requested": len(codes),
        "returned": 0,
        "missing": 0,
        "missing_codes": [],
        "failed_batches": 0,
        "batches": len(batches),
        "batch_size": size,
    }
    mapping: dict[str, ProfileSnapshot] = {}

    if not codes:
        return mapping, stats

    try:
        with open_client() as client:
            for idx, batch in enumerate(batches, start=1):
                try:
                    table = with_retry(
                        lambda b=batch: client.helpers.stock_profile_table(b),
                        what=f"helpers.stock_profile_table(batch {idx}/{len(batches)}, n={len(batch)})",
                    )
                except Exception as exc:  # noqa: BLE001
                    stats["failed_batches"] += 1
                    stats["missing_codes"].extend(batch)
                    logger.warning(
                        f"画像批次 {idx}/{len(batches)} 拉取失败（{len(batch)} 只记为 "
                        f"PROFILE_MISSING，不静默剔除）: {type(exc).__name__}: {exc}"
                    )
                    if health is not None:
                        try:
                            health.record_failure(
                                "全市场行情画像批次",
                                "eltdx.helpers.stock_profile_table",
                                exc,
                                note=f"批次 {idx}/{len(batches)} 共 {len(batch)} 只未取得画像",
                            )
                        except Exception:  # noqa: BLE001
                            logger.debug("画像批次健康度记账失败（已忽略）")
                    continue

                for row in getattr(table, "rows", None) or []:
                    snap = _row_to_snapshot(row)
                    if snap is not None:
                        mapping[snap.full_code] = snap
    except Exception as exc:  # noqa: BLE001  连接层整体不可用
        logger.error(f"画像吞吐整体失败: {type(exc).__name__}: {exc}", exc_info=True)
        stats["missing_codes"] = list(codes)

    seen = set(mapping)
    stats["missing_codes"] = [c for c in codes if c not in seen]
    stats["returned"] = len(mapping)
    stats["missing"] = len(stats["missing_codes"])

    if health is not None and stats["returned"]:
        try:
            if stats["failed_batches"]:
                health.record_degraded(
                    "全市场行情画像",
                    "eltdx.helpers.stock_profile_table",
                    f"{stats['failed_batches']}/{stats['batches']} 批次失败，"
                    f"{stats['missing']} 只未取得画像",
                )
            else:
                health.record_success("全市场行情画像", "eltdx.helpers.stock_profile_table", stats["returned"])
        except Exception:  # noqa: BLE001
            logger.debug("画像健康度记账失败（已忽略）")

    logger.info(
        f"行情画像吞吐完成: 请求 {stats['requested']} 只 / 取到 {stats['returned']} 只 / "
        f"缺失 {stats['missing']} 只 (失败批次 {stats['failed_batches']}/{stats['batches']})"
    )
    return mapping, stats
