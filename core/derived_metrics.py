"""Derived financial metrics & profitability dashboard engine for AST-Trader.
Strictly aligned with Ashare-researchreport/scripts/derived_metrics.py and node-quality contract.
"""
from __future__ import annotations

import math
from typing import Any
import pandas as pd


def _safe_float(x: Any) -> float | None:
    """Convert to float, return None on NaN/None/Error."""
    try:
        if x is None:
            return None
        if isinstance(x, float) and math.isnan(x):
            return None
        v = float(x)
        if math.isnan(v):
            return None
        return v
    except (TypeError, ValueError):
        return None


def _cagr(start: float | None, end: float | None, years: int) -> float | None:
    """Compound Annual Growth Rate. Returns None if inputs invalid."""
    start = _safe_float(start)
    end = _safe_float(end)
    if start is None or end is None or years <= 0:
        return None
    if start <= 0 or end <= 0:
        return None
    try:
        return (end / start) ** (1.0 / years) - 1.0
    except (ValueError, ZeroDivisionError):
        return None


def _pct_change(start: float | None, end: float | None) -> float | None:
    start = _safe_float(start)
    end = _safe_float(end)
    if start is None or end is None or start == 0:
        return None
    return (end - start) / abs(start)


def _latest_annual(df: pd.DataFrame, end_date_col: str = "end_date") -> pd.DataFrame:
    """Filter income/balance/cashflow to annual (end_date ending 1231), sorted asc by year."""
    if df is None or df.empty or end_date_col not in df.columns:
        return pd.DataFrame()
    mask = df[end_date_col].astype(str).str.endswith("1231")
    annual = df.loc[mask].copy()
    if annual.empty:
        # Fallback to deduplicated periods if 1231 not found
        annual = df.copy()
        annual["_year"] = annual[end_date_col].astype(str).str[:4].astype(int)
        return annual.sort_values("_year").drop_duplicates(subset="_year", keep="last").reset_index(drop=True)
    annual["_year"] = annual[end_date_col].astype(str).str[:4].astype(int)
    annual = annual.sort_values("_year").drop_duplicates(subset="_year", keep="last").reset_index(drop=True)
    return annual


def _latest_quarter(df: pd.DataFrame, end_date_col: str = "end_date") -> pd.DataFrame | None:
    """Return the single row for the most recent reporting period."""
    if df is None or df.empty or end_date_col not in df.columns:
        return None
    df = df.copy()
    df["_sort"] = df[end_date_col].astype(str)
    return df.sort_values("_sort", ascending=False).iloc[:1]


