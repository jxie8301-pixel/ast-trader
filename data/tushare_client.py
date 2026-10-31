"""Tushare Pro VIP 数据通道客户端。
优先接入用户配置的 6000 积分 Tushare Key，调取权威清洗后的官方财务三表与业绩预告。
"""
from __future__ import annotations

import logging
from typing import Any
import pandas as pd
import config
from data.eltdx_units import to_ts_code

logger = logging.getLogger("ast_trader.data.tushare")

_PRO_CLIENT = None


def get_pro_client():
    """获取 Tushare Pro 客户端单例。"""
    global _PRO_CLIENT
    token = getattr(config, "TUSHARE_TOKEN", "").strip()
    if not token:
        return None
    if _PRO_CLIENT is None:
        try:
            import tushare as ts
            ts.set_token(token)
            _PRO_CLIENT = ts.pro_api(token)
            logger.info("已成功连接 Tushare Pro VIP 客户端")
        except Exception as e:
            logger.warning("初始化 Tushare 客户端失败: %s", e)
            return None
    return _PRO_CLIENT


class TushareClient:
    """Tushare Pro 数据拉取器。"""

    def __init__(self, token: str | None = None) -> None:
        self.token = token or getattr(config, "TUSHARE_TOKEN", "").strip()
        self.pro = get_pro_client()

    @property
    def is_available(self) -> bool:
        return bool(self.token and self.pro is not None)

    def get_financial_reports(self, code_str: str, limit: int = 20) -> dict[str, pd.DataFrame]:
        """获取标准化的财务三表（资产负债表、现金流量表、利润表）。
        返回格式与 EltdxCollector.get_financial_reports 100% 对齐：
        {"balance": df, "cashflow": df, "income": df}
        """
        if not self.is_available:
            return {}

        ts_code = to_ts_code(code_str)
        out: dict[str, pd.DataFrame] = {
            "balance": pd.DataFrame(),
            "cashflow": pd.DataFrame(),
            "income": pd.DataFrame(),
        }

        try:
            # 1. 利润表 (优先取合并报表 report_type=1)
            df_inc = self.pro.income(ts_code=ts_code, limit=limit)
            if df_inc is not None and not df_inc.empty:
                if "report_type" in df_inc.columns:
                    con = df_inc[df_inc["report_type"] == "1"]
                    if not con.empty:
                        df_inc = con
                df_inc = df_inc.drop_duplicates(subset=["end_date"]).sort_values("end_date").reset_index(drop=True)
                out["income"] = df_inc

            # 2. 资产负债表
            df_bal = self.pro.balancesheet(ts_code=ts_code, limit=limit)
            if df_bal is not None and not df_bal.empty:
                if "report_type" in df_bal.columns:
                    con = df_bal[df_bal["report_type"] == "1"]
                    if not con.empty:
                        df_bal = con
                df_bal = df_bal.drop_duplicates(subset=["end_date"]).sort_values("end_date").reset_index(drop=True)
                out["balance"] = df_bal

            # 3. 现金流量表
            df_cf = self.pro.cashflow(ts_code=ts_code, limit=limit)
            if df_cf is not None and not df_cf.empty:
                if "report_type" in df_cf.columns:
                    con = df_cf[df_cf["report_type"] == "1"]
                    if not con.empty:
                        df_cf = con
                df_cf = df_cf.drop_duplicates(subset=["end_date"]).sort_values("end_date").reset_index(drop=True)
                out["cashflow"] = df_cf

            logger.info("Tushare Pro VIP 成功调取 %s 三表 (有效期数: 利润 %d, 资产 %d, 现金 %d)",
                        ts_code, len(out["income"]), len(out["balance"]), len(out["cashflow"]))
            return out
        except Exception as e:
            logger.warning("Tushare Pro 拉取财务三表异常 (%s): %s", ts_code, e)
            return {}

    def get_forecast(self, code_str: str, limit: int = 10) -> list[dict[str, Any]]:
        """获取上市公司最新业绩预告。"""
        if not self.is_available:
            return []

        ts_code = to_ts_code(code_str)
        try:
            df = self.pro.forecast(ts_code=ts_code, limit=limit)
            if df is None or df.empty:
                return []
            out = []
            for _, row in df.iterrows():
                out.append({
                    "notice_date": str(row.get("ann_date", ""))[:10],
                    "report_date": str(row.get("end_date", ""))[:10],
                    "predict_type": str(row.get("type", "") or "").strip(),
                    "min_profit": float(row.get("net_profit_min") or 0.0) * 10000.0,
                    "max_profit": float(row.get("net_profit_max") or 0.0) * 10000.0,
                    "increase_pct": float(row.get("p_change_min") or 0.0),
                    "predict_content": str(row.get("summary", "") or row.get("change_reason", "") or "").strip(),
                })
            return out
        except Exception as e:
            logger.warning("Tushare Pro 拉取业绩预告异常 (%s): %s", ts_code, e)
            return []
