"""Supplementary data for AST-Trader: Dragon-Tiger list (LHB) and news/sentiment."""
from __future__ import annotations

from datetime import datetime, timedelta
import logging
from typing import Any

import config
import requests

logger = logging.getLogger("ast_trader.data.supplement")


def fetch_realtime_supplement(num_code: str, health: Any | None = None) -> dict[str, Any]:
    """通过极速行情快照接口拉取真实中文证券名称、PE(TTM) 与 PB 补充信息。"""
    prefix = "sh" if num_code.startswith("6") else ("bj" if num_code.startswith(("4", "8", "920")) else "sz")
    # ★ 20261029 审计 P2：旧实现走**明文 http** —— 行情快照本身虽非机密，但明文
    #   传输可被中间人篡改（把 name / pe_ttm / pb 改掉就能污染下游所有结论）。
    #   腾讯行情接口支持 https，改走 https；若对方不支持再回退（并如实记降级）。
    url = f"https://qt.gtimg.cn/q={prefix}{num_code}"
    try:
        r = requests.get(url, timeout=config.TIMEOUT_DEFAULT, headers={"User-Agent": "Mozilla/5.0"})
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
        r = requests.get(url, params=params, timeout=config.TIMEOUT_DEFAULT, headers={"User-Agent": "Mozilla/5.0"})
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
        r = requests.get(url, params=params, timeout=config.TIMEOUT_DEFAULT, headers={"User-Agent": "Mozilla/5.0"})
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


def fetch_single_stock_news(num_code: str, limit: int = 10, health: Any | None = None) -> list[dict[str, Any]]:
    """获取单只股票专属新闻报道（东财 search-api-web JSONP 直连）。"""
    import json
    url = "https://search-api-web.eastmoney.com/search/jsonp"
    inner_param = {
        "uid": "",
        "keyword": num_code,
        "type": ["cmsArticleWebOld"],
        "client": "web",
        "clientVersion": "curr",
        "param": {
            "cmsArticleWebOld": {
                "searchScope": "default",
                "sort": "default",
                "pageIndex": 1,
                "pageSize": min(max(limit, 1), 50),
            }
        },
    }
    params = {
        "cb": "jQuery",
        "param": json.dumps(inner_param, ensure_ascii=False),
    }
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "Referer": f"https://so.eastmoney.com/news/s?keyword={num_code}",
    }
    try:
        r = requests.get(url, params=params, headers=headers, timeout=config.TIMEOUT_DEFAULT)
        if r.status_code == 200:
            text = r.text.strip()
            p_idx = text.find("(")
            if p_idx > 0 and text.endswith(")"):
                text = text[p_idx + 1: -1]
            data = json.loads(text)
            raw_articles = data.get("result", {}).get("cmsArticleWebOld", []) or []
            out = []
            for a in raw_articles:
                t = str(a.get("title", "") or "").replace("<em>", "").replace("</em>", "").strip()
                c = str(a.get("content", "") or "").replace("<em>", "").replace("</em>", "").strip()
                d = str(a.get("date", "") or "").strip()
                m = str(a.get("mediaName", "") or "").strip()
                u = str(a.get("url", "") or "").strip()
                if t:
                    out.append({
                        "title": t,
                        "content": c,
                        "date": d,
                        "media": m,
                        "url": u,
                    })
            if health:
                health.record_success("东财个股专属新闻", "search-api-web", len(out))
            return out
        if health:
            health.record_empty("东财个股专属新闻", "search-api-web", f"状态码: {r.status_code}")
    except Exception as e:
        logger.warning("获取个股新闻异常 (%s): %s", num_code, e)
        if health:
            health.record_failure("东财个股专属新闻", "search-api-web", e)
    return []


