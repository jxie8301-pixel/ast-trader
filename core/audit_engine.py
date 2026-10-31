"""11 classic accounting and forensic audit frameworks for AST-Trader.
Strictly aligned with Ashare-researchreport/scripts/financial_audit.py.
"""
from __future__ import annotations

import logging
import math
from typing import Any

import pandas as pd

import config
from .industry import classify_industry, is_financial
from .red_flags import (
    LEVEL_FATAL,
    LEVEL_HIGH,
    LEVEL_INFO,
    LEVEL_LOW,
    LEVEL_MEDIUM,
    RedFlagItem,
    make_flag_id,
)

logger = logging.getLogger("ast_trader.core.audit_engine")


def _safe_float(v: Any, default: float | None = None) -> float | None:
    if v is None:
        return default
    try:
        val = float(v)
        return default if math.isnan(val) else val
    except (ValueError, TypeError):
        return default


def _first_present(d: Any, keys: tuple[str, ...]) -> float | None:
    """按顺序取第一个非空且合法的浮点数字段值。"""
    if d is None:
        return None
    for k in keys:
        if isinstance(d, dict):
            val = d.get(k)
        elif hasattr(d, "get"):
            val = d.get(k)
        elif hasattr(d, "__getitem__"):
            try:
                val = d[k]
            except (KeyError, IndexError):
                val = None
        else:
            val = None
        sf = _safe_float(val)
        if sf is not None:
            return sf
    return None


def _model_applicable(model: str, industry: str | None) -> bool:
    """根据标的行业判定该审计模型是否适用。金融业等非制造业经验模型主动弃权。"""
    if not industry:
        return True
    lookup_key = "AltmanZ" if model in ("Altman", "AltmanZ") else model
    blocked = config.AUDIT_MODEL_INDUSTRY_BLOCKLIST.get(lookup_key, ())
    if industry in blocked:
        return False
    if "金融" in blocked and is_financial(industry):
        return False
    return True


def _abstention_flag(model: str, industry: str, model_cn: str, reason: str) -> RedFlagItem:
    return RedFlagItem(
        id=make_flag_id("Governance", f"{model.lower()}_industry_abstention"),
        framework="Governance",
        level=LEVEL_INFO,
        title=f"{model_cn} 模型不适用 ({industry}业) · 主动弃权",
        value=None,
        threshold="模型校验域准入适用性检查",
        evidence=reason,
        node="path",
        metric_refs=[model],
    )


