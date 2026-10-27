"""Supplementary data for AST-Trader: Dragon-Tiger list (LHB) and news/sentiment."""
from __future__ import annotations

import logging
from typing import Any

import requests

logger = logging.getLogger("ast_trader.data.supplement")


def fetch_lhb_seats(num_code: str) -> list[dict[str, Any]]:
    """拉取近 30 天龙虎榜上榜明细。若失败或无数据返回空列表。"""
    url = "https://datacenter-web.eastmoney.com/api/data/v1/get"
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
                    seats.append({
                        "trade_date": str(row.get("TRADE_DATE", ""))[:10],
                        "seat_name": row.get("OPERATEDEPT_NAME", ""),
                        "buy_amt": float(row.get("BUY_AMT") or 0.0),
                        "sell_amt": float(row.get("SELL_AMT") or 0.0),
                        "net_amt": float(row.get("NET_AMT") or 0.0),
                    })
                return seats
    except Exception as e:
        logger.debug(f"获取龙虎榜席位降级跳过: {e}")
    return []
