"""eltdx collector for AST-Trader: quotes, k-lines, money flow, and financial statements.
Strictly captures all interface exceptions and tracks data pipeline health.
"""
from __future__ import annotations

from datetime import datetime
import logging
import math
from typing import Any

import pandas as pd

from .eltdx_client import normalize_code, open_client, with_retry, EltdxFetchError
from . import eltdx_financial_map as fmap
from . import eltdx_financial as ef
from .supplement_api import fetch_realtime_supplement, fetch_holder_flow
from .data_health import DataHealthTracker

logger = logging.getLogger("ast_trader.data.collector")

BALANCE_MAP = {
    "T007": "money_cap",             # 货币资金
    "T010": "accounts_receiv",       # 应收账款
    "T011": "prepayment",            # 预付款项
    "T012": "oth_receiv",            # 其他应收款
    "T016": "inventories",           # 存货
    "T019": "oth_cur_assets",        # 其他流动资产
    "T020": "total_cur_assets",      # 流动资产合计
    "T024": "lt_eqt_invest",         # 长期股权投资
    "T026": "fix_assets",            # 固定资产
    "T027": "cip",                   # 在建工程
    "T032": "intan_assets",          # 无形资产
    "T034": "goodwill",              # 商誉
    "T038": "total_nca",             # 非流动资产合计
    "T039": "total_assets",          # 资产总计
    "T040": "st_borr",               # 短期借款
    "T043": "acct_payable",          # 应付账款
    "T045": "payroll_payable",       # 应付职工薪酬
    "T046": "taxes_payable",         # 应交税费
    "T051": "non_cur_liab_due_1y",   # 一年内到期的非流动负债
    "T053": "total_cur_liab",        # 流动负债合计
    "T054": "lt_borr",               # 长期借款
    "T061": "total_ncl",             # 非流动负债合计
    "T062": "total_liab",            # 负债合计
    "T063": "total_share",           # 总股本
    "T067": "undistr_profit",        # 未分配利润
    "T071": "total_equity",          # 所有者权益合计
    "T077": "equity_attr_p",         # 归母所有者权益合计
}

CASHFLOW_MAP = {
    "T008": "c_fr_sale_sg",          # 销售商品收到的现金
    "T012": "c_paid_goods_s",        # 购买商品支付的现金
    "T017": "n_cashflow_act",        # 经营活动现金流量净额
    "T024": "c_pay_acq_const_fiolta",# 购建固定资产支付现金 (CAPEX)
    "T029": "n_cashflow_inv_act",    # 投资活动现金流量净额
    "T038": "n_cash_flows_fnc_act",  # 筹资活动现金流量净额
    "T046": "net_profit",            # 净利润
    "T048": "depr_fa_coga_dpba",     # 固定资产折旧
    "T049": "amort_intang_assets",   # 无形资产摊销
}

INCOME_CODE_MAP = {
    "T001": "revenue",               # 营业收入
    "T002": "oper_cost",             # 营业成本
    "T003": "biz_tax_surchg",        # 税金及附加
    "T004": "sell_exp",              # 销售费用
    "T005": "admin_exp",             # 管理费用
    "T007": "fin_exp",               # 财务费用
    "T010": "invest_income",         # 投资收益
    "T013": "operate_profit",        # 营业利润
    "T016": "total_profit",          # 利润总额
}