def _annual(df: pd.DataFrame) -> pd.DataFrame:
    """年报切片 (仅取 1231 结尾的表) (对齐 Ashare financial_audit.py:90)"""
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
    """11 大经典财务与法务会计审计引擎."""

    def __init__(self) -> None:
        pass

    def run_audit(
        self,
        balance_df: pd.DataFrame,
        cashflow_df: pd.DataFrame,
        income_df: pd.DataFrame,
        governance_info: dict[str, Any] | None = None,
        quote_info: dict[str, Any] | None = None,
        ai: dict[str, Any] | None = None,
    ) -> list[RedFlagItem]:
        """对齐 11 大核心框架与本土法务排雷."""
        flags: list[RedFlagItem] = []

        ann_bs = _annual(balance_df)
        ann_inc = _annual(income_df)
        ann_cf = _annual(cashflow_df)

        gov = governance_info or {}
        industry = classify_industry(
            industry=gov.get("industry"),
            name=(quote_info or {}).get("name"),
            concepts=gov.get("concepts"),
            main_business=gov.get("main_business"),
        )

        # 1. Piotroski F-Score (9 签号)
        flags.extend(self._check_piotroski(ann_bs, ann_inc, ann_cf, industry=industry))

        # 2. Beneish M-Score (8 变量)
        flags.extend(self._check_beneish(ann_bs, ann_inc, ann_cf, industry=industry))

        # 3. Altman Z-Score (5 变量破产预警)
        flags.extend(self._check_altman(ann_bs, ann_inc, quote_info, industry=industry))

        # 4. DuPont 3/5 分解与 ROE 恶化
        flags.extend(self._check_dupont(ann_bs, ann_inc, industry=industry))

        # 5. Buffett Quality Checks (剪刀差、现金覆盖与非经占比)
        flags.extend(self._check_buffett_quality(ann_bs, ann_inc, ann_cf, industry=industry))

        # 6. 主营业务侵蚀 (投资收益占营业利润过高)
        flags.extend(self._check_invest_income_erosion(income_df, industry=industry))

        # 7. Sloan Accrual Anomaly (高应计异象)
        flags.extend(self._check_sloan(ann_bs, ann_inc, ann_cf, industry=industry))

        # 8. Governance Red Flags (高比例质押、股东减持)
        if governance_info:
            flags.extend(self._check_governance(governance_info))

        # 9. Shareholder Flow (股东户数变动与筹码散户化)
        if governance_info:
            flags.extend(self._check_shareholder_flow(governance_info))

        # 10. Forward Guidance Anomaly (业绩预告异常与首亏/预亏)
        if governance_info:
            flags.extend(self._check_forecast_anomaly(governance_info))

        # 11. Valuation Anomaly (估值透支、PB vs ROE 错配)
        if quote_info:
            flags.extend(self._check_valuation(ann_bs, ann_inc, quote_info))

        # 12. Related-Party & Subsidiary Exposure (长期股权投资与关联方敞口)
        flags.extend(self._check_related_party_exposure(ann_bs, ann_inc))

        # 13. A-Share Forensic: 存贷双高与利息/债务倒挂排雷
        target_bs = ann_bs if (ann_bs is not None and not ann_bs.empty) else balance_df
        target_inc = ann_inc if (ann_inc is not None and not ann_inc.empty) else income_df
        flags.extend(self._check_high_cash_high_debt(target_bs, target_inc, industry=industry))

        # 14. A-Share Forensic: 在建工程长期不转固与异常膨胀排雷
        flags.extend(self._check_cip_anomaly(target_bs, target_inc, industry=industry))

        # AI 治理与监管文本穿透增强
        if ai:
            try:
                from core.ai_coprocessor.guard import nominations_to_flags
                flags.extend(nominations_to_flags(ai))
            except Exception as exc:
                logger.warning("AI 治理提名并入失败: %s", exc)

        # 框架与排雷红旗严格去重 (按 framework, title, node 唯一性收敛)
        deduped_flags: list[RedFlagItem] = []
        seen_keys: set[tuple[str, str, str]] = set()
        for f in flags:
            key = (str(f.framework).strip(), str(f.title).strip(), str(f.node).strip())
            if key not in seen_keys:
                seen_keys.add(key)
                deduped_flags.append(f)

        return deduped_flags

    # ─────────────────────────────────────────────────────────────
    # Framework 1: Piotroski F-Score (9 签号打分)
    # ─────────────────────────────────────────────────────────────
    def _check_piotroski(
        self, bs: pd.DataFrame, inc: pd.DataFrame, cf: pd.DataFrame,
        industry: str | None = None,
    ) -> list[RedFlagItem]:
        flags = []
        if not _model_applicable("Piotroski", industry):
            return [_abstention_flag(
                "Piotroski", industry or "金融", "Piotroski F-Score",
                f"标的归属于{industry or '金融'}业，F-Score在金融业不具备判别力，主动弃权。"
            )]
        if len(inc) < 2 or len(bs) < 2 or len(cf) < 2:
            return flags

        y_now, y_prev = inc.iloc[-1], inc.iloc[-2]
        bs_now, bs_prev = bs.iloc[-1], bs.iloc[-2]
        cf_now, cf_prev = cf.iloc[-1], cf.iloc[-2]

        ni = _first_present(y_now, ("n_income_attr_p", "n_income"))
        ni_prev = _first_present(y_prev, ("n_income_attr_p", "n_income"))
        ocf = _safe_float(cf_now.get("n_cashflow_act"))
        if ni is None or ocf is None or ni_prev is None:
            return flags

        score = 0
        details: list[str] = []

        # 1. NI > 0
        ok_ni = ni > 0
        score += int(ok_ni)
        details.append(f"NI>0={'✓' if ok_ni else '✗'}")

        # 2. ROA > 0
        ta_now = _safe_float(bs_now.get("total_assets"))
        ta_prev = _safe_float(bs_prev.get("total_assets"))
        if ta_now and ta_now > 0:
            roa = ni / ta_now
            ok_roa = roa > 0
        else:
            roa = None
            ok_roa = False
        score += int(ok_roa)
        details.append(f"ROA>0={'✓' if ok_roa else '✗'}")

        # 3. OCF > 0
        ok_ocf = ocf > 0
        score += int(ok_ocf)
        details.append(f"OCF>0={'✓' if ok_ocf else '✗'}")

        # 4. OCF > NI
        ok_cfo_ni = ocf > ni
        score += int(ok_cfo_ni)
        details.append(f"OCF>NI={'✓' if ok_cfo_ni else '✗'}")

        # 5. ROA 同比上升
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

        # 8. 毛利率同比上升
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
                id=make_flag_id("Piotroski", "f_score_weak"),
                framework="Piotroski F-Score",
                level=LEVEL_HIGH,
                title="基本面健康度堪忧 (Piotroski F-Score 极低)",
                value=score,
                threshold="F <= 3",
                evidence=f"F-Score={score}/9 ({', '.join(details)})",
                node="quality",
                metric_refs=["f_score"],
            ))
        elif score >= 8:
            flags.append(RedFlagItem(
                id=make_flag_id("Piotroski", "f_score_strong"),
                framework="Piotroski F-Score",
                level=LEVEL_LOW,
                title="基本面健康度优异 (Piotroski F-Score 强健)",
                value=score,
                threshold="F >= 8",
                evidence=f"F-Score={score}/9 ({', '.join(details)})",
                node="quality",
                metric_refs=["f_score"],
            ))

        return flags

    # ─────────────────────────────────────────────────────────────
    # Framework 2: Beneish M-Score (8 变量财务操纵检验)
    # ─────────────────────────────────────────────────────────────
    def _check_beneish(
        self, bs: pd.DataFrame, inc: pd.DataFrame, cf: pd.DataFrame,
        industry: str | None = None,
    ) -> list[RedFlagItem]:
        flags = []
        if not _model_applicable("Beneish", industry):
            return [_abstention_flag(
                "Beneish", industry or "金融", "Beneish M-Score",
                f"标的归属于{industry or '金融'}业，Beneish财务操纵模型不适用，主动弃权。"
            )]
        if len(inc) < 2 or len(bs) < 2 or len(cf) < 2:
            return flags

        y_now, y_prev = inc.iloc[-1], inc.iloc[-2]
        b_now, b_prev = bs.iloc[-1], bs.iloc[-2]
        c_now = cf.iloc[-1]

        rev_now = _safe_float(y_now.get("revenue"))
        rev_prev = _safe_float(y_prev.get("revenue"))
        rec_now = _safe_float(b_now.get("accounts_receiv")) or 0.0
        rec_prev = _safe_float(b_prev.get("accounts_receiv")) or 0.0

        if not rev_now or not rev_prev or rev_now <= 0 or rev_prev <= 0:
            return flags

        dsri = (rec_now / rev_now) / (rec_prev / rev_prev) if rec_prev > 0 else 1.0

        cos_now = _safe_float(y_now.get("oper_cost")) or 0.0
        cos_prev = _safe_float(y_prev.get("oper_cost")) or 0.0
        gm_now = (rev_now - cos_now) / rev_now
        gm_prev = (rev_prev - cos_prev) / rev_prev
        gmi = gm_prev / gm_now if gm_now > 0 else 1.0

        ta_now = _safe_float(b_now.get("total_assets")) or 1.0
        ta_prev = _safe_float(b_prev.get("total_assets")) or 1.0
        ca_now = _safe_float(b_now.get("total_cur_assets")) or 0.0
        ca_prev = _safe_float(b_prev.get("total_cur_assets")) or 0.0
        fa_now = _safe_float(b_now.get("fix_assets")) or 0.0
        fa_prev = _safe_float(b_prev.get("fix_assets")) or 0.0

        aqi_now = 1.0 - (ca_now + fa_now) / ta_now if ta_now > 0 else 0.0
        aqi_prev = 1.0 - (ca_prev + fa_prev) / ta_prev if ta_prev > 0 else 0.0
        aqi = aqi_now / aqi_prev if aqi_prev > 0 else 1.0

        sgi = rev_now / rev_prev
        depmi = 1.0

        sga_now = (_safe_float(y_now.get("sell_exp")) or 0.0) + (_safe_float(y_now.get("admin_exp")) or 0.0)
        sga_prev = (_safe_float(y_prev.get("sell_exp")) or 0.0) + (_safe_float(y_prev.get("admin_exp")) or 0.0)
        sgai = (sga_now / rev_now) / (sga_prev / rev_prev) if (sga_prev > 0 and rev_prev > 0) else 1.0

        ni = _first_present(y_now, ("n_income_attr_p", "n_income")) or 0.0
        cfo = _safe_float(c_now.get("n_cashflow_act")) or 0.0
        tata = (ni - cfo) / ta_now if ta_now > 0 else 0.0

        ltd_now = _safe_float(b_now.get("lt_borr")) or 0.0
        cl_now = _safe_float(b_now.get("total_cur_liab")) or 0.0
        ltd_prev = _safe_float(b_prev.get("lt_borr")) or 0.0
        cl_prev = _safe_float(b_prev.get("total_cur_liab")) or 0.0
        levi = ((ltd_now + cl_now) / ta_now) / ((ltd_prev + cl_prev) / ta_prev) if (ta_now > 0 and ta_prev > 0 and (ltd_prev + cl_prev) > 0) else 1.0

        m_score = (
            -4.84
            + 0.920 * dsri
            + 0.528 * gmi
            + 0.404 * aqi
            + 0.892 * sgi
            + 0.115 * depmi
            - 0.172 * sgai
            + 4.037 * tata
            + 0.0327 * levi
        )

        fatal_th = getattr(config, "BENEISH_M_SCORE_FATAL_THRESHOLD", -1.78)
        if m_score > fatal_th:
            flags.append(RedFlagItem(
                id=make_flag_id("Beneish", "m_score_fraud_risk"),
                framework="Beneish M-Score",
                level=LEVEL_FATAL,
                title="财务操纵高风险 (Beneish M-Score 异常)",
                value=round(m_score, 3),
                threshold=f"M > {fatal_th} 操纵嫌疑",
                evidence=f"M-Score={m_score:.3f} 超过阈值 {fatal_th} (DSRI={dsri:.2f}, GMI={gmi:.2f}, SGI={sgi:.2f}, TATA={tata:.3f})",
                node="quality",
                metric_refs=["m_score"],
            ))
        elif m_score > -2.22:
            flags.append(RedFlagItem(
                id=make_flag_id("Beneish", "m_score_warn"),
                framework="Beneish M-Score",
                level=LEVEL_HIGH,
                title="财务数据异象预警 (Beneish M-Score 处于灰色地带)",
                value=round(m_score, 3),
                threshold=f"-2.22 < M <= {fatal_th}",
                evidence=f"M-Score={m_score:.3f} 处于财务操纵临界灰区",
                node="quality",
                metric_refs=["m_score"],
            ))

        return flags

    # ─────────────────────────────────────────────────────────────
    # Framework 3: Altman Z-Score (破产风险预警)
    # ─────────────────────────────────────────────────────────────
    def _check_altman(
        self, bs: pd.DataFrame, inc: pd.DataFrame, quote_info: dict[str, Any] | None = None,
        industry: str | None = None,
    ) -> list[RedFlagItem]:
        flags = []
        if not _model_applicable("Altman", industry):
            return [_abstention_flag(
                "Altman", industry or "金融", "Altman Z-Score",
                f"标的归属于{industry or '金融'}业，Altman破产预警模型不适用金融业，主动弃权。"
            )]
        if bs.empty or inc.empty:
            return flags

        b_now = bs.iloc[-1]
        y_now = inc.iloc[-1]

        ta = _safe_float(b_now.get("total_assets"))
        tl = _safe_float(b_now.get("total_liab"))
        tca = _safe_float(b_now.get("total_cur_assets")) or 0.0
        tcl = _safe_float(b_now.get("total_cur_liab")) or 0.0
        re = _safe_float(b_now.get("undistr_profit")) or 0.0
        ebit = _safe_float(y_now.get("operate_profit")) or 0.0
        rev = _safe_float(y_now.get("revenue")) or 0.0

        if not ta or ta <= 0 or not tl or tl <= 0:
            return flags

        te = _first_present(b_now, ("total_hldr_eqy_inc_min_int", "total_hldr_eqy_exc_min_int", "total_equity"))
        mv = float((quote_info or {}).get("total_mv") or 0.0)
        if mv <= 0:
            mv = te if te is not None else 1.0

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
    # Framework 4: DuPont 3/5 分解
    # ─────────────────────────────────────────────────────────────
    def _check_dupont(
        self, bs: pd.DataFrame, inc: pd.DataFrame,
        industry: str | None = None,
    ) -> list[RedFlagItem]:
        flags = []
        if not _model_applicable("DuPont", industry):
            return [_abstention_flag(
                "DuPont", industry or "金融", "DuPont 分解",
                f"标的归属于{industry or '金融'}业，DuPont 分解不具备质量判别力，主动弃权。"
            )]
        if len(inc) < 2 or len(bs) < 2:
            return flags

        y_now, y_prev = inc.iloc[-1], inc.iloc[-2]
        b_now, b_prev = bs.iloc[-1], bs.iloc[-2]

        rev_now = _safe_float(y_now.get("revenue"))
        ni_now = _first_present(y_now, ("n_income_attr_p", "n_income"))
        ta_now = _safe_float(b_now.get("total_assets"))
        te_now = _first_present(b_now, ("total_hldr_eqy_exc_min_int", "total_equity"))

        rev_prev = _safe_float(y_prev.get("revenue"))
        ni_prev = _first_present(y_prev, ("n_income_attr_p", "n_income"))
        ta_prev = _safe_float(b_prev.get("total_assets"))
        te_prev = _first_present(b_prev, ("total_hldr_eqy_exc_min_int", "total_equity"))

        if None in (rev_now, ni_now, ta_now, te_now, rev_prev, ni_prev, ta_prev, te_prev):
            return flags

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
                    level=LEVEL_HIGH,
                    title="盈利能力阶段性承压 (DuPont ROE 同比大幅下滑 > 10pp)",
                    value=round((roe_prev - roe_now) * 100, 1),
                    threshold="降幅 > 10pp 警示",
                    evidence=f"ROE由 {roe_prev*100:.1f}% 下滑至 {roe_now*100:.1f}% (净利率由 {nm_prev*100:.1f}% 降至 {nm_now*100:.1f}%)",
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
    # Framework 5: Buffett Quality Checks
    # ─────────────────────────────────────────────────────────────
    def _check_buffett_quality(
        self, bs: pd.DataFrame, inc: pd.DataFrame, cf: pd.DataFrame,
        industry: str | None = None,
    ) -> list[RedFlagItem]:
        flags = []
        if not _model_applicable("Buffett", industry):
            return [_abstention_flag(
                "Buffett", industry or "金融", "Buffett 质量检查",
                f"标的归属于{industry or '金融'}业，质量检查项无对应经济含义，主动弃权。"
            )]
        if bs.empty:
            return flags

        b_now = bs.iloc[-1]
        goodwill = _safe_float(b_now.get("goodwill"))
        te = _first_present(b_now, ("total_hldr_eqy_exc_min_int", "total_equity"))
        if goodwill is not None and te is not None and te > 0 and (goodwill / te) > 0.30:
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
        rev = _safe_float(y_now.get("revenue")) or 0.0
        op = _safe_float(y_now.get("operate_profit")) or 0.0
        ni = _first_present(y_now, ("n_income_attr_p", "n_income")) or 0.0

        if not cf.empty:
            cfo = _safe_float(cf.iloc[-1].get("n_cashflow_act")) or 0.0
            if ni > 0 and cfo < 0:
                flags.append(RedFlagItem(
                    id=make_flag_id("Buffett", "negative_cfo_with_positive_ni"),
                    framework="Buffett Quality",
                    level=LEVEL_HIGH,
                    title="有利润无现金流 (盈利与经营活动现金流背离)",
                    value=round(cfo / 1e8, 2),
                    threshold="净利润 > 0 但 经营现金流 < 0",
                    evidence=f"净利润={ni/1e8:.2f} 亿，经营现金流={cfo/1e8:.2f} 亿",
                    node="quality",
                    metric_refs=["cfo_ni_ratio"],
                ))

        if len(inc) >= 2 and len(bs) >= 2:
            y_prev = inc.iloc[-2]
            b_prev = bs.iloc[-2]
            rev_prev = _safe_float(y_prev.get("revenue")) or 0.0
            rec_now = _safe_float(b_now.get("accounts_receiv")) or 0.0
            rec_prev = _safe_float(b_prev.get("accounts_receiv")) or 0.0
            if rev > 0 and rev_prev > 0 and rec_prev > 0:
                rev_g = (rev - rev_prev) / rev_prev
                rec_g = (rec_now - rec_prev) / rec_prev
                if rec_g - rev_g > 0.30 and rec_g > 0.20:
                    flags.append(RedFlagItem(
                        id=make_flag_id("Buffett", "receivable_revenue_scissors_gap"),
                        framework="Buffett Quality",
                        level=LEVEL_HIGH,
                        title="应收账款恶性剪刀差 (应收账款增速远超营收增速)",
                        value=round((rec_g - rev_g) * 100, 1),
                        threshold="应收增速 - 营收增速 > 30pp",
                        evidence=f"应收增速={rec_g*100:.1f}%, 营收增速={rev_g*100:.1f}%, 剪刀差达 {(rec_g-rev_g)*100:.1f}pp",
                        node="quality",
                        metric_refs=["scissors_gap"],
                    ))

            inv_now = _safe_float(b_now.get("inventories")) or 0.0
            inv_prev = _safe_float(b_prev.get("inventories")) or 0.0
            if rev > 0 and rev_prev > 0 and inv_prev > 0:
                rev_g = (rev - rev_prev) / rev_prev
                inv_g = (inv_now - inv_prev) / inv_prev
                if inv_g - rev_g > 0.30 and inv_g > 0.20:
                    flags.append(RedFlagItem(
                        id=make_flag_id("Buffett", "inventory_growth_divergence"),
                        framework="Buffett Quality",
                        level=LEVEL_HIGH,
                        title="存货恶性积压异象 (存货增速远超营收增速，存货积压减值风险)",
                        value=round((inv_g - rev_g) * 100, 1),
                        threshold="存货增速 - 营收增速 > 30pp",
                        evidence=f"存货增速={inv_g*100:.1f}%, 营收增速={rev_g*100:.1f}%, 剪刀差达 {(inv_g-rev_g)*100:.1f}pp",
                        node="quality",
                        metric_refs=["scissors_gap", "inventories"],
                    ))

        return flags

    # ─────────────────────────────────────────────────────────────
    # Framework 6: 主营业务侵蚀
    # ─────────────────────────────────────────────────────────────
    def _check_invest_income_erosion(
        self, inc: pd.DataFrame, industry: str | None = None,
    ) -> list[RedFlagItem]:
        flags = []
        if not _model_applicable("InvestIncomeErosion", industry):
            return [_abstention_flag(
                "InvestIncomeErosion", industry or "金融", "主营业务侵蚀模型",
                f"标的归属于{industry or '金融'}业，证券投资属于常规经营业务，主动弃权。"
            )]
        if inc.empty:
            return flags

        y_now = inc.iloc[-1]
        op = _safe_float(y_now.get("operate_profit")) or 0.0
        inv = _safe_float(y_now.get("invest_income")) or 0.0
        if op > 0 and inv > 0 and (inv / op) > 0.50:
            ratio = inv / op
            flags.append(RedFlagItem(
                id=make_flag_id("Buffett", "invest_income_erosion"),
                framework="Buffett Quality",
                level=LEVEL_HIGH,
                title="营业利润依赖非主营投资收益 (主营业务造血能力弱化)",
                value=round(ratio, 3),
                threshold="投资收益 / 营业利润 > 50%",
                evidence=f"投资收益={inv/1e8:.2f} 亿，占营业利润比例高达 {ratio*100:.1f}%",
                node="quality",
                metric_refs=["invest_income_ratio"],
            ))

        return flags

    # ─────────────────────────────────────────────────────────────
    # Framework 7: Sloan Accrual Anomaly
    # ─────────────────────────────────────────────────────────────
    def _check_sloan(
        self, bs: pd.DataFrame, inc: pd.DataFrame, cf: pd.DataFrame,
        industry: str | None = None,
    ) -> list[RedFlagItem]:
        flags = []
        if not _model_applicable("Sloan", industry):
            return [_abstention_flag(
                "Sloan", industry or "金融", "Sloan 应计异象",
                f"标的归属于{industry or '金融'}业，Sloan 应计模型不适用金融业，主动弃权。"
            )]
        if inc.empty or bs.empty or cf.empty:
            return flags

        y_now = inc.iloc[-1]
        b_now = bs.iloc[-1]
        c_now = cf.iloc[-1]

        ni = _first_present(y_now, ("n_income_attr_p", "n_income")) or 0.0
        cfo = _safe_float(c_now.get("n_cashflow_act")) or 0.0
        ta = _safe_float(b_now.get("total_assets")) or 0.0

        if ta > 0:
            accrual = (ni - cfo) / ta
            if accrual > 0.10:
                flags.append(RedFlagItem(
                    id=make_flag_id("Sloan", "high_accrual_anomaly"),
                    framework="Sloan Accrual",
                    level=LEVEL_HIGH,
                    title="高应计项目异象 (利润现金含量极低)",
                    value=round(accrual, 3),
                    threshold="应计利润 / 总资产 > 10%",
                    evidence=f"应计利润率={accrual*100:.2f}% (净利={ni/1e8:.2f}亿, CFO={cfo/1e8:.2f}亿, 总资产={ta/1e8:.2f}亿)",
                    node="quality",
                    metric_refs=["sloan_accrual"],
                ))

        return flags

    # ─────────────────────────────────────────────────────────────
    # Framework 8: Governance Red Flags
    # ─────────────────────────────────────────────────────────────
    def _check_governance(self, gov: dict[str, Any]) -> list[RedFlagItem]:
        flags = []
        if not gov:
            return flags

        # 1. 质押率
        pledge = _safe_float(gov.get("pledge_ratio"))
        fatal_pledge_th = getattr(config, "GOVERNANCE_PLEDGE_FATAL_RATIO", getattr(config, "PLEDGE_FATAL_RATIO", 0.70))
        warn_pledge_th = getattr(config, "GOVERNANCE_PLEDGE_WARN_RATIO", getattr(config, "PLEDGE_HIGH_RATIO", 0.50))
        if pledge is None:
            flags.append(RedFlagItem(
                id=make_flag_id("Governance", "unverified_pledge_ratio"),
                framework="Governance",
                level=LEVEL_INFO,
                title="质押比例未核验 (数据通道缺失，无法排查平仓风险)",
                value=None,
                threshold="控股股东质押比例需可核验",
                evidence="F10 数据未披露控股股东质押比例或数据接口未返回，无法排除极端质押爆仓风险",
                node="path",
                metric_refs=["pledge_ratio"],
            ))
        elif pledge >= fatal_pledge_th:
            flags.append(RedFlagItem(
                id=make_flag_id("Governance", "fatal_pledge_ratio"),
                framework="Governance",
                level=LEVEL_FATAL,
                title="控股股东高比例质押爆仓风险 (平仓线危机)",
                value=round(pledge, 3),
                threshold=f"质押比例 >= {fatal_pledge_th*100:.0f}% 致命",
                evidence=f"控股股东/实控人质押比例高达 {pledge*100:.1f}%，极易在下行周期触及平仓线引发被动减持踩踏",
                node="path",
                metric_refs=["pledge_ratio"],
            ))
        elif pledge >= warn_pledge_th:
            flags.append(RedFlagItem(
                id=make_flag_id("Governance", "warn_pledge_ratio"),
                framework="Governance",
                level=LEVEL_HIGH,
                title="股东质押比例偏高预警",
                value=round(pledge, 3),
                threshold=f"质押比例 >= {warn_pledge_th*100:.0f}%",
                evidence=f"质押比例 {pledge*100:.1f}%，需关注股价异动时的质押补仓压力",
                node="path",
                metric_refs=["pledge_ratio"],
            ))

        # 2. 监管违规处罚
        v_recent = int(gov.get("recent_violations") or gov.get("recent_violation_count") or 0)
        v_total = int(gov.get("total_violations") or gov.get("violation_count") or 0)
        fatal_violation_count = getattr(config, "GOVERNANCE_VIOLATION_FATAL_COUNT", 3)
        if v_recent >= fatal_violation_count:
            flags.append(RedFlagItem(
                id=make_flag_id("Governance", "fatal_regulatory_violations"),
                framework="Governance",
                level=LEVEL_FATAL,
                title="近期监管违规处罚密集 (合规失信致命)",
                value=v_recent,
                threshold=f"近1年违规处罚 >= {fatal_violation_count} 次",
                evidence=f"近1年内发生 {v_recent} 起违规处罚，反映公司内部治理与合规失控，触碰买方红线",
                node="path",
                metric_refs=["violations"],
            ))
        elif v_total > 0 or v_recent > 0 or gov.get("has_violation_record"):
            flags.append(RedFlagItem(
                id=make_flag_id("Governance", "warn_regulatory_violations"),
                framework="Governance",
                level=LEVEL_HIGH,
                title="存在历史监管处罚记录 (违规治理瑕疵预警)",
                value=max(v_recent, v_total),
                threshold="存在历史违规记录",
                evidence=f"历史记录累计 {v_total} 起违规处罚，近期 {v_recent} 起",
                node="path",
                metric_refs=["violations"],
            ))

        return flags

    # ─────────────────────────────────────────────────────────────
    # Framework 9: Shareholder Flow
    # ─────────────────────────────────────────────────────────────
    def _check_shareholder_flow(self, gov: dict[str, Any]) -> list[RedFlagItem]:
        flags = []
        flow = gov.get("holder_change_pct")
        if flow is not None:
            flow_val = _safe_float(flow)
            if flow_val is not None and flow_val > 0.20:
                flags.append(RedFlagItem(
                    id=make_flag_id("Shareholder", "retail_dispersion_risk"),
                    framework="Shareholder Flow",
                    level=LEVEL_HIGH,
                    title="筹码急剧散户化预警 (股东户数大幅激增)",
                    value=round(flow_val * 100, 1),
                    threshold="股东户数增幅 > 20%",
                    evidence=f"最新期股东户数环比激增 {flow_val*100:.1f}%，筹码呈现大幅派发散户化迹象",
                    node="tape",
                    metric_refs=["holder_change"],
                ))
        return flags

    # ─────────────────────────────────────────────────────────────
    # Framework 10: Forward Guidance Anomaly
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

        already_fatal = any(f.level == LEVEL_FATAL for f in flags)
        if (p_min is not None or p_max is not None) and not already_fatal:
            p_change_pct = min(v for v in (p_min, p_max) if v is not None)
            fatal_pct = config.FORECAST_DROP_FATAL_RATIO * 100.0
            if p_change_pct <= fatal_pct:
                flags.append(RedFlagItem(
                    id=make_flag_id("Forecast", "fatal_forecast_collapse"),
                    framework="Forecast Anomaly",
                    level=LEVEL_FATAL,
                    title="业绩预告断崖式变脸 (扣非同比暴跌)",
                    value=round(p_change_pct, 1),
                    threshold=f"预告同比变动 <= {fatal_pct:.0f}% 致命",
                    evidence=f"{ann_date} 预告同比变动下限 {p_change_pct:.1f}%，已跌破 {fatal_pct:.0f}% 断崖线，业绩变脸风险一票否决",
                    node="state",
                    metric_refs=["forecast"],
                ))

        return flags

    # ─────────────────────────────────────────────────────────────
    # Framework 11: Valuation Anomaly
    # ─────────────────────────────────────────────────────────────
    def _check_valuation(
        self, bs: pd.DataFrame, inc: pd.DataFrame, quote_info: dict[str, Any],
    ) -> list[RedFlagItem]:
        flags = []
        pe = _safe_float(quote_info.get("pe"))
        pb = _safe_float(quote_info.get("pb"))
        if pe is not None and pe > 120.0:
            flags.append(RedFlagItem(
                id=make_flag_id("Valuation", "extreme_high_pe"),
                framework="Valuation Anomaly",
                level=LEVEL_HIGH,
                title="静态市盈率畸高透支 (PE > 120x)",
                value=round(pe, 1),
                threshold="PE > 120",
                evidence=f"静态 PE 达 {pe:.1f} 倍，远超行业合理估值溢价空间",
                node="odds",
                metric_refs=["pe"],
            ))
        return flags

    # ─────────────────────────────────────────────────────────────
    # Framework 12: Related-Party Exposure
    # ─────────────────────────────────────────────────────────────
    def _check_related_party_exposure(self, bs: pd.DataFrame, inc: pd.DataFrame) -> list[RedFlagItem]:
        flags = []
        if bs.empty:
            return flags
        b_now = bs.iloc[-1]
        ta = _safe_float(b_now.get("total_assets")) or 0.0
        lt_eq = _safe_float(b_now.get("lt_eqt_invest")) or 0.0
        oth_rec = _safe_float(b_now.get("oth_receiv")) or 0.0
        if ta > 0 and (oth_rec / ta) > 0.15:
            ratio = oth_rec / ta
            flags.append(RedFlagItem(
                id=make_flag_id("Governance", "high_other_receivables"),
                framework="Governance",
                level=LEVEL_HIGH,
                title="其他应收款畸高预警 (警惕大股东资金占用)",
                value=round(ratio, 3),
                threshold="其他应收款 / 总资产 > 15%",
                evidence=f"其他应收款={oth_rec/1e8:.2f} 亿，占总资产比例高达 {ratio*100:.1f}%",
                node="quality",
                metric_refs=["oth_receiv"],
            ))
        return flags

    # ─────────────────────────────────────────────────────────────
    # Framework 13: 存贷双高与利息/债务倒挂排雷
    # ─────────────────────────────────────────────────────────────
    def _check_high_cash_high_debt(
        self, bs: pd.DataFrame, inc: pd.DataFrame, industry: str | None = None,
    ) -> list[RedFlagItem]:
        flags: list[RedFlagItem] = []
        if is_financial(industry):
            return flags
        if bs is None or bs.empty:
            return flags

        b_now = bs.iloc[-1]
        ta = _safe_float(b_now.get("total_assets"))
        if not ta or ta <= 0:
            return flags

        money_cap = _safe_float(b_now.get("money_cap"), 0.0) or 0.0
        st_borr = _safe_float(b_now.get("st_borr"), 0.0) or 0.0
        lt_borr = _safe_float(b_now.get("lt_borr"), 0.0) or 0.0
        ncl_due_1y = _safe_float(b_now.get("non_cur_liab_due_1y"), 0.0) or 0.0
        ibd = st_borr + lt_borr + ncl_due_1y

        cash_ratio = money_cap / ta
        debt_ratio = ibd / ta

        fatal_cash_th = getattr(config, "FORENSIC_CASH_RATIO_FATAL", 0.25)
        fatal_debt_th = getattr(config, "FORENSIC_DEBT_RATIO_FATAL", 0.25)
        warn_cash_th = getattr(config, "FORENSIC_CASH_RATIO_WARN", 0.20)
        warn_debt_th = getattr(config, "FORENSIC_DEBT_RATIO_WARN", 0.20)

        fin_exp = 0.0
        op = 0.0
        if inc is not None and not inc.empty:
            y_now = inc.iloc[-1]
            fin_exp = _safe_float(y_now.get("fin_exp"), 0.0) or 0.0
            op = _safe_float(y_now.get("operate_profit"), 0.0) or 0.0

        erosion_th = getattr(config, "FORENSIC_FIN_EXP_EROSION_RATIO", 0.25)
        has_severe_erosion = (
            (fin_exp > 0 and op > 0 and (fin_exp / op) >= erosion_th)
            or (fin_exp > 0 and op <= 0)
            or (fin_exp >= 100_000_000 and (fin_exp / money_cap) >= 0.035 if money_cap > 0 else False)
        )

        if cash_ratio >= fatal_cash_th and debt_ratio >= fatal_debt_th and has_severe_erosion:
            flags.append(RedFlagItem(
                id=make_flag_id("Forensic", "fatal_high_cash_high_debt"),
                framework="Forensic Accounting",
                level=LEVEL_FATAL,
                title="存贷双高与财务费用严重侵蚀 (造假/受限资金极高危)",
                value=f"现金{cash_ratio*100:.1f}%, 负债{debt_ratio*100:.1f}%",
                threshold=f"货币资金>={fatal_cash_th*100:.0f}% 且 有息负债>={fatal_debt_th*100:.0f}% 且 财务费用重度侵蚀",
                evidence=(
                    f"账面货币资金高达 {money_cap/1e8:.2f} 亿 (占资产 {cash_ratio*100:.1f}%)，"
                    f"同时背负高达 {ibd/1e8:.2f} 亿有息负债 (占资产 {debt_ratio*100:.1f}%)，"
                    f"且当期财务费用高达 {fin_exp/1e8:.2f} 亿侵蚀营业利润。典型存贷双高虚假暴雷形态。"
                ),
                node="quality",
                metric_refs=["high_cash_high_debt", "money_cap"],
            ))
        elif cash_ratio >= warn_cash_th and debt_ratio >= warn_debt_th:
            flags.append(RedFlagItem(
                id=make_flag_id("Forensic", "warn_high_cash_high_debt"),
                framework="Forensic Accounting",
                level=LEVEL_HIGH,
                title="存贷双高结构性异常 (资金利用效率低下或存在受限资金)",
                value=f"现金{cash_ratio*100:.1f}%, 负债{debt_ratio*100:.1f}%",
                threshold=f"货币资金占比 >= {warn_cash_th*100:.0f}% 且 有息负债占比 >= {warn_debt_th*100:.0f}%",
                evidence=(
                    f"账面货币资金 {money_cap/1e8:.2f} 亿 (占资产 {cash_ratio*100:.1f}%) 与有息负债 {ibd/1e8:.2f} 亿并存。"
                ),
                node="quality",
                metric_refs=["high_cash_high_debt", "money_cap"],
            ))

        return flags

    # ─────────────────────────────────────────────────────────────
    # Framework 14: 在建工程长期不转固与异常膨胀排雷
    # ─────────────────────────────────────────────────────────────
    def _check_cip_anomaly(
        self, bs: pd.DataFrame, inc: pd.DataFrame, industry: str | None = None,
    ) -> list[RedFlagItem]:
        flags: list[RedFlagItem] = []
        if is_financial(industry):
            return flags
        if bs is None or bs.empty:
            return flags

        b_now = bs.iloc[-1]
        ta_now = _safe_float(b_now.get("total_assets"))
        if ta_now is None or ta_now <= 0:
            return flags

        cip_now = _safe_float(b_now.get("cip"), 0.0) or 0.0
        fix_now = _safe_float(b_now.get("fix_assets"), 0.0) or 0.0
        if cip_now <= 0:
            return flags

        cip_to_fix = (cip_now / fix_now) if fix_now > 0 else 999.0
        cip_to_ta = cip_now / ta_now

        cip_warn_th = getattr(config, "FORENSIC_CIP_TO_FIXED_WARN", 0.40)
        cip_fatal_th = getattr(config, "FORENSIC_CIP_TO_FIXED_FATAL", 0.60)
        cip_ta_min = getattr(config, "FORENSIC_CIP_TO_ASSETS_MIN", 0.15)

        has_stagnant_cip = False
        cip_prev = 0.0
        fix_prev = 0.0
        if len(bs) >= 2:
            b_prev = bs.iloc[-2]
            cip_prev = _safe_float(b_prev.get("cip"), 0.0) or 0.0
            fix_prev = _safe_float(b_prev.get("fix_assets"), 0.0) or 0.0
            if fix_prev > 0 and cip_prev > 0:
                cip_prev_to_fix = cip_prev / fix_prev
                fix_growth = (fix_now - fix_prev) / fix_prev
                if cip_to_fix >= 0.40 and cip_prev_to_fix >= 0.40 and fix_growth < 0.08:
                    has_stagnant_cip = True

        if cip_now >= 100_000_000 and (
            (has_stagnant_cip and cip_to_ta >= cip_ta_min)
            or (cip_to_fix >= cip_fatal_th and cip_to_ta >= cip_ta_min)
            or (cip_to_fix >= 1.0 and cip_now >= 200_000_000)
        ):
            ev = f"最新在建工程达 {cip_now/1e8:.2f} 亿元 (占固定资产 {cip_to_fix*100:.1f}%，占总资产 {cip_to_ta*100:.1f}%)"
            flags.append(RedFlagItem(
                id=make_flag_id("Forensic", "cip_stagnant_anomaly"),
                framework="Forensic Accounting",
                level=LEVEL_HIGH,
                title="在建工程长期不转固与异常膨胀 (疑似延迟折旧或虚构工程)",
                value=f"在建/固资={cip_to_fix*100:.1f}%, 占资产={cip_to_ta*100:.1f}%",
                threshold=f"在建工程/固定资产 >= {cip_fatal_th*100:.0f}% 且 占资产 >= {cip_ta_min*100:.0f}% 且转固滞后",
                evidence=ev,
                node="quality",
                metric_refs=["cip_anomaly", "cip"],
            ))
        elif cip_now >= 50_000_000 and (cip_to_fix >= cip_warn_th or cip_to_ta >= cip_ta_min):
            flags.append(RedFlagItem(
                id=make_flag_id("Forensic", "cip_scale_warning"),
                framework="Forensic Accounting",
                level=LEVEL_MEDIUM,
                title="在建工程规模庞大 (未来转固折旧承压)",
                value=f"在建/固资={cip_to_fix*100:.1f}%, 占资产={cip_to_ta*100:.1f}%",
                threshold=f"在建工程/固定资产 >= {cip_warn_th*100:.0f}% 或 占资产 >= {cip_ta_min*100:.0f}%",
                evidence=f"在建工程金额达 {cip_now/1e8:.2f} 亿元，占固定资产比例达 {cip_to_fix*100:.1f}% (占总资产 {cip_to_ta*100:.1f}%)",
                node="quality",
                metric_refs=["cip_anomaly", "cip"],
            ))

        return flags
