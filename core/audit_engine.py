"""11 classic accounting and forensic audit frameworks for AST-Trader."""
from __future__ import annotations

import math
from typing import Any

import pandas as pd

import config
from .red_flags import LEVEL_FATAL, LEVEL_HIGH, LEVEL_LOW, LEVEL_MEDIUM, RedFlagItem, make_flag_id


def _safe_float(v: Any, default: float | None = None) -> float | None:
    if v is None:
        return default
    try:
        val = float(v)
        return default if math.isnan(val) else val
    except (ValueError, TypeError):
        return default


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
        """运行全部 11 个审计框架，返回红旗清单。"""
        flags: list[RedFlagItem] = []

        # 1. Beneish M-Score (盈余操纵排查)
        flags.extend(self._check_beneish(balance_df, income_df, cashflow_df))

        # 2. Piotroski F-Score (财务健康打分)
        flags.extend(self._check_piotroski(balance_df, income_df, cashflow_df))

        # 3. Altman Z-Score (破产预警)
        flags.extend(self._check_altman(balance_df, income_df))

        # 4. Sloan Accrual Anomaly (高应计异象)
        flags.extend(self._check_sloan(balance_df, income_df, cashflow_df))

        # 5. Buffett Quality (现金流含金量)
        flags.extend(self._check_buffett_quality(balance_df, income_df, cashflow_df))

        # 6. 主营业务侵蚀 (投资收益占营业利润过高)
        flags.extend(self._check_invest_income_erosion(income_df))

        # 7. 治理风险 (高比例质押、大额减持)
        if governance_info:
            flags.extend(self._check_governance(governance_info))

        # 8. 长期股权投资与关联方敞口
        flags.extend(self._check_lt_equity_exposure(balance_df))

        # 9. 估值透支警报
        if quote_info:
            flags.extend(self._check_valuation(balance_df, income_df, quote_info))

        # 10. 商誉与资产减值黑天鹅排查
        flags.extend(self._check_goodwill_impairment(balance_df))

        # 11. 股东户数变动与筹码散户化
        if governance_info:
            flags.extend(self._check_shareholder_dispersion(governance_info))

        return flags

    # ─────────────────────────────────────────────────────────────
    # 1. Beneish M-Score (8 变量模型)
    # ─────────────────────────────────────────────────────────────
    def _check_beneish(self, bs: pd.DataFrame, inc: pd.DataFrame, cf: pd.DataFrame) -> list[RedFlagItem]:
        flags = []
        if len(inc) < 2 or len(bs) < 2:
            return flags

        curr_inc, prev_inc = inc.iloc[-1], inc.iloc[-2]
        curr_bs, prev_bs = bs.iloc[-1], bs.iloc[-2]

        rev_t = _safe_float(curr_inc.get("revenue"))
        rev_t1 = _safe_float(prev_inc.get("revenue"))
        rec_t = _safe_float(curr_bs.get("accounts_receiv"))
        rec_t1 = _safe_float(prev_bs.get("accounts_receiv"))
        cogs_t = _safe_float(curr_inc.get("oper_cost"))
        cogs_t1 = _safe_float(prev_inc.get("oper_cost"))
        ta_t = _safe_float(curr_bs.get("total_assets"))
        ta_t1 = _safe_float(prev_bs.get("total_assets"))

        if not all([rev_t, rev_t1, ta_t, ta_t1]) or rev_t <= 0 or rev_t1 <= 0 or ta_t <= 0 or ta_t1 <= 0:
            return flags

        # 1. DSRI (应收账款异动指数)
        dsri = ((rec_t or 0) / rev_t) / max(((rec_t1 or 0) / rev_t1), 1e-4)
        # 2. GMI (毛利率指数)
        gm_t = (rev_t - (cogs_t or 0)) / rev_t
        gm_t1 = (rev_t1 - (cogs_t1 or 0)) / rev_t1
        gmi = max(gm_t1, 1e-4) / max(gm_t, 1e-4)
        # 3. AQI (资产质量指数)
        nca_t = _safe_float(curr_bs.get("total_nca"), 0)
        nca_t1 = _safe_float(prev_bs.get("total_nca"), 0)
        aqi = (1 - ((curr_bs.get("total_cur_assets") or 0) + (curr_bs.get("fix_assets") or 0)) / ta_t) / max(
            (1 - ((prev_bs.get("total_cur_assets") or 0) + (prev_bs.get("fix_assets") or 0)) / ta_t1), 1e-4
        )
        # 4. SGI (营收增长指数)
        sgi = rev_t / rev_t1
        # 5. DEPI (折旧指数)
        depi = 1.0
        # 6. SGAI (销售管理费用指数)
        sgai = 1.0
        # 7. LVGI (杠杆指数)
        debt_t = (_safe_float(curr_bs.get("total_liab")) or 0) / ta_t
        debt_t1 = (_safe_float(prev_bs.get("total_liab")) or 0) / ta_t1
        lvgi = debt_t / max(debt_t1, 1e-4)
        # 8. TATA (总应计占总资产比)
        ni_t = _safe_float(curr_inc.get("n_income")) or 0
        cfo_t = (_safe_float(cf.iloc[-1].get("n_cashflow_act")) or 0) if len(cf) > 0 else 0
        tata = (ni_t - cfo_t) / ta_t

        # Beneish M-Score 公式
        m_score = (
            -4.84
            + 0.920 * dsri
            + 0.528 * gmi
            + 0.404 * aqi
            + 0.892 * sgi
            + 0.115 * depi
            - 0.172 * sgai
            + 4.037 * tata
            + 0.0327 * lvgi
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
            ))

        return flags

    # ─────────────────────────────────────────────────────────────
    # 2. Piotroski F-Score (9 项财务健康打分)
    # ─────────────────────────────────────────────────────────────
    def _check_piotroski(self, bs: pd.DataFrame, inc: pd.DataFrame, cf: pd.DataFrame) -> list[RedFlagItem]:
        flags = []
        if len(inc) < 2 or len(bs) < 2:
            return flags

        curr_inc, prev_inc = inc.iloc[-1], inc.iloc[-2]
        curr_bs, prev_bs = bs.iloc[-1], bs.iloc[-2]
        curr_cf = cf.iloc[-1] if len(cf) > 0 else {}

        ta = _safe_float(curr_bs.get("total_assets")) or 1.0
        ni = _safe_float(curr_inc.get("n_income")) or 0.0
        cfo = _safe_float(curr_cf.get("n_cashflow_act")) or 0.0
        roa_curr = ni / ta
        roa_prev = (_safe_float(prev_inc.get("n_income")) or 0.0) / (_safe_float(prev_bs.get("total_assets")) or 1.0)

        f_score = 0
        if roa_curr > 0: f_score += 1
        if cfo > 0: f_score += 1
        if roa_curr > roa_prev: f_score += 1
        if cfo > ni: f_score += 1

        # 杠杆
        lev_curr = (_safe_float(curr_bs.get("lt_borr")) or 0) / ta
        lev_prev = (_safe_float(prev_bs.get("lt_borr")) or 0) / (_safe_float(prev_bs.get("total_assets")) or 1.0)
        if lev_curr <= lev_prev: f_score += 1

        # 流动比率
        cr_curr = (_safe_float(curr_bs.get("total_cur_assets")) or 0) / max(_safe_float(curr_bs.get("total_cur_liab")) or 1.0, 1e-4)
        cr_prev = (_safe_float(prev_bs.get("total_cur_assets")) or 0) / max(_safe_float(prev_bs.get("total_cur_liab")) or 1.0, 1e-4)
        if cr_curr > cr_prev: f_score += 1

        # 股份稀释
        if (_safe_float(curr_bs.get("total_share")) or 0) <= (_safe_float(prev_bs.get("total_share")) or 0): f_score += 1

        # 毛利与周转
        rev_curr = _safe_float(curr_inc.get("revenue")) or 1.0
        rev_prev = _safe_float(prev_inc.get("revenue")) or 1.0
        gm_curr = (rev_curr - (_safe_float(curr_inc.get("oper_cost")) or 0)) / rev_curr
        gm_prev = (rev_prev - (_safe_float(prev_inc.get("oper_cost")) or 0)) / rev_prev
        if gm_curr > gm_prev: f_score += 1
        if (rev_curr / ta) > (rev_prev / (_safe_float(prev_bs.get("total_assets")) or 1.0)): f_score += 1

        if f_score <= 3:
            flags.append(RedFlagItem(
                id=make_flag_id("Piotroski", "f_score_poor"),
                framework="Piotroski F-Score",
                level=LEVEL_HIGH,
                title="基本面健康度严重恶化 (Piotroski F-Score 极低)",
                value=f_score,
                threshold="<= 3",
                evidence=f"F-Score={f_score}/9 分 (ROA={roa_curr*100:.1f}%, 现金流={cfo/1e8:.2f}亿)",
                node="quality",
            ))

        return flags

    # ─────────────────────────────────────────────────────────────
    # 3. Altman Z-Score (破产预警)
    # ─────────────────────────────────────────────────────────────
    def _check_altman(self, bs: pd.DataFrame, inc: pd.DataFrame) -> list[RedFlagItem]:
        flags = []
        if bs.empty or inc.empty:
            return flags

        b = bs.iloc[-1]
        i = inc.iloc[-1]
        ta = _safe_float(b.get("total_assets"))
        tl = _safe_float(b.get("total_liab"))
        if not ta or ta <= 0:
            return flags

        ca = _safe_float(b.get("total_cur_assets"), 0)
        cl = _safe_float(b.get("total_cur_liab"), 0)
        working_cap = ca - cl
        re_earned = _safe_float(b.get("undistr_profit"), 0)
        ebit = _safe_float(i.get("operate_profit"), 0)
        eq = _safe_float(b.get("total_equity"), 0)
        sales = _safe_float(i.get("revenue"), 0)

        # 针对新兴市场与非制造业通用的 Altman Z''-Score
        # Z = 6.56*X1 + 3.26*X2 + 6.72*X3 + 1.05*X4
        x1 = working_cap / ta
        x2 = re_earned / ta
        x3 = ebit / ta
        x4 = eq / max(tl or 1.0, 1.0)
        z = 6.56 * x1 + 3.26 * x2 + 6.72 * x3 + 1.05 * x4

        if z < 1.1:
            flags.append(RedFlagItem(
                id=make_flag_id("Altman", "z_score_distress"),
                framework="Altman Z-Score",
                level=LEVEL_FATAL,
                title="破产高危区域 (Altman Z-Score 极低)",
                value=round(z, 2),
                threshold="< 1.1",
                evidence=f"Z-Score={z:.2f} 处于重度财务危机困境区 (营运资金占比={x1*100:.1f}%, 权益负债比={x4:.2f})",
                node="path",
            ))
        elif z < 2.6:
            flags.append(RedFlagItem(
                id=make_flag_id("Altman", "z_score_grey"),
                framework="Altman Z-Score",
                level=LEVEL_MEDIUM,
                title="财务状况脆弱 (Altman Z-Score 处于灰色预警区)",
                value=round(z, 2),
                threshold="< 2.6",
                evidence=f"Z-Score={z:.2f} (流动资产对负债覆盖偏紧)",
                node="path",
            ))

        return flags

    # ─────────────────────────────────────────────────────────────
    # 4. Sloan Accrual Anomaly (应计利润异象)
    # ─────────────────────────────────────────────────────────────
    def _check_sloan(self, bs: pd.DataFrame, inc: pd.DataFrame, cf: pd.DataFrame) -> list[RedFlagItem]:
        flags = []
        if bs.empty or inc.empty or cf.empty:
            return flags

        ta = _safe_float(bs.iloc[-1].get("total_assets"))
        ni = _safe_float(inc.iloc[-1].get("n_income"))
        cfo = _safe_float(cf.iloc[-1].get("n_cashflow_act"))

        if not ta or ta <= 0 or ni is None or cfo is None:
            return flags

        accrual_ratio = (ni - cfo) / ta
        if accrual_ratio > config.SLOAN_ACCRUAL_FATAL_RATIO:
            flags.append(RedFlagItem(
                id=make_flag_id("Sloan", "high_accrual"),
                framework="Sloan Accrual",
                level=LEVEL_HIGH,
                title="高应计异象 (纸面富贵，经营现金流严重落后利润)",
                value=round(accrual_ratio, 3),
                threshold=f"> {config.SLOAN_ACCRUAL_FATAL_RATIO}",
                evidence=f"应计利润率={accrual_ratio*100:.1f}% (净利润={ni/1e8:.2f}亿 vs 现金流={cfo/1e8:.2f}亿)",
                node="quality",
            ))

        return flags

    # ─────────────────────────────────────────────────────────────
    # 5. Buffett Quality (现金流真实性)
    # ─────────────────────────────────────────────────────────────
    def _check_buffett_quality(self, bs: pd.DataFrame, inc: pd.DataFrame, cf: pd.DataFrame) -> list[RedFlagItem]:
        flags = []
        if inc.empty or cf.empty:
            return flags

        ni = _safe_float(inc.iloc[-1].get("n_income")) or 0.0
        cfo = _safe_float(cf.iloc[-1].get("n_cashflow_act")) or 0.0

        if ni > 0 and cfo < 0:
            flags.append(RedFlagItem(
                id=make_flag_id("Buffett", "cfo_negative_while_profitable"),
                framework="Buffett Quality",
                level=LEVEL_HIGH,
                title="利润含金量严重虚脱 (盈利但经营现金流为负)",
                value=round(cfo / 1e8, 2),
                threshold="< 0",
                evidence=f"净利润={ni/1e8:.2f} 亿，但经营现金流净额为 {cfo/1e8:.2f} 亿",
                node="quality",
            ))
        elif ni > 0 and (cfo / ni) < 0.5:
            flags.append(RedFlagItem(
                id=make_flag_id("Buffett", "cfo_ni_ratio_low"),
                framework="Buffett Quality",
                level=LEVEL_MEDIUM,
                title="经营现金流对净利润覆盖不足",
                value=round(cfo / ni, 2),
                threshold="< 0.5",
                evidence=f"CFO/NI 比率={cfo/ni*100:.1f}% (远低于及格线 100%)",
                node="quality",
            ))

        return flags

    # ─────────────────────────────────────────────────────────────
    # 6. 主营业务侵蚀 (投资收益占营业利润过高)
    # ─────────────────────────────────────────────────────────────
    def _check_invest_income_erosion(self, inc: pd.DataFrame) -> list[RedFlagItem]:
        flags = []
        if inc.empty:
            return flags

        i = inc.iloc[-1]
        op = _safe_float(i.get("operate_profit"))
        inv = _safe_float(i.get("invest_income"))

        if op and op > 0 and inv and (inv / op) > 0.50:
            flags.append(RedFlagItem(
                id=make_flag_id("Erosion", "invest_income_too_high"),
                framework="Profit Erosion",
                level=LEVEL_HIGH,
                title="主营业务成色不足 (过半营业利润依赖外部投资收益)",
                value=round(inv / op, 2),
                threshold="> 50%",
                evidence=f"投资收益={inv/1e8:.2f} 亿，占营业利润比例高达 {inv/op*100:.1f}%",
                node="quality",
            ))

        return flags

    # ─────────────────────────────────────────────────────────────
    # 7. 治理风险 (高比例质押、大额减持)
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
                threshold=f"> {config.PLEDGE_FATAL_RATIO*100:.0f}%",
                evidence=f"控股股东/实控人累计质押比例高达 {pledge*100:.1f}%，极易遭遇被动平仓与连环跌停",
                node="path",
            ))
        elif pledge > 0.40:
            flags.append(RedFlagItem(
                id=make_flag_id("Governance", "high_pledge_ratio"),
                framework="Governance",
                level=LEVEL_MEDIUM,
                title="控股股东质押比例偏高",
                value=round(pledge, 3),
                threshold="> 40%",
                evidence=f"质押比例 {pledge*100:.1f}%",
                node="path",
            ))

        if gov.get("has_reduction_plan"):
            flags.append(RedFlagItem(
                id=make_flag_id("Governance", "shareholder_reduction"),
                framework="Governance",
                level=LEVEL_HIGH,
                title="大股东/高管近期有集中减持计划",
                value="在途减持",
                threshold="存在在途减持",
                evidence="公告显示存在大股东竞价减持计划，高位抛压沉重",
                node="path",
            ))

        return flags

    # ─────────────────────────────────────────────────────────────
    # 8. 长期股权投资与关联方敞口
    # ─────────────────────────────────────────────────────────────
    def _check_lt_equity_exposure(self, bs: pd.DataFrame) -> list[RedFlagItem]:
        flags = []
        if bs.empty:
            return flags

        b = bs.iloc[-1]
        ta = _safe_float(b.get("total_assets"))
        lt = _safe_float(b.get("lt_eqt_invest"), 0.0)

        if ta and ta > 0 and (lt / ta) > 0.25:
            flags.append(RedFlagItem(
                id=make_flag_id("RelatedParty", "lt_equity_too_large"),
                framework="Related-Party Exposure",
                level=LEVEL_MEDIUM,
                title="长期股权投资占比过大 (外部联营合营资产黑洞风险)",
                value=round(lt / ta, 3),
                threshold="> 25%",
                evidence=f"长期股权投资={lt/1e8:.2f} 亿，占总资产比例为 {lt/ta*100:.1f}%",
                node="quality",
            ))

        return flags

    # ─────────────────────────────────────────────────────────────
    # 9. 估值透支警报
    # ─────────────────────────────────────────────────────────────
    def _check_valuation(self, bs: pd.DataFrame, inc: pd.DataFrame, q: dict[str, Any]) -> list[RedFlagItem]:
        flags = []
        if bs.empty or inc.empty:
            return flags

        eq = _safe_float(bs.iloc[-1].get("equity_attr_p"))
        ni = _safe_float(inc.iloc[-1].get("n_income_attr_p"))
        price = _safe_float(q.get("close"))

        if not eq or eq <= 0 or not price or price <= 0:
            return flags

        total_share = _safe_float(bs.iloc[-1].get("total_share"))
        if not total_share or total_share <= 0:
            return flags

        mv = price * total_share
        pb = mv / eq
        roe = (ni / eq) if ni else 0.0

        if pb > 8.0 and roe < 0.05:
            flags.append(RedFlagItem(
                id=make_flag_id("Valuation", "extreme_pb_low_roe"),
                framework="Valuation",
                level=LEVEL_HIGH,
                title="高估值低盈利双杀风险 (PB > 8 但 ROE < 5%)",
                value=round(pb, 1),
                threshold="PB > 8 & ROE < 5%",
                evidence=f"市净率 PB={pb:.1f} 倍，而年化 ROE 仅 {roe*100:.1f}%，纯情绪题材炒作",
                node="odds",
            ))

        return flags

    # ─────────────────────────────────────────────────────────────
    # 10. 商誉与资产减值黑天鹅排查
    # ─────────────────────────────────────────────────────────────
    def _check_goodwill_impairment(self, bs: pd.DataFrame) -> list[RedFlagItem]:
        flags = []
        if bs.empty:
            return flags

        b = bs.iloc[-1]
        eq = _safe_float(b.get("total_equity"))
        goodwill = _safe_float(b.get("goodwill"), 0.0)

        if eq and eq > 0 and goodwill and (goodwill / eq) > 0.30:
            gw_ratio = goodwill / eq
            flags.append(RedFlagItem(
                id=make_flag_id("Goodwill", "high_goodwill_ratio"),
                framework="Asset Impairment",
                level=LEVEL_FATAL if gw_ratio > 0.50 else LEVEL_HIGH,
                title="巨额商誉悬顶 (存在年报商誉大额减值暴雷风险)",
                value=round(gw_ratio, 3),
                threshold="> 30%",
                evidence=f"账面商誉={goodwill/1e8:.2f} 亿，占净资产比例高达 {gw_ratio*100:.1f}%",
                node="quality",
            ))

        return flags

    # ─────────────────────────────────────────────────────────────
    # 11. 股东户数变动与筹码散户化 (主力出逃排查)
    # ─────────────────────────────────────────────────────────────
    def _check_shareholder_dispersion(self, gov: dict[str, Any]) -> list[RedFlagItem]:
        flags = []
        holder_change_pct = _safe_float(gov.get("holder_change_pct"))
        if holder_change_pct is not None and holder_change_pct > 20.0:
            flags.append(RedFlagItem(
                id=make_flag_id("Chip", "shareholder_surge"),
                framework="Shareholder Dispersion",
                level=LEVEL_HIGH,
                title="筹码急剧发散 (散户接盘，主力高位出逃)",
                value=round(holder_change_pct, 1),
                threshold="> 20%",
                evidence=f"最新一期股东户数环比激增 {holder_change_pct:.1f}%，筹码集中度迅速恶化",
                node="path",
            ))

        return flags