class EltdxCollector:
    """采集器封装：行情、K线、分笔、财务快照与板块概念。全程记录接口健康度与异常状态。"""

    def __init__(self, health_tracker: DataHealthTracker | None = None) -> None:
        self.health = health_tracker or DataHealthTracker()

    def get_daily(self, code_str: str, count: int = 60) -> pd.DataFrame:
        """获取日 K 线（倒序，最新交易日排在第一行）。"""
        eltdx_code, ts_code = normalize_code(code_str)

        def _fetch():
            with open_client() as c:
                return c.bars.get(eltdx_code, period="day", adjust=None, count=count)

        try:
            resp = with_retry(_fetch, what=f"日K线({eltdx_code})")
            bars = list(getattr(resp, "bars", ()) or ())
            if not bars:
                self.health.record_empty("日K线序列", f"eltdx.bars.get({eltdx_code})", "未返回K线记录")
                return pd.DataFrame()

            rows = []
            prev_close = None
            for b in bars:
                close = float(b.close)
                pre = (b.last_close_price_milli / 1000.0) if getattr(b, "last_close_price_milli", None) is not None else prev_close
                chg = (close - pre) if pre is not None else None
                pct = ((close - pre) / pre * 100.0) if pre else None
                rows.append({
                    "ts_code": ts_code,
                    "trade_date": b.time.strftime("%Y%m%d"),
                    "open": float(b.open),
                    "high": float(b.high),
                    "low": float(b.low),
                    "close": close,
                    "pre_close": pre,
                    "change": chg,
                    "pct_chg": pct,
                    "vol": float(b.volume_lots),
                    "amount": float(b.amount) if b.amount else 0.0,
                })
                prev_close = close

            df = pd.DataFrame(rows)
            df = df.sort_values("trade_date", ascending=False).reset_index(drop=True)
            self.health.record_success("日K线序列", f"eltdx.bars.get({eltdx_code})", len(df))
            return df
        except Exception as e:
            self.health.record_failure("日K线序列", f"eltdx.bars.get({eltdx_code})", e, fatal=True)
            logger.error(f"日K线获取异常: {e}")
            raise EltdxFetchError(f"日K线获取失败: {e}") from e

    def get_realtime_quote(self, code_str: str) -> dict[str, Any]:
        """获取单股实时快照及股本市值基本面数据。"""
        eltdx_code, ts_code = normalize_code(code_str)

        def _fetch():
            with open_client() as c:
                sn_list = c.quotes.get_snapshots([eltdx_code])
                fb = None
                try:
                    fb = c.corporate.finance_batch([eltdx_code])
                    if fb and hasattr(fb, "records") and fb.records:
                        self.health.record_success("专业财务快照批次", "c.corporate.finance_batch", len(fb.records))
                    else:
                        self.health.record_empty("专业财务快照批次", "c.corporate.finance_batch", "无财务快照批次记录")
                except Exception as e_fb:
                    self.health.record_failure("专业财务快照批次", "c.corporate.finance_batch", e_fb)
                    logger.warning(f"finance_batch 获取失败: {e_fb}")
                return sn_list, fb

        try:
            resp = with_retry(_fetch, what=f"实时快照({eltdx_code})")
            if not resp or not resp[0]:
                self.health.record_empty("实时行情快照", f"eltdx.quotes.get_snapshots({eltdx_code})", "未返回快照记录")
                raise EltdxFetchError(f"无法获取 {code_str} 的实时快照")
            sn_list, fb = resp
            self.health.record_success("实时行情快照", f"eltdx.quotes.get_snapshots({eltdx_code})", len(sn_list))
        except Exception as e:
            self.health.record_failure("实时行情快照", f"eltdx.quotes.get_snapshots({eltdx_code})", e, fatal=True)
            logger.error(f"获取实时快照异常: {e}")
            raise EltdxFetchError(f"获取实时快照失败: {e}") from e

        sn = sn_list[0]
        close = float(sn.last_price)
        pre = float(sn.pre_close_price)
        pct_chg = round((close - pre) / pre * 100.0, 2) if pre else 0.0

        # 从真实财务批次中提取总股本、流通股本与 EPS / BPS (单位：万股 / 元)
        total_share = 0.0
        float_share = 0.0
        bps = 0.0
        eps = 0.0
        if fb and hasattr(fb, "records") and fb.records:
            frec = fb.records[0]
            total_share = float(getattr(frec, "zong_gu_ben_raw_float", 0.0) or 0.0) * 10000.0
            float_share = float(getattr(frec, "liu_tong_gu_ben_raw_float", 0.0) or 0.0) * 10000.0
            bps = float(getattr(frec, "mei_gu_jing_zi_chan_raw_float", 0.0) or 0.0)
            eps = float(getattr(frec, "eps_raw", 0.0) or 0.0)

        total_mv = close * total_share if total_share > 0 else 0.0
        circ_mv = close * float_share if float_share > 0 else 0.0
        vol_shares = float(sn.total_hand) * 100.0
        turnover_ratio = round((vol_shares / float_share) * 100.0, 2) if float_share > 0 else 0.0
        pe = round(close / eps, 2) if eps > 0 else 0.0
        pb = round(close / bps, 2) if bps > 0 else 0.0

        # 从高速行情补充接口拉取真实名称与真实 TTM PE
        num_code = ts_code.split(".")[0]
        supp = fetch_realtime_supplement(num_code, health=self.health)
        name = supp.get("name", "")
        pe_ttm = supp.get("pe_ttm")
        if pe_ttm and pe_ttm > 0:
            pe = round(pe_ttm, 2)
        if supp.get("pb") and supp["pb"] > 0:
            pb = round(supp["pb"], 2)

        return {
            "ts_code": ts_code,
            "eltdx_code": eltdx_code,
            "name": name,
            "close": close,
            "pre_close": pre,
            "open": float(sn.open_price),
            "high": float(sn.high_price),
            "low": float(sn.low_price),
            "pct_chg": pct_chg,
            "vol": float(sn.total_hand),
            "amount": float(sn.amount) if sn.amount else 0.0,
            "total_share": total_share,
            "float_share": float_share,
            "total_mv": total_mv,
            "circ_mv": circ_mv,
            "turnover_ratio": turnover_ratio,
            "bps": bps,
            "eps": eps,
            "pe": pe,
            "pb": pb,
        }

    def get_money_flow(self, code_str: str) -> dict[str, Any]:
        """获取资金流向大单、超大单净额（单位：万元）。"""
        eltdx_code, ts_code = normalize_code(code_str)

        def _fetch():
            with open_client() as c:
                return c.money_flow.daily(eltdx_code)

        try:
            resp = with_retry(_fetch, what=f"资金流({eltdx_code})")
            records = getattr(resp, "records", None)
            if not records:
                self.health.record_empty("资金流向明细", f"eltdx.money_flow.daily({eltdx_code})", "资金流记录为空")
                return {"main_net_wan": 0.0, "main_ratio": 0.0, "super_large_net_wan": 0.0, "large_net_wan": 0.0}
            latest = records[0]
            self.health.record_success("资金流向明细", f"eltdx.money_flow.daily({eltdx_code})", len(records))
            return {
                "ts_code": ts_code,
                "main_net_wan": round(latest.main_net / 10000.0, 2),
                "main_ratio": round(latest.main_ratio, 2),
                "super_large_net_wan": round(latest.main_super_large_net / 10000.0, 2),
                "large_net_wan": round(latest.main_large_net / 10000.0, 2),
                "medium_net_wan": round(latest.main_medium_net / 10000.0, 2),
                "small_net_wan": round(latest.main_small_net / 10000.0, 2),
            }
        except Exception as e:
            self.health.record_failure("资金流向明细", f"eltdx.money_flow.daily({eltdx_code})", e)
            logger.warning(f"获取资金流异常: {e}")
            return {"main_net_wan": 0.0, "main_ratio": 0.0, "super_large_net_wan": 0.0, "large_net_wan": 0.0}

    def get_microstructure(
        self,
        code_str: str,
        current_price: float = 0.0,
        daily_df: pd.DataFrame | None = None,
        momentum: dict[str, Any] | None = None,
        ladder_info: dict[str, Any] | None = None,
        float_share: float = 0.0,
        quote: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """获取高频微观结构、知情交易与主力生命周期分析 (开源金工聪明钱 Q、时段切割与换手沉淀)."""
        eltdx_code, ts_code = normalize_code(code_str)

        def _fetch():
            with open_client() as c:
                bars_resp = c.bars.get(eltdx_code, period="5min", count=480)
                ad_resp = None
                try:
                    ad_resp = c.helpers.auction_data(eltdx_code)
                    if ad_resp:
                        self.health.record_success("早盘集合竞价切片", "eltdx.helpers.auction_data", 1)
                    else:
                        self.health.record_empty("早盘集合竞价切片", "eltdx.helpers.auction_data", "无竞价切片数据")
                except Exception as e_ad:
                    self.health.record_failure("早盘集合竞价切片", "eltdx.helpers.auction_data", e_ad)
                    logger.warning(f"auction_data 获取失败: {e_ad}")
                return getattr(bars_resp, "bars", []) or [], ad_resp

        try:
            bars, ad = with_retry(_fetch, what=f"高频微观结构({eltdx_code})")
            if bars:
                self.health.record_success("5分钟高频分时K线", "eltdx.bars.get(5min)", len(bars))
            else:
                self.health.record_empty("5分钟高频分时K线", "eltdx.bars.get(5min)", "无5分钟K线记录")

            from core.microstructure import MicrostructureAnalyzer
            analyzer = MicrostructureAnalyzer()
            prof = analyzer.analyze(
                bars,
                auction_data=ad,
                current_price=current_price,
                daily_df=daily_df,
                momentum=momentum,
                ladder_info=ladder_info,
                float_share=float_share,
                quote=quote,
                ticker=ts_code,
            )
            return {
                "smart_q": prof.smart_q,
                "smart_vwap": prof.smart_vwap,
                "all_vwap": prof.all_vwap,
                "smart_buy_ratio": prof.smart_buy_ratio,
                "smart_sell_ratio": prof.smart_sell_ratio,
                "smart_phase": prof.smart_phase,
                "apm_pattern": prof.apm_pattern,
                "am_return_pct": prof.am_return_pct,
                "pm_return_pct": prof.pm_return_pct,
                "tail_vol_ratio": prof.tail_vol_ratio,
                "auction_open_amt_wan": prof.auction_open_amt_wan,
                "auction_open_chg_pct": prof.auction_open_chg_pct,
                "verdict_text": prof.verdict_text,
                "main_force_stage": prof.main_force_stage,
                "main_force_behavior": prof.main_force_behavior,
                "main_force_risk": prof.main_force_risk,
                "cum_turnover_20d": prof.cum_turnover_20d,
                "price_position_60d": prof.price_position_60d,
                "main_force_confidence": prof.main_force_confidence,
                "is_transitional": prof.is_transitional,
                "suggested_pos_cap": prof.suggested_pos_cap,
                "recommended_action": prof.recommended_action,
                "decision_gear_override": prof.decision_gear_override,
                "stage_code": prof.stage_code,
                "anti_spoofing_summary": prof.anti_spoofing_summary,
                "scores": prof.scores,
            }
        except Exception as e:
            self.health.record_failure("5分钟高频分时K线", "eltdx.bars.get(5min)", e)
            self.health.record_degraded("5分钟高频分时K线", "eltdx.bars.get(5min)", f"接口异常降级: {e}")
            logger.warning(f"获取微观结构异常: {e}")
            return {
                "smart_q": None,
                "smart_vwap": None,
                "all_vwap": None,
                "smart_buy_ratio": None,
                "smart_sell_ratio": None,
                "smart_phase": "UNVERIFIED",
                "apm_pattern": "UNKNOWN",
                "am_return_pct": 0.0,
                "pm_return_pct": 0.0,
                "tail_vol_ratio": 0.0,
                "auction_open_amt_wan": 0.0,
                "auction_open_chg_pct": 0.0,
                "verdict_text": f"微观分时数据获取降级 ({e})",
                "main_force_stage": "【⏳ 数据缺失/微观未核验】",
                "main_force_behavior": "分时数据暂缺(未核验)，微观特征无法确认",
                "main_force_risk": "分时高频数据缺失，无法探测日内算法对倒与出货特征",
                "cum_turnover_20d": None,
                "price_position_60d": None,
                "main_force_confidence": 0.0,
                "is_transitional": False,
                "suggested_pos_cap": 0.0,
                "recommended_action": "等待微观数据完整",
                "decision_gear_override": "观察",
                "stage_code": "STAGE_UNVERIFIED",
                "anti_spoofing_summary": ["微观盘口数据缺失，防伪审计未核验"],
                "scores": {},
                "is_degraded": True,
            }

    def get_financial_reports(self, code_str: str) -> dict[str, pd.DataFrame]:
        """获取三张报表的历史截面（用于 11 经典审计与赚不赚钱看板）。"""
        _, ts_code = normalize_code(code_str)
        num_code = ts_code.split(".")[0]

        def _fetch_f10(rtype):
            with open_client() as c:
                return c.f10.finance_report(num_code, rtype)

        out = {"balance": pd.DataFrame(), "cashflow": pd.DataFrame(), "income": pd.DataFrame()}

        # 1. 资产负债表
        try:
            resp_bs = with_retry(lambda: _fetch_f10("zcfzb"), what="f10.finance_report(zcfzb)")
            rs0 = resp_bs.result_sets[0] if resp_bs and resp_bs.result_sets else None
            if rs0 and rs0.rows:
                rows = []
                for r in rs0.rows:
                    p = fmap.period_of(r)
                    if not p:
                        continue
                    rec = fmap.to_balance_record(r)
                    rec["end_date"] = p
                    rows.append(rec)
                out["balance"] = pd.DataFrame(rows).sort_values("end_date").reset_index(drop=True)
                self.health.record_success("资产负债表 (zcfzb)", "eltdx.f10.finance_report", len(rows))
            else:
                self.health.record_empty("资产负债表 (zcfzb)", "eltdx.f10.finance_report", "F10资产负债表数据集为空")
        except Exception as e:
            self.health.record_failure("资产负债表 (zcfzb)", "eltdx.f10.finance_report", e)
            logger.warning(f"获取资产负债表失败: {e}")

        # 2. 现金流量表
        try:
            resp_cf = with_retry(lambda: _fetch_f10("xjllb"), what="f10.finance_report(xjllb)")
            rs0 = resp_cf.result_sets[0] if resp_cf and resp_cf.result_sets else None
            if rs0 and rs0.rows:
                rows = []
                for r in rs0.rows:
                    p = fmap.period_of(r)
                    if not p:
                        continue
                    rec = fmap.to_cashflow_record(r)
                    rec["end_date"] = p
                    rows.append(rec)
                out["cashflow"] = pd.DataFrame(rows).sort_values("end_date").reset_index(drop=True)
                self.health.record_success("现金流量表 (xjllb)", "eltdx.f10.finance_report", len(rows))
            else:
                self.health.record_empty("现金流量表 (xjllb)", "eltdx.f10.finance_report", "F10现金流量表数据集为空")
        except Exception as e:
            self.health.record_failure("现金流量表 (xjllb)", "eltdx.f10.finance_report", e)
            logger.warning(f"获取现金流量表失败: {e}")

        # 3. 利润表 (优先读取专业财务 zip 缓存)
        try:
            periods = ef.available_periods()[:8]
            rows = []
            for p in periods:
                vec = ef.fields_of(num_code, p)
                if vec is not None:
                    rec = fmap.to_income_record(vec)
                    if rec:
                        rec["end_date"] = p
                        rows.append(rec)
            if rows:
                out["income"] = pd.DataFrame(rows).sort_values("end_date").reset_index(drop=True)
                self.health.record_success("利润表 (income)", "eltdx_financial.zip", len(rows))
            else:
                self.health.record_empty("利润表 (income)", "eltdx_financial.zip", "专业财务包中无当前标的利润表数据")
        except Exception as e:
            self.health.record_failure("利润表 (income)", "eltdx_financial.zip", e)
            logger.warning(f"专业财务 zip 提取异常: {e}")

        return out

    def get_f10_governance_and_concept(self, code_str: str) -> dict[str, Any]:
        """获取治理信息（质押率、减持）与概念板块。"""
        _, ts_code = normalize_code(code_str)
        num_code = ts_code.split(".")[0]

        res = {
            "pledge_ratio": 0.0,
            "has_reduction_plan": False,
            "concepts": [],
            "main_business": [],
        }

        with open_client() as c:
            # 1. 概念题材
            try:
                ht = c.f10.hot_topics(num_code)
                if ht and ht.result_sets and ht.result_sets[0].rows:
                    concepts = [r.get("T002") for r in ht.result_sets[0].rows if r.get("T002")]
                    res["concepts"] = list(dict.fromkeys(concepts))[:8]
                    self.health.record_success("概念题材分类", "eltdx.f10.hot_topics", len(res["concepts"]))
                else:
                    self.health.record_empty("概念题材分类", "eltdx.f10.hot_topics", "无关联热点概念")
            except Exception as e_ht:
                self.health.record_failure("概念题材分类", "eltdx.f10.hot_topics", e_ht)
                logger.warning(f"获取概念题材异常: {e_ht}")

            # 2. 减持计划 (严格核验在途计划，排除历史已届满/已实施完毕的旧记录)
            try:
                scp = c.f10.shareholder_change_plans(num_code)
                if scp and scp.result_sets and scp.result_sets[0].rows:
                    today_str = datetime.now().strftime("%Y-%m-%d")
                    active_plans = []
                    for r in scp.result_sets[0].rows:
                        direction = str(r.get("N002", ""))
                        status = str(r.get("N011", ""))
                        end_date = str(r.get("N010", "") or "")
                        is_reduction = ("减" in direction)
                        is_completed = ("完" in status)
                        is_active_date = (end_date >= today_str) if end_date else False
                        if is_reduction and not is_completed and is_active_date:
                            active_plans.append(r)
                    res["has_reduction_plan"] = len(active_plans) > 0
                    self.health.record_success("股东减持计划", "eltdx.f10.shareholder_change_plans", len(active_plans))
                else:
                    self.health.record_empty("股东减持计划", "eltdx.f10.shareholder_change_plans", "无减持计划记录")
            except Exception as e_scp:
                self.health.record_failure("股东减持计划", "eltdx.f10.shareholder_change_plans", e_scp)
                logger.warning(f"获取减持计划异常: {e_scp}")

            # 3. 主营构成
            try:
                bc = c.f10.business_composition(num_code)
                if bc and bc.result_sets and bc.result_sets[0].rows:
                    for r in bc.result_sets[0].rows[:5]:
                        name = r.get("N002")
                        ratio = r.get("N004")
                        if name and ratio:
                            res["main_business"].append({"name": str(name), "ratio": float(ratio)})
                    self.health.record_success("主营业务构成", "eltdx.f10.business_composition", len(res["main_business"]))
                else:
                    self.health.record_empty("主营业务构成", "eltdx.f10.business_composition", "未披露主营构成占比明细")
            except Exception as e_bc:
                self.health.record_failure("主营业务构成", "eltdx.f10.business_composition", e_bc)
                logger.warning(f"获取主营构成异常: {e_bc}")

        # 4. 股东户数环比变动 (筹码沉淀追踪)
        hf = fetch_holder_flow(num_code, health=self.health)
        if hf:
            res["holder_count"] = hf.get("holder_count")
            res["holder_change_pct"] = hf.get("holder_change_pct")
            res["holder_date"] = hf.get("end_date")

        return res

    def get_market_breadth(self) -> dict[str, Any]:
        """获取全市场广度统计（涨跌家数比、全市场总成交额、涨跌停数）。"""
        def _fetch():
            with open_client() as c:
                quotes = c.quotes.legacy(["sh880005", "sh880001", "sh880006"])
                if not quotes:
                    return {}
                q = quotes[0]
                up = round(q.last_price)
                down = round(q.open_price)
                neutral = round(q.low_price)
                total = round(q.high_price)
                if total > 15000:
                    up = round(up / 10)
                    down = round(down / 10)
                    neutral = round(neutral / 10)
                    total = round(total / 10)
                limit_down = round(quotes[2].open_price) if len(quotes) > 2 else 0
                limit_up = round(quotes[2].last_price) if len(quotes) > 2 else 0
                if limit_up > 500:
                    limit_up = round(limit_up / 10)
                if limit_down > 500:
                    limit_down = round(limit_down / 10)
                return {
                    "up_count": up,
                    "down_count": down,
                    "neutral_count": neutral,
                    "total_count": total,
                    "total_amount": float(q.amount) if q.amount else 0.0,
                    "limit_up_count": limit_up,
                    "limit_down_count": limit_down,
                }

        try:
            resp = with_retry(_fetch, what="quotes.legacy_market_stat")
            if resp:
                self.health.record_success("全市场广度统计", "eltdx.quotes.legacy", 1)
            else:
                self.health.record_empty("全市场广度统计", "eltdx.quotes.legacy", "未返回大盘广度数据")
            return resp or {}
        except Exception as e:
            self.health.record_failure("全市场广度统计", "eltdx.quotes.legacy", e)
            logger.warning(f"获取大盘广度异常: {e}")
            return {}