def fetch_institution_survey(num_code: str, limit: int = 10, health: Any | None = None) -> list[dict[str, Any]]:
    """获取上市公司投资者关系活动记录表（机构调研纪要）。"""
    url = "https://datacenter-web.eastmoney.com/api/data/v1/get"
    params = {
        "reportName": "RPT_ORG_SURVEYNEW",
        "columns": "ALL",
        "filter": f'(SECURITY_CODE="{num_code}")',
        "pageNumber": 1,
        "pageSize": min(max(limit, 1), 50),
        "sortTypes": "-1",
        "sortColumns": "NOTICE_DATE",
        "source": "WEB",
        "client": "WEB",
    }
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    try:
        r = requests.get(url, params=params, headers=headers, timeout=config.TIMEOUT_DEFAULT)
        if r.status_code == 200:
            res = (r.json().get("result") or {}).get("data", []) or []
            out = []
            for row in res:
                out.append({
                    "notice_date": str(row.get("NOTICE_DATE", ""))[:10],
                    "survey_date": str(row.get("START_DATE", ""))[:10],
                    "org_name": str(row.get("ORGANIZATION_NAME", "") or "").strip(),
                    "org_type": str(row.get("ORG_TYPE", "") or "").strip(),
                    "reception_place": str(row.get("RECEIVE_PLACE", "") or "").strip(),
                    "personnel": str(row.get("RECEIVE_PERSONNEL_NAME", "") or "").strip(),
                    "main_content": str(row.get("MAIN_CONTENT", "") or "").strip(),
                })
            if health:
                health.record_success("东财机构调研纪要", "eastmoney.RPT_ORG_SURVEYNEW", len(out))
            return out
        if health:
            health.record_empty("东财机构调研纪要", "eastmoney.RPT_ORG_SURVEYNEW", f"状态码: {r.status_code}")
    except Exception as e:
        logger.warning("获取机构调研纪要异常 (%s): %s", num_code, e)
        if health:
            health.record_failure("东财机构调研纪要", "eastmoney.RPT_ORG_SURVEYNEW", e)
    return []


def fetch_earnings_forecast(num_code: str, limit: int = 10, health: Any | None = None) -> list[dict[str, Any]]:
    """获取上市公司业绩预告与业绩快报（东财 datacenter）。"""
    url = "https://datacenter-web.eastmoney.com/api/data/v1/get"
    params = {
        "reportName": "RPT_LICO_FN_CPD",
        "columns": "ALL",
        "filter": f'(SECURITY_CODE="{num_code}")',
        "pageNumber": 1,
        "pageSize": min(max(limit, 1), 50),
        "sortTypes": "-1",
        "sortColumns": "NOTICE_DATE",
        "source": "WEB",
        "client": "WEB",
    }
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    try:
        r = requests.get(url, params=params, headers=headers, timeout=config.TIMEOUT_DEFAULT)
        if r.status_code == 200:
            res = (r.json().get("result") or {}).get("data", []) or []
            out = []
            for row in res:
                out.append({
                    "notice_date": str(row.get("NOTICE_DATE", ""))[:10],
                    "report_date": str(row.get("REPORT_DATE", ""))[:10],
                    "predict_type": str(row.get("PREDICT_TYPE", "") or "").strip(),
                    "min_profit": float(row.get("MIN_PROFIT") or 0.0),
                    "max_profit": float(row.get("MAX_PROFIT") or 0.0),
                    "increase_pct": float(row.get("ADD_YPCT") or 0.0),
                    "predict_content": str(row.get("PREDICT_CONTENT", "") or "").strip(),
                })
            if health:
                health.record_success("东财业绩预告", "eastmoney.RPT_LICO_FN_CPD", len(out))
            return out
        if health:
            health.record_empty("东财业绩预告", "eastmoney.RPT_LICO_FN_CPD", f"状态码: {r.status_code}")
    except Exception as e:
        logger.warning("获取业绩预告异常 (%s): %s", num_code, e)
        if health:
            health.record_failure("东财业绩预告", "eastmoney.RPT_LICO_FN_CPD", e)
    return []