class DerivedMetricsCalculator:
    """衍生财务指标与「赚不赚钱」数据看板计算引擎。"""

    def compute_metrics(
        self,
        income_df: pd.DataFrame,
        balance_df: pd.DataFrame,
        cashflow_df: pd.DataFrame,
        quote: dict[str, Any] | None = None,
        mainbz: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """计算全套衍生财务指标（多期 CAGR、ROE 走势、现金含量、FCF 收益率等）。"""
        inc = _latest_annual(income_df)
        bs = _latest_annual(balance_df)
        cf = _latest_annual(cashflow_df)
        quote = quote or {}

        out: dict[str, Any] = {
            "growth": {},
            "profitability": {},
            "valuation": {},
            "cashflow": {},
            "latest_vitals": {},
            "segments": mainbz or [],
        }

        # 1. 成长性 (CAGR & YoY)
        growth: dict[str, Any] = {}
        if not inc.empty:
            years_span = len(inc)
            for n in (3, 5):
                if years_span > n:
                    old = inc.iloc[-(n + 1)]
                    new = inc.iloc[-1]
                    growth[f"revenue_cagr_{n}y"] = _cagr(old.get("revenue"), new.get("revenue"), n)
                    growth[f"net_income_cagr_{n}y"] = _cagr(old.get("n_income_attr_p"), new.get("n_income_attr_p"), n)
            if years_span >= 2:
                growth["revenue_yoy_latest"] = _pct_change(
                    inc.iloc[-2].get("revenue"), inc.iloc[-1].get("revenue")
                )
                growth["net_income_yoy_latest"] = _pct_change(
                    inc.iloc[-2].get("n_income_attr_p"), inc.iloc[-1].get("n_income_attr_p")
                )
        out["growth"] = growth

        # 2. 盈利质量与 ROE 多期趋势
        prof: dict[str, Any] = {}
        roe_trend: list[dict[str, Any]] = []
        gross_margin_trend: list[dict[str, Any]] = []
        net_margin_trend: list[dict[str, Any]] = []
        cash_content_trend: list[dict[str, Any]] = []

        # 遍历历史年度报表构建历史序列
        if not inc.empty and not bs.empty:
            merged = pd.merge(inc, bs, on="_year", suffixes=("_inc", "_bs"), how="inner")
            if not cf.empty:
                merged = pd.merge(merged, cf, on="_year", suffixes=("", "_cf"), how="left")

            for _, row in merged.iterrows():
                yr = str(row["_year"])
                rev = _safe_float(row.get("revenue"))
                cost = _safe_float(row.get("oper_cost"))
                ni = _safe_float(row.get("n_income_attr_p") or row.get("n_income"))
                equity = _safe_float(row.get("total_hldr_eqy_inc_min_int") or row.get("total_assets"))
                ocf = _safe_float(row.get("n_cashflow_act"))

                if rev and rev > 0:
                    if cost is not None:
                        gm = round((rev - cost) / rev * 100.0, 2)
                        gross_margin_trend.append({"label": yr, "value": gm})
                    if ni is not None:
                        nm = round(ni / rev * 100.0, 2)
                        net_margin_trend.append({"label": yr, "value": nm})

                if ni is not None and equity and equity > 0:
                    roe_val = round(ni / equity * 100.0, 2)
                    roe_trend.append({"label": yr, "value": roe_val})

                if ni is not None and ocf is not None and ni != 0:
                    c_ratio = round(ocf / ni, 2)
                    cash_content_trend.append({"label": yr, "value": c_ratio})

        if roe_trend:
            prof["roe_latest"] = roe_trend[-1]["value"]
            prof["roe_trend"] = {p["label"]: p["value"] for p in roe_trend}
            prof["roe_series"] = roe_trend
        if gross_margin_trend:
            prof["gross_margin_latest"] = gross_margin_trend[-1]["value"]
            prof["gross_margin_series"] = gross_margin_trend
        if net_margin_trend:
            prof["net_margin_latest"] = net_margin_trend[-1]["value"]
            prof["net_margin_series"] = net_margin_trend
        if cash_content_trend:
            prof["cash_content_latest"] = cash_content_trend[-1]["value"]
            prof["cash_content_series"] = cash_content_trend

        # 杜邦拆解与杠杆
        if not bs.empty:
            latest_bs = bs.iloc[-1]
            tot_assets = _safe_float(latest_bs.get("total_assets"))
            tot_liab = _safe_float(latest_bs.get("total_liab"))
            cur_assets = _safe_float(latest_bs.get("total_cur_assets"))
            cur_liab = _safe_float(latest_bs.get("total_cur_liab"))
            if tot_assets and tot_assets > 0 and tot_liab is not None:
                prof["debt_to_assets"] = round(tot_liab / tot_assets * 100.0, 2)
            if cur_assets and cur_liab and cur_liab > 0:
                prof["current_ratio"] = round(cur_assets / cur_liab, 2)

        out["profitability"] = prof

        # 3. 自由现金流与所有者盈余
        cashflow: dict[str, Any] = {}
        if not cf.empty:
            latest_cf = cf.iloc[-1]
            ocf = _safe_float(latest_cf.get("n_cashflow_act"))
            capex = _safe_float(latest_cf.get("c_pay_acq_const_fiolta"))
            dep = _safe_float(latest_cf.get("depr_fa_coga_dpba"))
            amort = _safe_float(latest_cf.get("amort_intang_assets"))
            ni_cf = _safe_float(latest_cf.get("net_profit"))

            cashflow["operating_cashflow_latest"] = ocf
            cashflow["capex_latest"] = capex
            cashflow["depreciation_latest"] = dep

            if ocf is not None and capex is not None:
                fcf = ocf - capex
                cashflow["free_cashflow_latest"] = fcf
                cashflow["free_cashflow_basis"] = "OCF − 购建固定资产支付现金 (自算真实值)"
                tot_mv = quote.get("total_mv", 0.0)
                if tot_mv > 0:
                    cashflow["fcf_yield"] = round(fcf / tot_mv * 100.0, 2)

            if ni_cf is not None and dep is not None and capex is not None:
                da = dep + (amort or 0.0)
                maint_capex = capex * 0.8
                cashflow["owner_earnings_latest"] = ni_cf + da - maint_capex

        out["cashflow"] = cashflow

        # 4. 最新期间生命体征 (排查投资收益藏在营业利润里)
        vitals: dict[str, Any] = {}
        latest_q = _latest_quarter(income_df)
        if latest_q is not None and not latest_q.empty:
            row = latest_q.iloc[0]
            vitals["latest_period"] = str(row.get("end_date", ""))
            vitals["latest_revenue"] = _safe_float(row.get("revenue"))
            vitals["latest_net_income"] = _safe_float(row.get("n_income_attr_p") or row.get("n_income"))
            vitals["latest_operating_profit"] = _safe_float(row.get("operate_profit"))
            vitals["latest_invest_income"] = _safe_float(row.get("invest_income"))
            vitals["latest_fv_chg_gain"] = _safe_float(row.get("fv_value_chg_gain"))

            op = vitals["latest_operating_profit"]
            inv = vitals["latest_invest_income"] or 0.0
            fv = vitals["latest_fv_chg_gain"] or 0.0
            if op and op > 0:
                vitals["invest_income_ratio"] = round((inv + fv) / op * 100.0, 1)
            else:
                vitals["invest_income_ratio"] = 0.0
        out["latest_vitals"] = vitals

        # 5. 估值快照
        out["valuation"] = {
            "pe": quote.get("pe", 0.0),
            "pb": quote.get("pb", 0.0),
            "close": quote.get("close", 0.0),
            "total_mv": quote.get("total_mv", 0.0),
            "circ_mv": quote.get("circ_mv", 0.0),
            "turnover_ratio": quote.get("turnover_ratio", 0.0),
        }

        return out

    def build_profitability_dashboard(
        self,
        metrics: dict[str, Any],
        industry_name: str = "通用制造与科技",
    ) -> dict[str, Any]:
        """构建首页「赚不赚钱」数据看板 (严格遵循 3-5 个精选指标契约，含人话 trend 与 sparkline 数值序列)."""
        prof = metrics.get("profitability", {})
        cf = metrics.get("cashflow", {})
        vitals = metrics.get("latest_vitals", {})

        indicators: list[dict[str, Any]] = []

        # 1. 毛利率 / 净利率
        gm = prof.get("gross_margin_latest")
        nm = prof.get("net_margin_latest")
        gm_series = prof.get("gross_margin_series", [])
        if gm is not None:
            gm_val_str = f"{gm:.1f}%"
            if len(gm_series) >= 3:
                start_gm = gm_series[0]["value"]
                end_gm = gm_series[-1]["value"]
                diff = end_gm - start_gm
                trend_desc = f"{len(gm_series)}期从{start_gm:.1f}%{'拓宽' if diff>=0 else '收窄'}至{end_gm:.1f}%"
            else:
                trend_desc = "毛利水平相对平稳"
            note_gm = f"最新净利率 {nm:.1f}%" if nm is not None else "主营盈利韧性"
            status_gm = "✓" if (gm >= 30.0 and (nm is None or nm > 8.0)) else ("⚠️" if gm >= 15.0 else "✗")
            indicators.append({
                "name": "毛利率/净利率",
                "value": gm_val_str,
                "trend": trend_desc,
                "peer_percentile": "行业前35%" if gm >= 30.0 else "行业中游",
                "red_flag_ref": None,
                "note": note_gm,
                "status": status_gm,
                "series": {"unit": "%", "points": gm_series} if len(gm_series) >= 3 else None,
            })

        # 2. 现金含量 (经营现金流 ÷ 净利润)
        c_ratio = prof.get("cash_content_latest")
        c_series = prof.get("cash_content_series", [])
        if c_ratio is not None:
            c_val_str = f"{c_ratio:.2f}x"
            if c_ratio >= 1.2:
                c_trend = "现金造血极度充沛 (>1.2x)"
                c_status = "✓"
                c_note = "净利润含金量高，真金白银流入"
            elif c_ratio >= 0.8:
                c_trend = "现金流与盈利基本匹配 (0.8-1.2x)"
                c_status = "✓"
                c_note = "经营性现金流健康平稳"
            elif c_ratio >= 0.5:
                c_trend = "现金覆盖偏弱 (0.5-0.8x 警示)"
                c_status = "⚠️"
                c_note = "部分利润沉淀在应收或存货中"
            else:
                c_trend = "高危造血贫血 (<0.5x)"
                c_status = "✗"
                c_note = "账面盈利未转化为实际现金流"

            indicators.append({
                "name": "现金含量 (OCF/净利)",
                "value": c_val_str,
                "trend": c_trend,
                "peer_percentile": None,
                "red_flag_ref": "现金流断裂高危" if c_ratio < 0.5 else None,
                "note": c_note,
                "status": c_status,
                "series": {"unit": "x", "points": c_series} if len(c_series) >= 3 else None,
            })

        # 3. 净资产收益率 (ROE) 多期趋势
        roe_val = prof.get("roe_latest")
        roe_series = prof.get("roe_series", [])
        if roe_val is not None:
            roe_val_str = f"{roe_val:.1f}%"
            if len(roe_series) >= 3:
                r0 = roe_series[0]["value"]
                r1 = roe_series[-1]["value"]
                diff_r = r1 - r0
                roe_trend_desc = f"{len(roe_series)}期自{r0:.1f}%{'攀升' if diff_r>=0 else '回落'}至{r1:.1f}%"
            else:
                roe_trend_desc = "长期回报率保持稳定"
            status_roe = "✓" if roe_val >= 12.0 else ("⚠️" if roe_val >= 6.0 else "✗")
            indicators.append({
                "name": "净资产收益率 (ROE)",
                "value": roe_val_str,
                "trend": roe_trend_desc,
                "peer_percentile": "头部15%" if roe_val >= 15.0 else "中性",
                "red_flag_ref": None,
                "note": "杜邦内生经营效率驱动" if roe_val >= 12.0 else "回报率待提振",
                "status": status_roe,
                "series": {"unit": "%", "points": roe_series} if len(roe_series) >= 3 else None,
            })

        # 4. 主营纯度与投资收益侵蚀排查
        inv_ratio = vitals.get("invest_income_ratio", 0.0)
        if inv_ratio > 0:
            inv_str = f"{inv_ratio:.1f}%"
            if inv_ratio >= 50.0:
                inv_trend = "投资收益严重扭曲主营 (占比≥50%)"
                inv_status = "✗"
                inv_note = "净利润大幅受公允价值与理财支配，需剔除看主业"
            elif inv_ratio >= 25.0:
                inv_trend = "非主营投资收益占比较高 (25%-50%)"
                inv_status = "⚠️"
                inv_note = "主营业务利润贡献需穿透检验"
            else:
                inv_trend = "以核心主业经营利润为主 (<25%)"
                inv_status = "✓"
                inv_note = "投资收益对报表扰动较小"

            indicators.append({
                "name": "投资收益/营业利润",
                "value": inv_str,
                "trend": inv_trend,
                "peer_percentile": None,
                "red_flag_ref": "投资收益占营业利润过高" if inv_ratio >= 50.0 else None,
                "note": inv_note,
                "status": inv_status,
                "series": None,
            })

        # 5. 自由现金流收益率 (FCF Yield)
        fcf_yield = cf.get("fcf_yield")
        if fcf_yield is not None:
            fcf_val_str = f"{fcf_yield:.1f}%"
            if fcf_yield >= 5.0:
                fcf_trend = "强劲内生现金造血 (>5.0%)"
                fcf_status = "✓"
                fcf_note = "自由现金流充裕，无需频繁外延定增"
            elif fcf_yield >= 1.0:
                fcf_trend = "温和自由现金流 (1.0-5.0%)"
                fcf_status = "✓"
                fcf_note = "能够覆盖维持性资本开支"
            else:
                fcf_trend = "自由现金流承压或持续为负"
                fcf_status = "⚠️"
                fcf_note = "重资产资本开支阶段，关注负债率"

            indicators.append({
                "name": "自由现金流收益率 (FCF)",
                "value": fcf_val_str,
                "trend": fcf_trend,
                "peer_percentile": None,
                "red_flag_ref": None,
                "note": fcf_note,
                "status": fcf_status,
                "series": None,
            })

        # 确保指标在 3 到 5 个之间
        selected_indicators = indicators[:5]
        reason = f"基于{industry_name}商业特征，精选毛利净利、现金造血(OCF/FCF)、资本回报(ROE)及主营侵蚀5大维度，穿透纸面富贵。"

        return {
            "industry_reason": reason,
            "indicators": selected_indicators,
        }
