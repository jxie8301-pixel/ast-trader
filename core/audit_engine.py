"""11 classic accounting and forensic audit frameworks for AST-Trader.
Strictly aligned with Ashare-researchreport/scripts/financial_audit.py.
"""
from __future__ import annotations

import math
from typing import Any

import pandas as pd

import config
from .red_flags import (
    LEVEL_FATAL,
    LEVEL_HIGH,
    LEVEL_INFO,
    LEVEL_LOW,
    LEVEL_MEDIUM,
    RedFlagItem,
    make_flag_id,
)


def _safe_float(v: Any, default: float | None = None) -> float | None:
    if v is None:
        return default
    try:
        val = float(v)
        return default if math.isnan(val) else val
    except (ValueError, TypeError):
        return default


def _annual(df: pd.DataFrame) -> pd.DataFrame:
    """过滤年报行 (以 1231 结尾的报告期)，按年份升序排序 (完全对齐 Ashare financial_audit.py:90)"""
    if df is None or df.empty:
        return pd.DataFrame()
    if "end_date" not in df.columns:
        return df.copy()
    mask = df["end_date"].astype(str).str.endswith("1231")
    ann = df.loc[mask].copy()
    if ann.empty or len(ann) < 2:
        return pd.DataFrame()
    ann["_year"] = ann["end_date"].astype(str).str[:4].astype(int)
    ann = ann.sort_values("_year").drop_duplicates("_year", keep="last").reset_index(drop=True)
    return ann


