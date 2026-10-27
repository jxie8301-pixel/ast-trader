"""选股实盘追踪账本与次日胜率复盘器 (严格对齐 UZI-Skill tracker.py)."""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from data.eltdx_collector import EltdxCollector

logger = logging.getLogger("ast_trader.tracker")

TRACKER_PATH = Path(".cache/screener_tracker.jsonl")


def record_screen_picks(picks: list[dict[str, Any]], mode: str = "close") -> int:
    """将每日选出的精选标的追加写入实盘追踪账本。"""
    if not picks:
        return 0

    TRACKER_PATH.parent.mkdir(parents=True, exist_ok=True)
    today_str = datetime.now().strftime("%Y%m%d")
    report_id = f"SCREEN_{today_str}_{mode.upper()}"
    ts_now = datetime.now().isoformat()

    lines = []
    for rank, p in enumerate(picks, start=1):
        pb = p.get("playbook")
        entry = {
            "report_id": report_id,
            "created_at": ts_now,
            "trade_date": today_str,
            "rank": rank,
            "code": p.get("code", ""),
            "name": p.get("name", ""),
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

    try:
        with open(TRACKER_PATH, "a", encoding="utf-8") as f:
            f.writelines(lines)
        logger.info(f"成功将 {len(lines)} 条选股记录追加至追踪账本: {TRACKER_PATH}")
        return len(lines)
    except Exception as e:
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


def evaluate_tracker_performance(collector: EltdxCollector | None = None) -> dict[str, Any]:
    """回测复盘已选股票的次日 (T+1) 真实表现，计算实战胜率与盈亏比。"""
    records = load_tracker_records()
    if not records:
        return {"total_samples": 0, "evaluated_samples": 0, "win_rate_pct": 0.0, "avg_return_pct": 0.0, "details": []}

    if collector is None:
        collector = EltdxCollector()

    today_str = datetime.now().strftime("%Y%m%d")
    evaluated_list = []
    win_count = 0
    total_return = 0.0
    total_run_up = 0.0
    total_drawdown = 0.0

    # 针对每只历史标的，获取其历史日 K 线验证次日走势
    for rec in records:
        pick_date = rec.get("trade_date", "")
        code = rec.get("code", "")
        base_price = rec.get("close", 0.0)
        if not code or not base_price or base_price <= 0:
            continue

        # 如果是今天刚刚选出的，次日行情尚未发生
        if pick_date >= today_str:
            evaluated_list.append({
                **rec,
                "status": "WAITING_NEXT_DAY",
                "next_date": "待交易日走完",
                "t1_return_pct": None,
                "t1_runup_pct": None,
                "t1_drawdown_pct": None,
            })
            continue

        try:
            df = collector.get_daily(code, count=20)
            if df.empty or len(df) < 2:
                continue

            # 确保日 K 线严格按 trade_date 升序排列，以便 idx+1 正确指向未来下一个交易日
            df["trade_date"] = df["trade_date"].astype(str)
            df = df.sort_values("trade_date", ascending=True).reset_index(drop=True)
            # 找到选出当天的索引
            match_idx = df[df["trade_date"] == pick_date].index
            if len(match_idx) == 0:
                continue

            idx = match_idx[0]
            # 选出日之后的一个交易日
            if idx + 1 < len(df):
                next_bar = df.iloc[idx + 1]
                next_date = next_bar["trade_date"]
                next_open = next_bar["open"]
                next_high = next_bar["high"]
                next_low = next_bar["low"]
                next_close = next_bar["close"]

                # 收益测算:
                # T+1 收盘收益
                t1_return = round((next_close - base_price) / base_price * 100.0, 2)
                # T+1 最大冲高幅度
                t1_runup = round((next_high - base_price) / base_price * 100.0, 2)
                # T+1 最大下探回撤
                t1_drawdown = round((next_low - base_price) / base_price * 100.0, 2)

                is_win = t1_return > 0
                if is_win:
                    win_count += 1
                total_return += t1_return
                total_run_up += t1_runup
                total_drawdown += t1_drawdown

                evaluated_list.append({
                    **rec,
                    "status": "COMPLETED",
                    "next_date": next_date,
                    "next_open": next_open,
                    "next_high": next_high,
                    "next_close": next_close,
                    "t1_return_pct": t1_return,
                    "t1_runup_pct": t1_runup,
                    "t1_drawdown_pct": t1_drawdown,
                    "is_win": is_win,
                })
            else:
                evaluated_list.append({
                    **rec,
                    "status": "WAITING_NEXT_DAY",
                    "next_date": "待下一个交易日",
                    "t1_return_pct": None,
                    "t1_runup_pct": None,
                    "t1_drawdown_pct": None,
                })
        except Exception as e:
            logger.debug(f"跟踪标的 {code} 异常: {e}")

    completed_samples = [x for x in evaluated_list if x.get("status") == "COMPLETED"]
    n_comp = len(completed_samples)
    win_rate = round(win_count / n_comp * 100.0, 1) if n_comp > 0 else 0.0
    avg_ret = round(total_return / n_comp, 2) if n_comp > 0 else 0.0
    avg_runup = round(total_run_up / n_comp, 2) if n_comp > 0 else 0.0
    avg_dd = round(total_drawdown / n_comp, 2) if n_comp > 0 else 0.0

    return {
        "total_samples": len(records),
        "evaluated_samples": n_comp,
        "win_rate_pct": win_rate,
        "avg_return_pct": avg_ret,
        "avg_runup_pct": avg_runup,
        "avg_drawdown_pct": avg_dd,
        "details": evaluated_list,
    }
