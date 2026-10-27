"""Supplementary data for AST-Trader: Dragon-Tiger list (LHB) and news/sentiment."""
from __future__ import annotations

from datetime import datetime, timedelta
import logging
from typing import Any

import requests

logger = logging.getLogger("ast_trader.data.supplement")


def fetch_realtime_supplement(num_code: str, health: Any | None = None) -> dict[str, Any]:
    """通过极速行情快照接口拉取真实中文证券名称、PE(TTM) 与 PB 补充信息。"""
    prefix = "sh" if num_code.startswith("6") else ("bj" if num_code.startswith(("4", "8", "920")) else "sz")
    url = f"http://qt.gtimg.cn/q={prefix}{num_code}"
    try:
        r = requests.get(url, timeout=3.0, headers={"User-Agent": "Mozilla/5.0"})
        if r.status_code == 200:
            text = r.content.decode("gbk", errors="ignore")
            if "~" in text:
                parts = text.split("~")
                if len(parts) > 46:
                    res = {
                        "name": parts[1].strip(),
                        "code": parts[2].strip(),
                        "price": float(parts[3] or 0.0),
                        "pe_ttm": float(parts[39] or 0.0),
                        "pb": float(parts[46] or 0.0),
                    }
                    if health:
                        health.record_success("腾讯极速行情快照", "qt.gtimg.cn", 1)
                    return res
        if health:
            health.record_empty("腾讯极速行情快照", "qt.gtimg.cn", f"状态码: {r.status_code}，响应无标的数据")
    except Exception as e:
        logger.warning(f"获取实时补充行情失败: {e}")
        if health:
            health.record_failure("腾讯极速行情快照", "qt.gtimg.cn", e)
    return {}


def fetch_holder_flow(num_code: str, health: Any | None = None) -> dict[str, Any]:
    """获取最新一期股东户数及其环比变动率 (检测筹码集中还是分散)."""
    url = "https://datacenter-web.eastmoney.com/api/data/v1/get"
    params = {
        "reportName": "RPT_F10_EH_HOLDERNUM",
        "columns": "ALL",
        "filter": f'(SECURITY_CODE="{num_code}")',
        "pageNumber": 1,
        "pageSize": 2,
        "sortTypes": "-1",
        "sortColumns": "END_DATE",
        "source": "WEB",
        "client": "WEB",
    }
    try:
        r = requests.get(url, params=params, timeout=3.0, headers={"User-Agent": "Mozilla/5.0"})
        if r.status_code == 200:
            res = r.json().get("result")
            if res and res.get("data"):
                latest = res["data"][0]
                data = {
                    "holder_count": latest.get("HOLDER_TOTAL_NUM"),
                    "holder_change_pct": float(latest.get("CHANGEWITHLAST") or latest.get("TOTAL_NUM_RATIO") or 0.0),
                    "end_date": str(latest.get("END_DATE", ""))[:10],
                }
                if health:
                    health.record_success("东方财富股东户数", "eastmoney.RPT_F10_EH_HOLDERNUM", 1)
                return data
        if health:
            health.record_empty("东方财富股东户数", "eastmoney.RPT_F10_EH_HOLDERNUM", f"状态码: {r.status_code}，无股东户数记录")
    except Exception as e:
        logger.warning(f"获取股东户数变动失败: {e}")
        if health:
            health.record_failure("东方财富股东户数", "eastmoney.RPT_F10_EH_HOLDERNUM", e)
    return {}


def fetch_lhb_seats(num_code: str, days: int = 30, health: Any | None = None) -> list[dict[str, Any]]:
    """拉取近 30 个自然日内真实的龙虎榜上榜席位明细。严格按日期窗口过滤，杜绝历史陈旧数据。"""
    url = "https://datacenter-web.eastmoney.com/api/data/v1/get"
    cutoff_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    params = {
        "reportName": "RPT_DAILYBILLBOARD_DETAILS",
        "columns": "SECURITY_CODE,SECUCODE,TRADE_DATE,OPERATEDEPT_NAME,BUY_AMT,SELL_AMT,NET_AMT,D1_CLOSE_ADJCHRATE",
        "filter": f'(SECURITY_CODE="{num_code}")',
        "pageNumber": 1,
        "pageSize": 50,
        "sortTypes": "-1",
        "sortColumns": "TRADE_DATE",
        "source": "WEB",
        "client": "WEB",
    }
    try:
        r = requests.get(url, params=params, timeout=4.0, headers={"User-Agent": "Mozilla/5.0"})
        if r.status_code == 200:
            data = r.json()
            result = data.get("result")
            if result and result.get("data"):
                seats = []
                for row in result["data"]:
                    t_date = str(row.get("TRADE_DATE", ""))[:10]
                    if t_date < cutoff_date:
                        continue
                    seats.append({
                        "trade_date": t_date,
                        "seat_name": row.get("OPERATEDEPT_NAME", ""),
                        "buy_amt": float(row.get("BUY_AMT") or 0.0),
                        "sell_amt": float(row.get("SELL_AMT") or 0.0),
                        "net_amt": float(row.get("NET_AMT") or 0.0),
                    })
                if health:
                    health.record_success("东方财富龙虎榜席位", "eastmoney.RPT_DAILYBILLBOARD_DETAILS", len(seats))
                return seats
            else:
                if health:
                    health.record_empty("东方财富龙虎榜席位", "eastmoney.RPT_DAILYBILLBOARD_DETAILS", "近30日无龙虎榜上榜记录")
                return []
        if health:
            health.record_empty("东方财富龙虎榜席位", "eastmoney.RPT_DAILYBILLBOARD_DETAILS", f"状态码: {r.status_code}")
    except Exception as e:
        logger.warning(f"获取龙虎榜席位异常: {e}")
        if health:
            health.record_failure("东方财富龙虎榜席位", "eastmoney.RPT_DAILYBILLBOARD_DETAILS", e)
    return []
