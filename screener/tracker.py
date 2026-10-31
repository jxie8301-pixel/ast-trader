"""选股实盘追踪账本与次日胜率复盘器。

★ 20261029 审计 P0-4：本模块的收益口径被整体重写过一次。旧实现有三处硬伤，
  共同结果是**胜率被系统性高估**：

  1. **买入基准错误**：用「选出日收盘价」算收益 —— 可那天收盘时人还没下单，
     次日开盘能不能按这个价成交根本不保证（一字涨停开盘直接买不到）。
     现改为**次日开盘价买入、次日收盘价卖出**，这才是可执行口径。
  2. **不可成交样本仍进胜率分母**：一字涨停/跌停的标的开盘即封死，全天无法成交，
     旧实现照样按"涨了/跌了"计入胜率。现标记 `UNFILLABLE` 并**剔出胜率分母**，
     单独统计（买不到的票不能算赢，也不能算输）。
  3. **零交易成本**：印花税、佣金、过户费一律未计。现按 config 中的费率模型
     扣除双边成本后再判胜负。

  另补齐：按 `(report_id, code)` **去重**（旧实现重复跑会重复落账，样本被反复计入），
  以及**四轨分别落账与分轨胜率**（旧实现只记轨道 A，B/C/D 的选股永远无法复盘）。
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

import config
from data.eltdx_collector import EltdxCollector

logger = logging.getLogger("ast_trader.tracker")

TRACKER_PATH = config.CACHE_DIR / "screener_tracker.jsonl"

#: 不可成交（剔除出胜率分母）的状态
STATUS_UNFILLABLE = "UNFILLABLE"
#: 尚无 T+1 行情
STATUS_WAITING = "WAITING_NEXT_DAY"
#: 已完成测算
STATUS_COMPLETED = "COMPLETED"
#: 行情缺失，无法核验（同样不计入胜率）
STATUS_NO_DATA = "NO_DATA"


def round_trip_fee_pct(amount_yuan: float | None = None) -> float:
    """一次完整买卖（T+1 买、T+1 卖）的交易成本，折算成**百分比**。

    成本 = 双边佣金（万 2.5，单笔最低 5 元）+ 卖出印花税 0.05% + 双边过户费 0.001%。
    固定费用（佣金下限 5 元）使得小额交易的百分比成本更高 —— 这正是必须给出
    名义成交额假设的原因（``config.TRACKER_ASSUMED_AMOUNT_YUAN``）。
    """
    amt = float(amount_yuan or config.TRACKER_ASSUMED_AMOUNT_YUAN)
    if amt <= 0:
        return 0.0
    commission = max(amt * config.TRACKER_COMMISSION_PCT / 100.0, config.TRACKER_COMMISSION_MIN_YUAN)
    fees = (
        commission * 2.0                                       # 买 + 卖
        + amt * config.TRACKER_STAMP_DUTY_PCT / 100.0          # 卖出印花税
        + amt * config.TRACKER_TRANSFER_FEE_PCT / 100.0 * 2.0  # 双边过户费
    )
    return round(fees / amt * 100.0, 4)


def _existing_keys() -> set[tuple[str, str]]:
    """已落账的 `(report_id, code)` 集合 —— 用于去重。"""
    keys: set[tuple[str, str]] = set()
    if not TRACKER_PATH.exists():
        return keys
    try:
        with open(TRACKER_PATH, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except Exception:
                    continue
                keys.add((str(rec.get("report_id") or ""), str(rec.get("code") or "")))
    except Exception as exc:                                    # noqa: BLE001
        logger.warning(f"读取选股账本失败（按空账本处理）: {exc}")
    return keys


def record_screen_picks(
    picks: list[dict[str, Any]],
    mode: str = "close",
    *,
    track: str | None = None,
    trade_date: str | None = None,
) -> int:
    """将每日选出的精选标的追加写入实盘追踪账本。

    ★ 去重：同一 `(report_id, code)` 只记一次 —— 旧实现无去重，同一天跑两次
      screen 就会把同一批标的重复计入样本，胜率统计被自己污染。
    ★ 落 `track`：四轨统一入账，才能算分轨胜率（旧实现只记轨道 A）。
    """
    if not picks:
        return 0

    TRACKER_PATH.parent.mkdir(parents=True, exist_ok=True)
    today_str = trade_date or datetime.now().strftime("%Y%m%d")
    report_id = f"SCREEN_{today_str}_{mode.upper()}"
    ts_now = datetime.now().isoformat()

    existing = _existing_keys()
    lines: list[str] = []
    skipped = 0
    for rank, p in enumerate(picks, start=1):
        code = str(p.get("code", "") or "")
        if not code:
            continue
        if (report_id, code) in existing:
            skipped += 1
            continue
        existing.add((report_id, code))

        pb = p.get("playbook")
        entry = {
            "report_id": report_id,
            "created_at": ts_now,
            "trade_date": today_str,
            "mode": mode,
            "track": track or p.get("track") or "",
            "rank": rank,
            "code": code,
            "name": p.get("name", ""),
            # ★ 选出日收盘价：只作**参考价**（用于展示当日涨幅、及与次日开盘比价），
            #   不再是收益计算基准 —— 收益一律以次日开盘价成交为准。
            "close": p.get("close", 0.0),
            "pct_chg": p.get("pct_chg", 0.0),
            "action": p.get("action", ""),
            "main_net_wan": p.get("main_net_wan", 0.0),
            "matched_personas": p.get("matched_personas", []),
            "entry_tactic": getattr(pb, "entry_tactic", ""),
            "stop_loss_line": getattr(pb, "stop_loss_line", ""),
            "invalidation_rule": getattr(pb, "invalidation_rule", ""),
        }
        lines.append(json.dumps(entry, ensure_ascii=False) + "\n")

    if not lines:
        if skipped:
            logger.info(f"{report_id} 的 {skipped} 条记录已存在（去重跳过），未新增")
        return 0

    try:
        with open(TRACKER_PATH, "a", encoding="utf-8") as f:
            f.writelines(lines)
        logger.info(
            f"成功将 {len(lines)} 条选股记录追加至追踪账本: {TRACKER_PATH}"
            + (f"（去重跳过 {skipped} 条）" if skipped else "")
        )
        return len(lines)
    except Exception as e:                                      # noqa: BLE001
        logger.warning(f"写入选股账本失败: {e}")
        return 0


def load_tracker_records() -> list[dict[str, Any]]:
    """读取历史所有选股跟踪记录。"""
    if not TRACKER_PATH.exists():
        return []

    records = []
    with open(TRACKER_PATH, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    records.append(json.loads(line))
                except Exception:
                    pass
    return records


def _is_one_word_bar(bar: Any) -> bool:
    """是否一字板（开盘即封死、全天只有一个价格）→ 无法在开盘后成交。"""
    try:
        return float(bar["high"]) <= float(bar["low"])
    except Exception:                                           # noqa: BLE001
        return False


def _measure(rec: dict[str, Any], collector: EltdxCollector, today_str: str) -> dict[str, Any]:
    """单条记录的 T+1 测算：次日开盘买入、次日收盘卖出，扣费后判胜负。"""
    pick_date = str(rec.get("trade_date", "") or "")
    code = str(rec.get("code", "") or "")

    if not code:
        return {**rec, "status": STATUS_NO_DATA, "t1_return_pct": None}
    if pick_date >= today_str:
        return {
            **rec, "status": STATUS_WAITING, "next_date": "待交易日走完",
            "t1_return_pct": None, "t1_runup_pct": None, "t1_drawdown_pct": None,
        }

    # ★ 20261029 审计 §3.3：收益核算必须走**不复权真实成交价**（adjust=None）——
    #   复权价是历史价格，用它算收益等于假装用昨天的价格成交，账本全是假的。
    df = collector.get_daily(code, count=20, adjust=None)
    if df.empty or len(df) < 2:
        return {**rec, "status": STATUS_NO_DATA, "t1_return_pct": None}

    df = df.copy()
    df["trade_date"] = df["trade_date"].astype(str)
    df = df.sort_values("trade_date", ascending=True).reset_index(drop=True)
    match_idx = df[df["trade_date"] == pick_date].index
    if len(match_idx) == 0:
        return {**rec, "status": STATUS_NO_DATA, "t1_return_pct": None}

    idx = match_idx[0]
    if idx + 1 >= len(df):
        return {
            **rec, "status": STATUS_WAITING, "next_date": "待下一个交易日",
            "t1_return_pct": None, "t1_runup_pct": None, "t1_drawdown_pct": None,
        }

    next_bar = df.iloc[idx + 1]
    next_date = str(next_bar["trade_date"])
    next_open = float(next_bar["open"])

    # ★ 一字板（含一字涨停/跌停）：开盘即封死，全天无法成交 → 剔出胜率分母。
    #   旧实现把这类样本照常计入，等于把"买不到的涨停"算成自己的胜绩。
    if _is_one_word_bar(next_bar):
        return {
            **rec, "status": STATUS_UNFILLABLE, "next_date": next_date,
            "next_open": next_open,
            "unfillable_reason": "一字板（开盘即封死，全天无法成交）",
            "t1_return_pct": None, "t1_runup_pct": None, "t1_drawdown_pct": None,
        }
    if next_open <= 0:
        return {**rec, "status": STATUS_NO_DATA, "next_date": next_date, "t1_return_pct": None}

    next_high = float(next_bar["high"])
    next_low = float(next_bar["low"])
    next_close = float(next_bar["close"])
    fee_pct = round_trip_fee_pct()

    # ★ 基准 = 次日开盘价（真实可成交价），不再是选出日收盘价
    gross = (next_close - next_open) / next_open * 100.0
    net = gross - fee_pct

    return {
        **rec,
        "status": STATUS_COMPLETED,
        "next_date": next_date,
        "next_open": next_open,
        "next_high": next_high,
        "next_low": next_low,
        "next_close": next_close,
        # 参考口径：与选出日收盘价的偏移（仅作对照，不用于判胜负）
        "open_gap_pct": round((next_open - float(rec.get("close") or 0.0))
                              / float(rec.get("close") or 1.0) * 100.0, 2) if rec.get("close") else None,
        "t1_return_pct": round(net, 2),
        "t1_return_gross_pct": round(gross, 2),
        "t1_fee_pct": fee_pct,
        "t1_runup_pct": round((next_high - next_open) / next_open * 100.0, 2),
        "t1_drawdown_pct": round((next_low - next_open) / next_open * 100.0, 2),
        "is_win": net > 0,
    }


def _summarize(details: list[dict[str, Any]]) -> dict[str, Any]:
    """按一组已完成样本汇总胜率/盈亏比。

    ★ 分母只含 `COMPLETED`：不可成交（`UNFILLABLE`）与无数据（`NO_DATA`）
      既不算赢也不算输 —— 把它们塞进分母才是旧版胜率虚高的根源之一。
    """
    completed = [x for x in details if x.get("status") == STATUS_COMPLETED]
    n = len(completed)
    wins = sum(1 for x in completed if x.get("is_win"))
    rets = [float(x.get("t1_return_pct") or 0.0) for x in completed]
    gross = [float(x.get("t1_return_gross_pct") or 0.0) for x in completed]
    runup = [float(x.get("t1_runup_pct") or 0.0) for x in completed]
    dd = [float(x.get("t1_drawdown_pct") or 0.0) for x in completed]

    win_rets = [r for r in rets if r > 0]
    loss_rets = [r for r in rets if r <= 0]
    avg_win = sum(win_rets) / len(win_rets) if win_rets else 0.0
    avg_loss = abs(sum(loss_rets) / len(loss_rets)) if loss_rets else 0.0

    return {
        "samples": n,
        "unfillable": sum(1 for x in details if x.get("status") == STATUS_UNFILLABLE),
        "no_data": sum(1 for x in details if x.get("status") == STATUS_NO_DATA),
        "waiting": sum(1 for x in details if x.get("status") == STATUS_WAITING),
        "win_rate_pct": round(wins / n * 100.0, 1) if n else 0.0,
        "avg_return_pct": round(sum(rets) / n, 2) if n else 0.0,
        # 毛收益（未扣费）单独给出 —— 用于对比"扣费前后"，成本是否吃掉策略一目了然
        "avg_return_gross_pct": round(sum(gross) / n, 2) if n else 0.0,
        "avg_runup_pct": round(sum(runup) / n, 2) if n else 0.0,
        "avg_drawdown_pct": round(sum(dd) / n, 2) if n else 0.0,
        "profit_loss_ratio": round(avg_win / avg_loss, 2) if avg_loss > 0 else None,
    }


def evaluate_tracker_performance(collector: EltdxCollector | None = None) -> dict[str, Any]:
    """回测复盘已选股票的次日 (T+1) 真实表现，计算实战胜率与盈亏比。"""
    records = load_tracker_records()
    if not records:
        return {
            "total_samples": 0, "evaluated_samples": 0, "win_rate_pct": 0.0,
            "avg_return_pct": 0.0, "details": [], "by_track": {},
            "unfillable": 0, "waiting": 0,
        }

    if collector is None:
        collector = EltdxCollector()

    today_str = datetime.now().strftime("%Y%m%d")
    evaluated_list: list[dict[str, Any]] = []
    for rec in records:
        try:
            evaluated_list.append(_measure(rec, collector, today_str))
        except Exception as e:                                  # noqa: BLE001
            logger.debug(f"跟踪标的 {rec.get('code', '')} 异常: {e}")
            evaluated_list.append({**rec, "status": STATUS_NO_DATA, "t1_return_pct": None})

    summary = _summarize(evaluated_list)

    # ★ 分轨胜率：四轨各自成账，才能回答"哪条轨道的结论是真的"
    by_track: dict[str, dict[str, Any]] = {}
    for tr in sorted({str(x.get("track") or "未标注") for x in evaluated_list}):
        by_track[tr] = _summarize(
            [x for x in evaluated_list if str(x.get("track") or "未标注") == tr]
        )

    return {
        "total_samples": len(records),
        "evaluated_samples": summary["samples"],
        "win_rate_pct": summary["win_rate_pct"],
        "avg_return_pct": summary["avg_return_pct"],
        "avg_return_gross_pct": summary["avg_return_gross_pct"],
        "avg_runup_pct": summary["avg_runup_pct"],
        "avg_drawdown_pct": summary["avg_drawdown_pct"],
        "profit_loss_ratio": summary["profit_loss_ratio"],
        "unfillable": summary["unfillable"],
        "waiting": summary["waiting"],
        "by_track": by_track,
        "details": evaluated_list,
    }