class AuditEngine:
    """11 大财务审计与扫雷引擎。输入三张报表与行情快照，输出标准红旗清单。"""

    def __init__(self) -> None:
        pass

    def run_audit(
        self,
        balance_df: pd.DataFrame,
        cashflow_df: pd.DataFrame,
        income_df: pd.DataFrame,
        governance_info: dict[str, Any] | None = None,
        quote_info: dict[str, Any] | None = None,
    ) -> list[RedFlagItem]:
        """运行全部 11 个经典审计框架，输出标准红旗清单。"""
        flags: list[RedFlagItem] = []

        ann_bs = _annual(balance_df)
        ann_inc = _annual(income_df)
        ann_cf = _annual(cashflow_df)

        # 1. Piotroski F-Score (9 签号)
        flags.extend(self._check_piotroski(ann_bs, ann_inc, ann_cf))

        # 2. Beneish M-Score (8 变量)
        flags.extend(self._check_beneish(ann_bs, ann_inc, ann_cf))

        # 3. Altman Z-Score (5 变量破产预警)
        flags.extend(self._check_altman(ann_bs, ann_inc, quote_info))

        # 4. DuPont 3/5 分解与 ROE 急剧恶化
        flags.extend(self._check_dupont(ann_bs, ann_inc))

        # 5. Buffett Quality Checks (剪刀差、现金覆盖与非经占比)
        flags.extend(self._check_buffett_quality(ann_bs, ann_inc, ann_cf))

        # 6. 主营业务侵蚀 (投资收益占营业利润过高 - 涵盖最新期)
        flags.extend(self._check_invest_income_erosion(income_df))

        # 7. Sloan Accrual Anomaly (高应计异象)
        flags.extend(self._check_sloan(ann_bs, ann_inc, ann_cf))

        # 8. Governance Red Flags (高比例质押、股东减持)
        if governance_info:
            flags.extend(self._check_governance(governance_info))

        # 9. Shareholder Flow (股东户数变动与筹码散户化)
        if governance_info:
            flags.extend(self._check_shareholder_flow(governance_info))

        # 10. Forward Guidance Anomaly (业绩预告异常与首亏/预亏, 对齐 Ashare Framework 9)
        if governance_info:
            flags.extend(self._check_forecast_anomaly(governance_info))

        # 11. Valuation Anomaly (估值透支、PB vs ROE 错配、小盘双杀)
        if quote_info:
            flags.extend(self._check_valuation(ann_bs, ann_inc, quote_info))

        # 12. Related-Party & Subsidiary Exposure (长期股权投资与关联方敞口)
        flags.extend(self._check_related_party_exposure(ann_bs, ann_inc))

        return flags

    # ─────────────────────────────────────────────────────────────
    # Framework 1: Piotroski F-Score (9 签号打分, 对齐 Ashare financial_audit.py:114)
    # ─────────────────────────────────────────────────────────────
    def _check_piotroski(self, bs: pd.DataFrame, inc: pd.DataFrame, cf: pd.DataFrame) -> list[RedFlagItem]:
        flags = []
        if len(inc) < 2 or len(bs) < 2 or len(cf) < 2:
            return flags

        y_now, y_prev = inc.iloc[-1], inc.iloc[-2]
        bs_now, bs_prev = bs.iloc[-1], bs.iloc[-2]
        cf_now, cf_prev = cf.iloc[-1], cf.iloc[-2]

        score = 0
        details: list[str] = []

        # 1. NI > 0
        ni = _safe_float(y_now.get("n_income_attr_p")) or _safe_float(y_now.get("n_income")) or 0.0
        ok_ni = ni > 0
        score += int(ok_ni)
        details.append(f"NI>0={'✓' if ok_ni else '✗'}")

        # 2. ROA > 0 (资产缺失严禁假定 ta=1.0)
        ta_now = _safe_float(bs_now.get("total_assets"))
        if ta_now and ta_now > 0:
            roa = ni / ta_now
            ok_roa = roa > 0
        else:
            roa = None
            ok_roa = False
        score += int(ok_roa)
        details.append(f"ROA>0={'✓' if ok_roa else '✗'}")

        # 3. OCF > 0
        ocf = _safe_float(cf_now.get("n_cashflow_act")) or 0.0
        ok_ocf = ocf > 0
        score += int(ok_ocf)
        details.append(f"OCF>0={'✓' if ok_ocf else '✗'}")

        # 4. OCF > NI (利润现金质量)
        ok_cfo_ni = ocf > ni
        score += int(ok_cfo_ni)
        details.append(f"OCF>NI={'✓' if ok_cfo_ni else '✗'}")

        # 5. ROA 同比上升
        ni_prev = _safe_float(y_prev.get("n_income_attr_p")) or _safe_float(y_prev.get("n_income")) or 0.0
        ta_prev = _safe_float(bs_prev.get("total_assets"))
        if roa is not None and ta_prev and ta_prev > 0:
            roa_prev = ni_prev / ta_prev
            ok_roa_up = roa > roa_prev
        else:
            ok_roa_up = False
        score += int(ok_roa_up)
        details.append(f"ROA↑={'✓' if ok_roa_up else '✗'}")

        # 6. 资产负债率同比下降
        tl_now = _safe_float(bs_now.get("total_liab"))
        tl_prev = _safe_float(bs_prev.get("total_liab"))
        if ta_now and ta_now > 0 and ta_prev and ta_prev > 0 and tl_now is not None and tl_prev is not None:
            dta_now = tl_now / ta_now
            dta_prev = tl_prev / ta_prev
            ok_lev_down = dta_now < dta_prev
        else:
            ok_lev_down = False
        score += int(ok_lev_down)
        details.append(f"负债率↓={'✓' if ok_lev_down else '✗'}")

        # 7. 流动比率同比上升
        tca_now = _safe_float(bs_now.get("total_cur_assets"))
        tcl_now = _safe_float(bs_now.get("total_cur_liab"))
        tca_prev = _safe_float(bs_prev.get("total_cur_assets"))
        tcl_prev = _safe_float(bs_prev.get("total_cur_liab"))
        if tca_now is not None and tcl_now and tcl_now > 0 and tca_prev is not None and tcl_prev and tcl_prev > 0:
            cr_now = tca_now / tcl_now
            cr_prev = tca_prev / tcl_prev
            ok_cr_up = cr_now > cr_prev
        else:
            ok_cr_up = False
        score += int(ok_cr_up)
        details.append(f"流动比率↑={'✓' if ok_cr_up else '✗'}")

        # 8. 毛利率同比上升 (营收缺失严禁假定 rev=1.0)
        rev_now = _safe_float(y_now.get("revenue"))
        rev_prev = _safe_float(y_prev.get("revenue"))
        cos_now = _safe_float(y_now.get("oper_cost"))
        cos_prev = _safe_float(y_prev.get("oper_cost"))
        if rev_now and rev_now > 0 and rev_prev and rev_prev > 0 and cos_now is not None and cos_prev is not None:
            gm_now = (rev_now - cos_now) / rev_now
            gm_prev = (rev_prev - cos_prev) / rev_prev
            ok_gm_up = gm_now > gm_prev
        else:
            ok_gm_up = False
        score += int(ok_gm_up)
        details.append(f"毛利率↑={'✓' if ok_gm_up else '✗'}")

        # 9. 资产周转率同比上升
        if rev_now and rev_prev and ta_now and ta_prev and ta_now > 0 and ta_prev > 0:
            at_now = rev_now / ta_now
            at_prev = rev_prev / ta_prev
            ok_at_up = at_now > at_prev
        else:
            ok_at_up = False
        score += int(ok_at_up)
        details.append(f"周转率↑={'✓' if ok_at_up else '✗'}")

        if score <= 3:
            flags.append(RedFlagItem(
                id=make_flag_id("Piotroski", "f_score_poor"),
                framework="Piotroski F-Score",
                level=LEVEL_HIGH,
                title="基本面健康度严重恶化 (Piotroski F-Score 极低)",
                value=score,
                threshold="F <= 3 警示",
                evidence=f"F-Score={score}/9 分 ({' | '.join(details)})",
                node="quality",
                metric_refs=["f_score"],
            ))
        elif score >= 7:
            flags.append(RedFlagItem(
                id=make_flag_id("Piotroski", "f_score_strong"),
                framework="Piotroski F-Score",
                level=LEVEL_LOW,
                title="综合财务状况优良 (Piotroski F-Score 强健)",
                value=score,
                threshold="F >= 7 优秀",
                evidence=f"F-Score={score}/9 分 ({' | '.join(details)})",
                node="quality",
                metric_refs=["f_score"],
            ))

        return flags

    # ─────────────────────────────────────────────────────────────
    # Framework 2: Beneish M-Score (8 变量模型, 对齐 Ashare financial_audit.py:222)
    # ─────────────────────────────────────────────────────────────
    def _check_beneish(self, bs: pd.DataFrame, inc: pd.DataFrame, cf: pd.DataFrame) -> list[RedFlagItem]:
        flags = []
        if len(inc) < 2 or len(bs) < 2:
            return flags

        y_now, y_prev = inc.iloc[-1], inc.iloc[-2]
        b_now, b_prev = bs.iloc[-1], bs.iloc[-2]

        rev_t = _safe_float(y_now.get("revenue"))
        rev_t1 = _safe_float(y_prev.get("revenue"))
        rec_t = _safe_float(b_now.get("accounts_receiv"))
        rec_t1 = _safe_float(b_prev.get("accounts_receiv"))
        cogs_t = _safe_float(y_now.get("oper_cost"))
        cogs_t1 = _safe_float(y_prev.get("oper_cost"))
        ta_t = _safe_float(b_now.get("total_assets"))
        ta_t1 = _safe_float(b_prev.get("total_assets"))

        if not all([rev_t, rev_t1, ta_t, ta_t1]) or rev_t <= 0 or rev_t1 <= 0 or ta_t <= 0 or ta_t1 <= 0:
            return flags

        # 1. DSRI
        dsri = ((rec_t or 0) / rev_t) / max(((rec_t1 or 0) / rev_t1), 1e-4)
        # 2. GMI
        gm_t = (rev_t - (cogs_t or 0)) / rev_t
        gm_t1 = (rev_t1 - (cogs_t1 or 0)) / rev_t1
        gmi = max(gm_t1, 1e-4) / max(gm_t, 1e-4)
        # 3. AQI
        ca_t = _safe_float(b_now.get("total_cur_assets"), 0)
        ca_t1 = _safe_float(b_prev.get("total_cur_assets"), 0)
        ppe_t = _safe_float(b_now.get("fix_assets"), 0)
        ppe_t1 = _safe_float(b_prev.get("fix_assets"), 0)
        aqi = (1 - (ca_t + ppe_t) / ta_t) / max((1 - (ca_t1 + ppe_t1) / ta_t1), 1e-4)
        # 4. SGI
        sgi = rev_t / rev_t1
        # 5. DEPI
        depi = 1.0
        # 6. SGAI
        sgai = 1.0
        # 7. LVGI
        debt_t = (_safe_float(b_now.get("total_liab")) or 0) / ta_t
        debt_t1 = (_safe_float(b_prev.get("total_liab")) or 0) / ta_t1
        lvgi = debt_t / max(debt_t1, 1e-4)
        # 8. TATA
        ni_t = _safe_float(y_now.get("n_income")) or 0
        cfo_t = (_safe_float(cf.iloc[-1].get("n_cashflow_act")) or 0) if len(cf) > 0 else 0
        tata = (ni_t - cfo_t) / ta_t

        m_score = (
            -4.84
            + 0.920 * dsri
            + 0.528 * gmi
            + 0.404 * aqi
            + 0.892 * sgi
            + 0.115 * depi
            - 0.172 * sgai
            + 4.679 * tata
            - 0.327 * lvgi
        )

        if m_score > config.BENEISH_M_FATAL_SCORE:
            flags.append(RedFlagItem(
                id=make_flag_id("Beneish", "m_score_fraud_risk"),
                framework="Beneish M-Score",
                level=LEVEL_FATAL,
                title="财务操纵高风险 (Beneish M-Score 超标)",
                value=round(m_score, 3),
                threshold=f"> {config.BENEISH_M_FATAL_SCORE}",
                evidence=f"M-Score={m_score:.3f} (DSRI应收异动={dsri:.2f}, SGI营收增长={sgi:.2f}, TATA应计率={tata:.2f})",
                node="quality",
                metric_refs=["m_score"],
            ))
        elif dsri > 2.0:
            flags.append(RedFlagItem(
                id=make_flag_id("Beneish", "dsri_high"),
                framework="Beneish M-Score",
                level=LEVEL_HIGH,
                title="应收账款增速远超营收 (存赊销激进确认风险)",
                value=round(dsri, 2),
                threshold="> 2.0",
                evidence=f"应收账款异动指数 DSRI={dsri:.2f}",
                node="quality",
                metric_refs=["receivables"],
            ))

        return flags

    # ─────────────────────────────────────────────────────────────
    # Framework 3: Altman Z-Score (破产预警, 对齐 Ashare financial_audit.py:335)
    # ─────────────────────────────────────────────────────────────
    def _check_altman(self, bs: pd.DataFrame, inc: pd.DataFrame, quote_info: dict[str, Any] | None = None) -> list[RedFlagItem]:
        flags = []
        if bs.empty or inc.empty:
            return flags

        b = bs.iloc[-1]
        i = inc.iloc[-1]
        ta = _safe_float(b.get("total_assets"))
        tl = _safe_float(b.get("total_liab"))
        if not ta or ta <= 0 or not tl or tl <= 0:
            return flags

        tca = _safe_float(b.get("total_cur_assets"), 0)
        tcl = _safe_float(b.get("total_cur_liab"), 0)
        re = _safe_float(b.get("undistr_profit"), 0)
        ebit = _safe_float(i.get("operate_profit"), 0)
        rev = _safe_float(i.get("revenue"), 0)

        mv = 0.0
        if quote_info:
            price = _safe_float(quote_info.get("close"), 0.0)
            shares = _safe_float(b.get("total_share"), 0.0)
            mv = (price * shares) if price and shares else (_safe_float(b.get("total_equity"), 0.0) or 1.0)
        else:
            mv = _safe_float(b.get("total_equity"), 0.0) or 1.0

        z = (
            1.2 * (tca - tcl) / ta
            + 1.4 * re / ta
            + 3.3 * ebit / ta
            + 0.6 * mv / tl
            + 1.0 * rev / ta
        )

        if z < 1.81:
            flags.append(RedFlagItem(
                id=make_flag_id("Altman", "z_score_distress"),
                framework="Altman Z-Score",
                level=LEVEL_FATAL,
                title="破产高危区域 (Altman Z-Score 极低)",
                value=round(z, 3),
                threshold="Z < 1.81 破产风险",
                evidence=f"Z-Score={z:.3f} 处于破产危机困境区 (营运资本/TA={(tca-tcl)/ta:.3f}, RE/TA={re/ta:.3f}, EBIT/TA={ebit/ta:.3f}, MV/TL={mv/tl:.3f})",
                node="path",
                metric_refs=["z_score"],
            ))
        elif z < 2.99:
            flags.append(RedFlagItem(
                id=make_flag_id("Altman", "z_score_grey"),
                framework="Altman Z-Score",
                level=LEVEL_HIGH,
                title="财务状况脆弱 (Altman Z-Score 处于灰色预警区)",
                value=round(z, 3),
                threshold="1.81 <= Z < 2.99",
                evidence=f"Z-Score={z:.3f} 处于财务灰色预警地带",
                node="path",
                metric_refs=["z_score"],
            ))

        return flags

    # ─────────────────────────────────────────────────────────────
    # Framework 4: DuPont 3/5 分解 (对齐 Ashare financial_audit.py:381)
    # ─────────────────────────────────────────────────────────────
    def _check_dupont(self, bs: pd.DataFrame, inc: pd.DataFrame) -> list[RedFlagItem]:
        flags = []
        if len(inc) < 2 or len(bs) < 2:
            return flags

        y_now, y_prev = inc.iloc[-1], inc.iloc[-2]
        b_now, b_prev = bs.iloc[-1], bs.iloc[-2]

        rev_now = _safe_float(y_now.get("revenue")) or 0.0
        ni_now = _safe_float(y_now.get("n_income_attr_p")) or _safe_float(y_now.get("n_income")) or 0.0
        ta_now = _safe_float(b_now.get("total_assets")) or 0.0
        te_now = _safe_float(b_now.get("total_hldr_eqy_exc_min_int")) or _safe_float(b_now.get("total_equity")) or 0.0

        rev_prev = _safe_float(y_prev.get("revenue")) or 0.0
        ni_prev = _safe_float(y_prev.get("n_income_attr_p")) or _safe_float(y_prev.get("n_income")) or 0.0
        ta_prev = _safe_float(b_prev.get("total_assets")) or 0.0
        te_prev = _safe_float(b_prev.get("total_hldr_eqy_exc_min_int")) or _safe_float(b_prev.get("total_equity")) or 0.0

        if rev_now > 0 and ta_now > 0 and te_now > 0 and rev_prev > 0 and ta_prev > 0 and te_prev > 0:
            nm_now = ni_now / rev_now
            at_now = rev_now / ta_now
            lev_now = ta_now / te_now
            roe_now = nm_now * at_now * lev_now

            nm_prev = ni_prev / rev_prev
            at_prev = rev_prev / ta_prev
            lev_prev = ta_prev / te_prev
            roe_prev = nm_prev * at_prev * lev_prev

            if (roe_prev - roe_now) > 0.10:
                flags.append(RedFlagItem(
                    id=make_flag_id("DuPont", "roe_severe_deterioration"),
                    framework="DuPont",
                    level=LEVEL_FATAL,
                    title="盈利能力系统性崩塌 (DuPont ROE 同比暴跌 > 10pp)",
                    value=round((roe_prev - roe_now) * 100, 1),
                    threshold="降幅 > 10pp",
                    evidence=f"ROE由 {roe_prev*100:.1f}% 崩塌至 {roe_now*100:.1f}% (净利率由 {nm_prev*100:.1f}% 降至 {nm_now*100:.1f}%)",
                    node="quality",
                    metric_refs=["roe"],
                ))
            elif nm_now < 0.02 and lev_now > 3.0:
                flags.append(RedFlagItem(
                    id=make_flag_id("DuPont", "high_leverage_low_margin"),
                    framework="DuPont",
                    level=LEVEL_HIGH,
                    title="高杠杆虚胖型 ROE (净利率不足 2% 纯靠杠杆支撑)",
                    value=round(lev_now, 2),
                    threshold="杠杆乘数 > 3.0 & 净利率 < 2%",
                    evidence=f"权益乘数={lev_now:.2f}倍，净利率仅={nm_now*100:.2f}%",
                    node="quality",
                    metric_refs=["roe"],
                ))

        return flags

    # ─────────────────────────────────────────────────────────────
    # Framework 5: Buffett Quality Checks (对齐 Ashare financial_audit.py:422)
    # ─────────────────────────────────────────────────────────────
    def _check_buffett_quality(self, bs: pd.DataFrame, inc: pd.DataFrame, cf: pd.DataFrame) -> list[RedFlagItem]:
        flags = []
        if bs.empty:
            return flags

        b_now = bs.iloc[-1]

        # 1. 商誉/净资产 (仅需资产负债表即可检验)
        goodwill = _safe_float(b_now.get("goodwill")) or 0.0
        te = _safe_float(b_now.get("total_hldr_eqy_exc_min_int")) or _safe_float(b_now.get("total_equity")) or 0.0
        if te and (goodwill / te) > 0.30:
            gw_ratio = goodwill / te
            flags.append(RedFlagItem(
                id=make_flag_id("Buffett", "goodwill_overhang"),
                framework="Buffett Quality",
                level=LEVEL_FATAL if gw_ratio > 0.50 else LEVEL_HIGH,
                title="巨额商誉悬顶 (存在年报商誉大额减值暴雷风险)",
                value=round(gw_ratio, 3),
                threshold="商誉/净资产 > 30% 警示，> 50% 致命",
                evidence=f"账面商誉={goodwill/1e8:.2f} 亿，占净资产比例高达 {gw_ratio*100:.1f}%",
                node="path",
                metric_refs=["goodwill"],
            ))

        if inc.empty:
            return flags

        y_now = inc.iloc[-1]
        ni = _safe_float(y_now.get("n_income_attr_p")) or _safe_float(y_now.get("n_income")) or 0.0

        # 2. OCF/NI
        if not cf.empty:
            c_now = cf.iloc[-1]
            ocf = _safe_float(c_now.get("n_cashflow_act")) or 0.0
            if ni and abs(ni) > 1e5:
                ratio = ocf / ni
                if ratio < 0.8:
                    flags.append(RedFlagItem(
                        id=make_flag_id("Buffett", "cfo_ni_ratio_weak"),
                        framework="Buffett Quality",
                        level=LEVEL_HIGH if ratio < 0.5 else LEVEL_MEDIUM,
                        title="利润质量偏弱 (经营现金流/净利润低于及格线)",
                        value=round(ratio, 3),
                        threshold="OCF/NI < 0.8 警示，< 0.5 严重",
                        evidence=f"OCF={ocf/1e8:.2f}亿 / NI={ni/1e8:.2f}亿 (现金覆盖率={ratio*100:.1f}%)",
                        node="quality",
                        metric_refs=["ocf_ni"],
                    ))

        # 3. 剪刀差检测 (需要至少 2 期)
        if len(inc) >= 2 and len(bs) >= 2:
            y_prev = inc.iloc[-2]
            b_prev = bs.iloc[-2]

            rev_now = _safe_float(y_now.get("revenue")) or 0.0
            rev_prev = _safe_float(y_prev.get("revenue")) or 0.0
            rec_now = _safe_float(b_now.get("accounts_receiv")) or 0.0
            rec_prev = _safe_float(b_prev.get("accounts_receiv")) or 0.0
            inv_now = _safe_float(b_now.get("inventories")) or 0.0
            inv_prev = _safe_float(b_prev.get("inventories")) or 0.0

            if rev_prev > 0 and rev_now > 0:
                rev_g = (rev_now - rev_prev) / rev_prev

                # 应收账款增速远高于营收增速
                if rec_prev > 0:
                    rec_g = (rec_now - rec_prev) / rec_prev
                    if (rec_g - rev_g) > 0.20:
                        flags.append(RedFlagItem(
                            id=make_flag_id("Buffett", "receivable_scissors_gap"),
                            framework="Buffett Quality",
                            level=LEVEL_HIGH,
                            title="应收账款增速远超营业收入 (放宽信用激进确认)",
                            value=round((rec_g - rev_g) * 100, 1),
                            threshold="应收增速 - 营收增速 > 20pp",
                            evidence=f"应收增速 {rec_g*100:.1f}% vs 营收增速 {rev_g*100:.1f}% (剪刀差 {(rec_g-rev_g)*100:.1f}pp)",
                            node="quality",
                            metric_refs=["receivables"],
                        ))

                # 存货增速远超营收增速
                if inv_prev > 0:
                    inv_g = (inv_now - inv_prev) / inv_prev
                    if (inv_g - rev_g) > 0.30:
                        flags.append(RedFlagItem(
                            id=make_flag_id("Buffett", "inventory_scissors_gap"),
                            framework="Buffett Quality",
                            level=LEVEL_MEDIUM,
                            title="存货增速远超营业收入 (存货积压减值雷)",
                            value=round((inv_g - rev_g) * 100, 1),
                            threshold="存货增速 - 营收增速 > 30pp",
                            evidence=f"存货增速 {inv_g*100:.1f}% vs 营收增速 {rev_g*100:.1f}% (剪刀差 {(inv_g-rev_g)*100:.1f}pp)",
                            node="quality",
                            metric_refs=["inventory"],
                        ))

        # 4. 非经常性损益占比过高
        op = _safe_float(y_now.get("operate_profit"))
        total_p = _safe_float(y_now.get("total_profit")) or ni
        if total_p and abs(total_p) > 1e5 and op is not None:
            non_op = total_p - op
            non_op_ratio = abs(non_op) / abs(total_p)
            if non_op_ratio > 0.30:
                flags.append(RedFlagItem(
                    id=make_flag_id("Buffett", "non_operating_profit_high"),
                    framework="Buffett Quality",
                    level=LEVEL_HIGH if non_op_ratio > 0.50 else LEVEL_MEDIUM,
                    title="非经常性损益占比过高 (盈利依赖非主营)",
                    value=round(non_op_ratio, 2),
                    threshold="|非经常性损益| / |利润总额| > 30%",
                    evidence=f"非经收益={non_op/1e8:.2f} 亿，占利润总额比例高达 {non_op_ratio*100:.1f}%",
                    node="quality",
                    metric_refs=["non_operating"],
                ))

        return flags

    # ─────────────────────────────────────────────────────────────
    # Framework 6: 主营业务侵蚀 (投资收益占营业利润过高, 对齐 Ashare financial_audit.py:523)
    # ─────────────────────────────────────────────────────────────
    def _check_invest_income_erosion(self, inc: pd.DataFrame) -> list[RedFlagItem]:
        flags = []
        if inc.empty:
            return flags

        now = inc.iloc[-1]
        op = _safe_float(now.get("operate_profit"))
        if not op or op <= 0:
            return flags

        inv = (_safe_float(now.get("invest_income")) or 0.0) + (_safe_float(now.get("fv_value_chg_gain")) or 0.0)
        ratio = inv / op
        if ratio > 0.30:
            flags.append(RedFlagItem(
                id=make_flag_id("Buffett", "invest_income_in_operating_profit"),
                framework="Buffett Quality",
                level=LEVEL_HIGH if ratio > 0.50 else LEVEL_MEDIUM,
                title="投资收益占营业利润过高 (非主营收益顶高估值)",
                value=round(ratio, 3),
                threshold="(投资收益+公允价值变动)/营业利润 > 30%",
                evidence=f"投资类收益 {inv/1e8:.2f}亿 / 营业利润 {op/1e8:.2f}亿 (占比 {ratio*100:.1f}%)",
                node="quality",
                metric_refs=["non_operating"],
            ))

        return flags

    # ─────────────────────────────────────────────────────────────
    # Framework 7: Sloan Accrual Anomaly (对齐 Ashare financial_audit.py:581)
    # ─────────────────────────────────────────────────────────────
    def _check_sloan(self, bs: pd.DataFrame, inc: pd.DataFrame, cf: pd.DataFrame) -> list[RedFlagItem]:
        flags = []
        if bs.empty or inc.empty or cf.empty:
            return flags

        ta = _safe_float(bs.iloc[-1].get("total_assets"))
        ni = _safe_float(inc.iloc[-1].get("n_income")) or _safe_float(inc.iloc[-1].get("n_income_attr_p"))
        cfo = _safe_float(cf.iloc[-1].get("n_cashflow_act"))

        if not ta or ta <= 0 or ni is None or cfo is None:
            return flags

        accrual_ratio = (ni - cfo) / ta
        if abs(accrual_ratio) > config.SLOAN_ACCRUAL_FATAL_RATIO:
            flags.append(RedFlagItem(
                id=make_flag_id("Sloan", "high_accrual"),
                framework="Sloan Accrual",
                level=LEVEL_HIGH if accrual_ratio > config.SLOAN_ACCRUAL_FATAL_RATIO else LEVEL_MEDIUM,
                title="高应计异象 (纸面富贵，经营现金流严重落后利润)",
                value=round(accrual_ratio, 3),
                threshold=f"|NI - OCF| / TA > {config.SLOAN_ACCRUAL_FATAL_RATIO*100:.0f}%",
                evidence=f"应计利润率={accrual_ratio*100:.1f}% (应计额={(ni-cfo)/1e8:.2f}亿 / 总资产={ta/1e8:.2f}亿)",
                node="quality",
                metric_refs=["accrual"],
            ))

        return flags

    # ─────────────────────────────────────────────────────────────
    # Framework 8: Governance Red Flags (对齐 Ashare financial_audit.py:619)
    # ─────────────────────────────────────────────────────────────
    def _check_governance(self, gov: dict[str, Any]) -> list[RedFlagItem]:
        flags = []
        pledge = _safe_float(gov.get("pledge_ratio"), 0.0)
        if pledge > config.PLEDGE_FATAL_RATIO:
            flags.append(RedFlagItem(
                id=make_flag_id("Governance", "fatal_pledge_ratio"),
                framework="Governance",
                level=LEVEL_FATAL,
                title="控股股东高比例质押暴雷风险 (平仓线悬顶)",
                value=round(pledge, 3),
                threshold=f"持股质押比例 > {config.PLEDGE_FATAL_RATIO*100:.0f}% 致命",
                evidence=f"控股股东/实控人累计质押比例高达 {pledge*100:.1f}%，极易遭遇被动平仓与连环跌停",
                node="path",
                metric_refs=["pledge"],
            ))
        elif pledge > 0.50:
            flags.append(RedFlagItem(
                id=make_flag_id("Governance", "high_pledge_ratio"),
                framework="Governance",
                level=LEVEL_HIGH,
                title="控股股东质押比例偏高",
                value=round(pledge, 3),
                threshold="持股质押比例 > 50% 警示",
                evidence=f"质押比例 {pledge*100:.1f}%",
                node="path",
                metric_refs=["pledge"],
            ))

        if gov.get("has_reduction_plan") or gov.get("hold_decrease_shares", 0) > 1_000_000:
            flags.append(RedFlagItem(
                id=make_flag_id("Governance", "shareholder_reduction"),
                framework="Governance",
                level=LEVEL_HIGH,
                title="大股东/高管近期有集中减持计划",
                value="在途减持",
                threshold="净减持 > 100 万股或在途公告",
                evidence="公告显示存在大股东竞价减持计划或减持超 100 万股，高位抛压沉重",
                node="path",
                metric_refs=["top10_change"],
            ))

        # 股权极度分散无实控人风险
        top1_ratio = _safe_float(gov.get("top1_holder_ratio"))
        if top1_ratio is not None and top1_ratio < 0.10:
            flags.append(RedFlagItem(
                id=make_flag_id("Governance", "dispersed_ownership"),
                framework="Governance",
                level=LEVEL_MEDIUM,
                title="无实控人与股权极度分散风险",
                value=round(top1_ratio * 100, 1),
                threshold="第一大股东持股比例 < 10%",
                evidence=f"第一大股东持股仅 {top1_ratio*100:.1f}%，极易发生控制权争夺或内部人治理失灵",
                node="path",
                metric_refs=["governance"],
            ))

        return flags

    # ─────────────────────────────────────────────────────────────
    # Framework 9: Shareholder Flow (对齐 Ashare financial_audit.py:692)
    # ─────────────────────────────────────────────────────────────
    def _check_shareholder_flow(self, gov: dict[str, Any]) -> list[RedFlagItem]:
        flags = []
        holder_change_pct = _safe_float(gov.get("holder_change_pct"))
        if holder_change_pct is not None:
            if holder_change_pct > 20.0:
                flags.append(RedFlagItem(
                    id=make_flag_id("ShareholderFlow", "holder_surge_fatal"),
                    framework="Shareholder Flow",
                    level=LEVEL_HIGH,
                    title="股东户数急剧激增 (散户接盘，主力高位出逃)",
                    value=round(holder_change_pct, 1),
                    threshold="环比增加 > 20%",
                    evidence=f"最新一期股东户数环比激增 {holder_change_pct:.1f}%，筹码集中度迅速恶化",
                    node="path",
                    metric_refs=["holder_count"],
                ))
            elif holder_change_pct > 5.0:
                flags.append(RedFlagItem(
                    id=make_flag_id("ShareholderFlow", "holder_increase"),
                    framework="Shareholder Flow",
                    level=LEVEL_MEDIUM,
                    title="股东户数上升 (筹码分散与高位承接风险)",
                    value=round(holder_change_pct, 1),
                    threshold="环比增加 > 5%",
                    evidence=f"股东户数环比增加 {holder_change_pct:.1f}%，散户新进涌入",
                    node="path",
                    metric_refs=["holder_count"],
                ))
            elif holder_change_pct < -5.0:
                flags.append(RedFlagItem(
                    id=make_flag_id("ShareholderFlow", "holder_decrease_positive"),
                    framework="Shareholder Flow",
                    level=LEVEL_LOW,
                    title="股东户数减少 (筹码向主力集中)",
                    value=round(holder_change_pct, 1),
                    threshold="环比减少 > 5%",
                    evidence=f"股东户数环比减少 {abs(holder_change_pct):.1f}%，主力吸筹锁仓",
                    node="path",
                    metric_refs=["holder_count"],
                ))

        return flags

    # ─────────────────────────────────────────────────────────────
    # Framework 9: Forward Guidance Anomaly (对齐 Ashare financial_audit.py:758)
    # ─────────────────────────────────────────────────────────────
    def _check_forecast_anomaly(self, gov: dict[str, Any]) -> list[RedFlagItem]:
        flags = []
        fc = gov.get("forecast")
        if not fc or not isinstance(fc, dict):
            return flags
        ftype = str(fc.get("type") or "")
        p_min = _safe_float(fc.get("p_change_min"))
        p_max = _safe_float(fc.get("p_change_max"))
        net_min = _safe_float(fc.get("net_profit_min"))
        ann_date = str(fc.get("ann_date") or "")

        if any(k in ftype for k in ["首亏", "预亏", "续亏"]):
            flags.append(RedFlagItem(
                id=make_flag_id("Forecast", "negative_forecast"),
                framework="Forecast Anomaly",
                level=LEVEL_FATAL if "首亏" in ftype else LEVEL_HIGH,
                title=f"业绩预告负面预警: {ftype}",
                value=ftype,
                threshold="首亏/预亏/续亏 = 负面预告",
                evidence=f"{ann_date} 预告类型={ftype}，变动 {p_min}%~{p_max}%" + (f"，净利下限 {net_min/1e4:.0f}万" if net_min else ""),
                node="state",
                metric_refs=["forecast"],
            ))
        elif any(k in ftype for k in ["略减", "预减"]):
            flags.append(RedFlagItem(
                id=make_flag_id("Forecast", "decline_forecast"),
                framework="Forecast Anomaly",
                level=LEVEL_MEDIUM,
                title=f"业绩预告边际下滑: {ftype}",
                value=ftype,
                threshold="预减 = 边际负面",
                evidence=f"{ann_date} 预告类型={ftype}，变动 {p_min}%~{p_max}%",
                node="state",
                metric_refs=["forecast"],
            ))

        if p_min is not None and p_max is not None:
            width = abs(p_max - p_min)
            if width > 50:
                flags.append(RedFlagItem(
                    id=make_flag_id("Forecast", "wide_forecast_spread"),
                    framework="Forecast Anomaly",
                    level=LEVEL_MEDIUM,
                    title="预告区间过宽 (业绩不确定性大)",
                    value=round(width, 1),
                    threshold="区间宽度 > 50pp",
                    evidence=f"最新预告区间宽度高达 {width:.1f}pp ({p_min}%~{p_max}%)",
                    node="state",
                    metric_refs=["forecast"],
                ))
        return flags

    # ─────────────────────────────────────────────────────────────
    # Framework 10: Valuation Anomaly (对齐 Ashare financial_audit.py:812)
    # ─────────────────────────────────────────────────────────────
    def _check_valuation(self, bs: pd.DataFrame, inc: pd.DataFrame, q: dict[str, Any]) -> list[RedFlagItem]:
        flags = []
        if bs.empty or inc.empty:
            return flags

        eq = _safe_float(bs.iloc[-1].get("total_hldr_eqy_exc_min_int")) or _safe_float(bs.iloc[-1].get("total_equity"))
        ni = _safe_float(inc.iloc[-1].get("n_income_attr_p")) or _safe_float(inc.iloc[-1].get("n_income"))
        price = _safe_float(q.get("close"))

        if not eq or eq <= 0 or not price or price <= 0:
            return flags

        total_share = _safe_float(bs.iloc[-1].get("total_share"))
        if not total_share or total_share <= 0:
            return flags

        mv = price * total_share
        pb = mv / eq
        roe = (ni / eq) if ni else 0.0

        # 1. PB vs ROE 错配 (Gordon 检验: 理论合理 PB ≈ ROE / 8%)
        fair_pb = (roe / 0.08) if roe > 0 else 0.5
        if fair_pb > 0 and pb > fair_pb * 2.0:
            flags.append(RedFlagItem(
                id=make_flag_id("Valuation", "pb_roe_mismatch"),
                framework="Valuation",
                level=LEVEL_HIGH,
                title="PB vs ROE 严重错配 (市场透支未来盈利预期)",
                value=round(pb / fair_pb, 2),
                threshold="PB / 合理PB > 2 警示",
                evidence=f"市净率 {pb:.2f} 倍; 按 ROE={roe*100:.1f}% 理论合理 PB 仅约 {fair_pb:.2f} 倍，现价透支达 {pb/fair_pb:.1f} 倍",
                node="odds",
                metric_refs=["pb"],
            ))
        elif fair_pb > 0 and pb < fair_pb * 0.5:
            flags.append(RedFlagItem(
                id=make_flag_id("Valuation", "pb_roe_undervalued"),
                framework="Valuation",
                level=LEVEL_LOW,
                title="PB vs ROE 具备显著估值安全边际",
                value=round(pb / fair_pb, 2),
                threshold="PB / 合理PB < 0.5",
                evidence=f"市净率 {pb:.2f} 倍，低于理论合理估值 {fair_pb:.2f} 倍一半以上",
                node="odds",
                metric_refs=["pb"],
            ))

        # 2. 小盘亏损 + 高 PB 双杀 (市值 < 100 亿 + 亏损 + PB > 5)
        if mv < 10_000_000_000 and (ni is None or ni <= 0) and pb > 5.0:
            flags.append(RedFlagItem(
                id=make_flag_id("Valuation", "small_cap_loss_high_pb"),
                framework="Valuation",
                level=LEVEL_HIGH,
                title="小盘亏损 + 高 PB 纯题材投机双杀",
                value=f"mv={mv/1e8:.1f}亿, PB={pb:.1f}x",
                threshold="市值 < 100 亿 + 亏损 + PB > 5",
                evidence=f"总市值 {mv/1e8:.1f} 亿元，当前亏损，PB={pb:.2f}x 缺乏基本面支撑",
                node="odds",
                metric_refs=["pb"],
            ))

        return flags

    # ─────────────────────────────────────────────────────────────
    # Framework 11: Related-Party Exposure (对齐 Ashare financial_audit.py:954)
    # ─────────────────────────────────────────────────────────────
    def _check_related_party_exposure(self, bs: pd.DataFrame, inc: pd.DataFrame) -> list[RedFlagItem]:
        flags = []
        if bs.empty:
            return flags

        b_now = bs.iloc[-1]
        ta = _safe_float(b_now.get("total_assets"))
        lt_now = _safe_float(b_now.get("lt_eqt_invest"), 0.0)

        # 长期股权投资大幅波动 (需 2 期，且遵循会计重要性原则：占总资产 > 1% 或绝对金额变动 > 5000 万)
        if len(bs) >= 2 and ta and ta > 0:
            b_prev = bs.iloc[-2]
            lt_prev = _safe_float(b_prev.get("lt_eqt_invest"), 0.0)
            if lt_prev and lt_prev > 0 and lt_now:
                chg = (lt_now - lt_prev) / lt_prev
                # 重要性门槛: 长期股权投资占总资产至少达到 1% 或变动绝对金额超 5000 万，微小体量排除误报
                is_material = (lt_now / ta > 0.01) or (abs(lt_now - lt_prev) > 50_000_000)
                if is_material and abs(chg) > 0.30:
                    flags.append(RedFlagItem(
                        id=make_flag_id("RelatedParty", "lt_equity_fluctuation"),
                        framework="Related-Party Exposure",
                        level=LEVEL_HIGH if chg < 0 else LEVEL_MEDIUM,
                        title="长期股权投资大幅波动 (参股公司潜在权益法爆雷风险)",
                        value=round(chg, 3),
                        threshold="变动幅度 > 30% 且占总资产 > 1%",
                        evidence=f"长期股权投资由 {lt_prev/1e8:.2f} 亿变为 {lt_now/1e8:.2f} 亿 (变动 {chg*100:+.1f}%)，占总资产 {lt_now/ta*100:.2f}%",
                        node="quality",
                        metric_refs=["related_party"],
                    ))

        # 投资收益持续大额负值
        if not inc.empty:
            now_inc = inc.iloc[-1]
            inv_inc = _safe_float(now_inc.get("invest_income"), 0.0)
            if inv_inc < -10_000_000:
                flags.append(RedFlagItem(
                    id=make_flag_id("RelatedParty", "invest_income_loss"),
                    framework="Related-Party Exposure",
                    level=LEVEL_HIGH,
                    title="投资收益大额负值 (联营企业权益法损失拖累)",
                    value=round(inv_inc / 1e8, 2),
                    threshold="投资收益 < -1000 万元",
                    evidence=f"最新期投资收益亏损 {inv_inc/1e8:.2f} 亿元",
                    node="quality",
                    metric_refs=["related_party"],
                ))

        return flags
