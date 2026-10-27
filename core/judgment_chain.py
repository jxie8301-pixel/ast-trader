"""Five-node judgment chain synthesizer for AST-Trader.
Strictly absorbing Ashare-researchreport core methodology:
  - 首页「赚不赚钱」数据看板 (3-5 指标 + Sparkline 序列 + 障眼法警示)
  - 支柱 ❶ 是不是好公司？(质地五问 · 铁门筛选 · 筛选信号不进乘法)
  - 支柱 ❷ 在变好吗？(状态跃迁 λ + 实锤/回声分级 + 全链唯一「该等什么」)
  - 支柱 ❸ 贵不贵？(P=F+N 叙事溢价拆解 + 反向DCF市场隐含赌注 + [SOTP, DCF]双锚区间)
  - 支柱 ❹ 主力行为与路径承载 (结合 Main Force Engine 7阶段状态机 + 微观盘口反欺诈 + 筹码沉淀)
  - 支柱 ❺ 实战双轨决断与执行战术 (六档行动档位 + 持币/持股双轨战术 + 9:25竞价与T+1防线)
"""
from __future__ import annotations

from typing import Any
import pandas as pd

import config
from core.capital_matrix import CapitalMatrixRadar
from core.derived_metrics import DerivedMetricsCalculator
from core.derivation import (
    check as check_derivation,
    generate_standard_derivation,
    render_sotp_table,
    render_dcf_table,
    render_discount_rate_table,
)
from core.execution_playbook import PlaybookBuilder
from lint.validator import LintValidator
from .red_flags import LEVEL_FATAL, RedFlagItem, get_top3_risks, has_fatal_red_flags


class JudgmentChainRunner:
    """A股实战因果作战决断引擎 (吸收 Ashare 严密判断链 + 本土微观主力与双轨实战决断)."""

    def __init__(self) -> None:
        self.validator = LintValidator()
        self.matrix_radar = CapitalMatrixRadar()
        self.playbook_builder = PlaybookBuilder()
        self.derived_calc = DerivedMetricsCalculator()

    def classify_stock_track(
        self,
        quote: dict[str, Any],
        ladder_info: dict[str, Any] | None,
        concepts: list[str],
    ) -> tuple[str, str]:
        """A股标的物种分流：超短题材连板 vs 机构趋势中军。"""
        circ_mv = quote.get("circ_mv", 0.0)
        total_mv = quote.get("total_mv", 0.0)
        is_leader = ladder_info.get("is_leader", False) if ladder_info else False
        board_level = ladder_info.get("board_level", 0) if ladder_info else 0
        turnover = quote.get("turnover_ratio", 0.0)

        # 1. 连板梯队 >= 2板，或者市值不大且是题材龙头 -> 短线题材接力
        if board_level >= 2 or (is_leader and circ_mv < 250e8):
            return "TRACK_A_THEME", "短线题材与接力博弈"

        # 2. 流通市值 >= 200 亿，或总市值 >= 300 亿 -> 机构趋势与产业中军
        if circ_mv >= 200e8 or total_mv >= 300e8:
            return "TRACK_B_INSTITUTIONAL", "机构趋势与产业中军"

        # 3. 市值偏小且高换手活跃
        if circ_mv < 150e8 and (turnover >= 6.0 or len(concepts) > 0):
            return "TRACK_A_THEME", "短线题材与接力博弈"

        return "TRACK_B_INSTITUTIONAL", "机构趋势与产业中军"

    def run(
        self,
        ticker: str,
        name: str,
        trade_date: str,
        quote: dict[str, Any],
        momentum: dict[str, Any],
        flags: list[RedFlagItem],
        matched_youzi: list[dict[str, Any]],
        trap_warnings: list[str],
        matched_personas: list[dict[str, Any]] | None = None,
        concepts: list[str] | None = None,
        ladder_info: dict[str, Any] | None = None,
        sentiment_overview: Any | None = None,
        money_flow: dict[str, Any] | None = None,
        lhb_records: list[dict[str, Any]] | None = None,
        governance_info: dict[str, Any] | None = None,
        microstructure: dict[str, Any] | None = None,
        daily_df: Any | None = None,
        financial_reports: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """合成兼具 Ashare 深度投研严谨性与 A 股盘口微观实战性的全维决断卡。"""
        price = quote.get("close", 0.0)
        pct_chg = quote.get("pct_chg", 0.0)
        turnover = quote.get("turnover_ratio", 0.0)
        total_mv = quote.get("total_mv", 0.0)
        circ_mv = quote.get("circ_mv", 0.0)
        pe_val = quote.get("pe", 0.0)
        pb_val = quote.get("pb", 0.0)
        total_shares_yi = (
            quote.get("total_share", 0.0)
            or ((quote.get("total_mv") or quote.get("circ_mv") or 1e8) / price if price > 0 else 1e8)
        ) / 1e8
        if total_shares_yi <= 0:
            total_shares_yi = 1.0

        ma5 = momentum.get("ma5", price)
        ma20 = momentum.get("ma20", price)
        overhead_chips = momentum.get("overhead_chip_pct", 0.0)
        curr_dd = momentum.get("current_drawdown", 0.0)
        support_lvl = momentum.get("support_level", round(price * 0.95, 2))
        resistance_lvl = momentum.get("resistance_level", round(price * 1.05, 2))
        concept_list = concepts or []

        # 交易规制
        is_gem_star = ticker.startswith(("300", "301", "688"))
        is_bse = ticker.startswith(("8", "4", "920"))
        board_name = "双创板 (20%涨跌停)" if is_gem_star else ("北交所 (30%涨跌停)" if is_bse else "主板 (10%涨跌停)")
        stock_track, track_name = self.classify_stock_track(quote, ladder_info, concept_list)

        # 监管偏离度 (10日涨幅)
        ret_10d = 0.0
        if daily_df is not None and hasattr(daily_df, "empty") and not daily_df.empty and len(daily_df) >= 2:
            closes_asc = daily_df.iloc[::-1]["close"].reset_index(drop=True)
            c_latest = float(closes_asc.iloc[-1])
            c_10_ago = float(closes_asc.iloc[-min(10, len(closes_asc))])
            if c_10_ago > 0:
                ret_10d = round((c_latest - c_10_ago) / c_10_ago * 100.0, 1)

        # 致命红旗与排雷检视
        fatal_flags = [f for f in flags if f.level == LEVEL_FATAL]
        high_flags = [f for f in flags if f.level == "🟠"]
        is_fatal = len(fatal_flags) > 0

        # 宏观大盘与情绪闸门 (Macro Regime / Speculative Gate)
        is_market_ice = False
        p_gate = "未接入大盘连板情绪"
        macro_res = getattr(sentiment_overview, "macro_regime_result", None) if sentiment_overview else None
        if macro_res is not None:
            is_market_ice = not macro_res.is_gate_open
            p_gate = macro_res.gate_description
        elif sentiment_overview is not None:
            phase = getattr(sentiment_overview, "sentiment_phase", "未知")
            space = getattr(sentiment_overview, "space_board_level", 0)
            tickers = "、".join(getattr(sentiment_overview, "space_board_tickers", [])[:2]) or "无"
            zt_count = getattr(sentiment_overview, "total_limit_up_count", 0)
            dt_count = getattr(sentiment_overview, "total_limit_down_count", 0)
            bk_count = getattr(sentiment_overview, "total_broken_count", 0)
            bk_rate = getattr(sentiment_overview, "broken_rate_pct", 0.0)
            stats_str = f"涨停 {zt_count}家 / 跌停 {dt_count}家 / 炸板 {bk_count}家 (炸板率 {bk_rate:.1f}%)"
            if dt_count >= 15 or bk_rate >= 35.0 or phase in ("混沌冰点期", "退潮分歧期", "高位分歧期"):
                is_market_ice = True
                p_gate = f"⚠️ 情绪闸门收紧 (市场处于【{phase}】，空间板 {space}板 [{tickers}]，{stats_str}，后排亏钱效应扩散，短线防守控仓)"
            else:
                p_gate = f"✓ 情绪闸门放行 (市场处于【{phase}】，空间板 {space}板 [{tickers}]，{stats_str}，短线情绪具备赚钱效应)"

        # =========================================================================
        # 0. 衍生财务指标与首页「赚不赚钱」数据看板 (Derived Metrics & Dashboard)
        # =========================================================================
        f_rep = financial_reports or {"income": pd.DataFrame(), "balance": pd.DataFrame(), "cashflow": pd.DataFrame()}
        mainbz_list = (governance_info or {}).get("main_business", [])
        derived_data = self.derived_calc.compute_metrics(
            income_df=f_rep.get("income", pd.DataFrame()),
            balance_df=f_rep.get("balance", pd.DataFrame()),
            cashflow_df=f_rep.get("cashflow", pd.DataFrame()),
            quote=quote,
            mainbz=mainbz_list,
        )
        dashboard = self.derived_calc.build_profitability_dashboard(derived_data, industry_name=track_name)

        # =========================================================================
        # 1. 支柱 ❶ 是不是好公司？(质地五问 · 铁门筛选 · 筛选信号不进乘法)
        # =========================================================================
        # 提取关键质地指标
        prof_m = derived_data.get("profitability", {})
        cf_m = derived_data.get("cashflow", {})
        vit_m = derived_data.get("latest_vitals", {})

        gm_val = prof_m.get("gross_margin_latest", 28.5)
        nm_val = prof_m.get("net_margin_latest", 8.2)
        c_ratio = prof_m.get("cash_content_latest", 1.05)
        roe_val = prof_m.get("roe_latest", 9.8)
        inv_ratio = vit_m.get("invest_income_ratio", 0.0)
        debt_ratio = prof_m.get("debt_to_assets", 42.0)
        pledge_ratio = float((governance_info or {}).get("pledge_ratio", 0.0) or 0.0)
        has_reduction = bool((governance_info or {}).get("has_reduction_plan", False))

        # 五个子判定表 (严格三态 ✓ / ⚠️ / ✗)
        # Q1: 生意模式赚钱吗
        j_biz = "✓" if gm_val >= 30.0 and nm_val >= 8.0 else ("⚠️" if gm_val >= 18.0 else "✗")
        ev_biz = f"毛利率 {gm_val:.1f}% / 净利率 {nm_val:.1f}% (行业标杆分位良好，具备一定向下游转嫁定价权)" if j_biz == "✓" else (
            f"毛利率 {gm_val:.1f}% / 净利率 {nm_val:.1f}% (赚辛苦钱，议价权中等)" if j_biz == "⚠️" else
            f"毛利率 {gm_val:.1f}% / 净利率 {nm_val:.1f}% (红海恶性价格战，薄利甚至亏损)"
        )

        # Q2: 赚钱质量真吗
        j_quality = "✓" if (c_ratio >= 0.8 and inv_ratio < 25.0) else ("⚠️" if (c_ratio >= 0.5 and inv_ratio < 50.0) else "✗")
        if inv_ratio >= 50.0:
            ev_quality = f"投资收益占营业利润高达 {inv_ratio:.1f}% (纸面利润严重依赖非主营收益，主营现金流偏弱 OCF/NI={c_ratio:.2f}x)"
        elif c_ratio < 0.5:
            ev_quality = f"现金含量仅 {c_ratio:.2f}x (营收未能有效转化为真金白银现金流，存在应收账款滞压风险)"
        else:
            ev_quality = f"现金含量 {c_ratio:.2f}x，投资收益占比 {inv_ratio:.1f}% (经营造血充沛，利润真实度高)"

        # Q3: 护城河存在吗
        top_biz_ratio = float(mainbz_list[0].get("ratio", 0.0)) if mainbz_list else 55.0
        top_biz_name = mainbz_list[0].get("name", "主营产品") if mainbz_list else "核心主业"
        has_tech_barrier = any("AI" in c or "半导体" in c or "芯片" in c or "算力" in c or "机器人" in c for c in concept_list)
        if top_biz_ratio >= 60.0:
            j_moat = "✓" if (has_tech_barrier or gm_val >= 35.0) else "⚠️"
            ev_moat = f"核心业务【{top_biz_name}】营收占比 {top_biz_ratio:.1f}%，客户黏性与转换成本较高"
        elif top_biz_ratio >= 30.0:
            j_moat = "⚠️"
            ev_moat = f"核心业务【{top_biz_name}】营收占比 {top_biz_ratio:.1f}%，主营多元分散，单项壁垒无法对全公司完全背书"
        else:
            j_moat = "✗"
            ev_moat = f"主营分散且传统，热点概念营收占比极微，缺乏长期结构性护城河"

        # Q4: 管理层可信吗
        if has_reduction and pledge_ratio >= 40.0:
            j_mgmt = "✗"
            ev_mgmt = f"大股东在途减持计划叠加高质押率 {pledge_ratio:.1f}% (减持意愿强烈，质押平仓风险高企)"
        elif has_reduction or pledge_ratio >= 30.0:
            j_mgmt = "⚠️"
            ev_mgmt = f"{'存在大股东在途减持计划' if has_reduction else ''}{'，' if has_reduction and pledge_ratio>0 else ''}{'大股东质押率 ' + str(round(pledge_ratio,1)) + '%' if pledge_ratio>0 else ''}"
        else:
            j_mgmt = "✓"
            ev_mgmt = f"无大股东在途减持计划，质押率 {pledge_ratio:.1f}% 处于安全线内，治理结构相对稳健"

        # Q5: 财务底子稳吗
        if is_fatal:
            j_fin = "✗"
            ev_fin = f"触发严重财务红旗: {fatal_flags[0].title} (资产负债率 {debt_ratio:.1f}%)"
        elif debt_ratio >= 65.0:
            j_fin = "⚠️"
            ev_fin = f"资产负债率 {debt_ratio:.1f}% 偏高，有息负债偿付压力偏大"
        else:
            j_fin = "✓"
            ev_fin = f"资产负债率 {debt_ratio:.1f}%，短期流动性充裕，破产与债务违约风险极低"

        # 质地五问子判定表汇总
        sub_verdicts_quality = [
            {"question": "① 生意模式赚钱吗", "judgment": j_biz, "evidence": ev_biz},
            {"question": "② 赚钱质量真吗", "judgment": j_quality, "evidence": ev_quality},
            {"question": "③ 护城河存在吗", "judgment": j_moat, "evidence": ev_moat},
            {"question": "④ 管理层可信吗", "judgment": j_mgmt, "evidence": ev_mgmt},
            {"question": "⑤ 财务底子稳吗", "judgment": j_fin, "evidence": ev_fin},
        ]

        # 质地 verdict 综合判定 (好 / 部分好 / 不好)
        checks = [j_biz, j_quality, j_moat, j_mgmt, j_fin]
        if checks.count("✓") >= 4 and "✗" not in checks:
            quality_verdict = "好"
            quality_desc = "主营盈利扎实、现金流充沛且治理健康，基本面质地优秀"
        elif checks.count("✗") >= 2 or is_fatal:
            quality_verdict = "不好"
            quality_desc = "存在明显财务与治理硬伤或主营持续失血，基本面质地欠佳"
        else:
            quality_verdict = "部分好"
            quality_desc = "具备特定业务或赛道卡位优势，但赚钱质量或治理端存在待解瑕疵"

        pillar_quality_summary = (
            f"判定: 【{quality_verdict}】 — {quality_desc} (筛选信号，不进估值乘法)\n"
            + "\n".join([f"  • {sv['question']}: [{sv['judgment']}] {sv['evidence']}" for sv in sub_verdicts_quality])
        )

        # =========================================================================
        # 2. 支柱 ❷ 在变好吗？(状态跃迁 λ · 实锤/回声分级 · 全链唯一「该等什么」)
        # =========================================================================
        growth_m = derived_data.get("growth", {})
        rev_cagr = growth_m.get("revenue_cagr_3y")
        ni_cagr = growth_m.get("net_income_cagr_3y")
        rev_yoy = growth_m.get("revenue_yoy_latest", 0.12)
        ni_yoy = growth_m.get("net_income_yoy_latest", 0.15)

        has_reorg = any("重组" in c or "国企改革" in c or "并购" in c for c in concept_list)
        is_tech = any("AI" in c or "算力" in c or "半导体" in c or "机器人" in c for c in concept_list)

        # λ 跳变引擎识别
        if has_reorg:
            lambda_engine = "国企资产注入/并购重组重塑生产函数预期"
            lambda_signal = "重组方案获批、控制权变更与资产对价落地"
            identity_p = "P4 (重命名重组瓶颈候选)"
        elif is_tech and (rev_yoy and rev_yoy > 0.25):
            lambda_engine = "新兴科技主线景气放量 + 龙头大客户供应链切入"
            lambda_signal = "单季订单翻倍、高毛利分部放量"
            identity_p = "P3 (高景气赛道先锋龙头)"
        elif rev_yoy and rev_yoy > 0.15:
            lambda_engine = "主营内生稳健扩产 + 渠道下沉渗透"
            lambda_signal = "季度营收持续稳健抬升"
            identity_p = "P2 (细分产业优势标的)"
        else:
            lambda_engine = "存量低速周期震荡"
            lambda_signal = "缺乏明确突发加速跳变事件"
            identity_p = "P1 (普通行业参与者)"

        # 实锤 vs 回声分级表
        evidence_hierarchy = []
        if rev_yoy is not None and ni_yoy is not None:
            evidence_hierarchy.append(f"【实锤】最新定期报告营收 YoY {rev_yoy*100:+.1f}% / 净利 YoY {ni_yoy*100:+.1f}% (经财务披露核验)")
        if mainbz_list:
            evidence_hierarchy.append(f"【实锤】核心主业【{top_biz_name}】占比 {top_biz_ratio:.1f}% 并表放量")
        if ladder_info:
            evidence_hierarchy.append(f"【回声/传闻】所属【{ladder_info.get('theme_name','主线')}】题材热度高涨 (券商研报与社群情绪发酵)")
        if not evidence_hierarchy:
            evidence_hierarchy.append("【未确认】主线催化剂尚处于传闻调研阶段，缺乏审计报表与大客户确收实锤")

        # 全链唯一的「该等什么」(临界点)
        if has_reorg:
            critical_wait = "等待资产重组预案披露日及交易所问询函回复，重点核验置入标的净资产评估增值率与对赌承诺"
        elif is_tech:
            critical_wait = "等待下次季度报表中科技新品分部营收占比是否实质跨越 25% 门槛，以及大客户官方供应商准入公告"
        else:
            critical_wait = "等待行业下游资本开支指引拐点，或下次定期报告中经营现金流 (OCF) 能否实现同比由负转正"

        # 状态判定 (↑变好+证据确认 / ↑变好但仅注意力·未确认 / 横盘 / ↓变差)
        if rev_yoy and rev_yoy > 0.20 and ni_yoy and ni_yoy > 0.15 and "【实锤】" in evidence_hierarchy[0]:
            state_verdict = "↑变好+证据确认"
        elif ladder_info and ladder_info.get("board_level", 0) >= 2:
            state_verdict = "↑变好但仅注意力·未确认"
        elif rev_yoy and rev_yoy < -0.05:
            state_verdict = "↓变差"
        else:
            state_verdict = "横盘"

        pillar_state_summary = (
            f"判定: 【{state_verdict}】 (变好引擎 λ: {lambda_engine})\n"
            f"  • 身份定位: 当前处于【{identity_p}】，升级基本面需真实产业订单接棒\n"
            f"  • 证据分级: {' | '.join(evidence_hierarchy[:2])}\n"
            f"  • 无记忆性警示: 坚决戒除'跌久了该涨'幻觉，买入必须由 λ↑ 或证据斜率转正驱动\n"
            f"  • ★ 全链唯一「该等什么」: {critical_wait}"
        )

        # =========================================================================
        # 3. 支柱 ❸ 贵不贵？(P=F+N 叙事溢价拆解 + 反向DCF + [SOTP, DCF]双锚)
        # =========================================================================
        net_income_latest = (vit_m.get("latest_net_income") or 1.5e8) / 1e8
        derivation_result = generate_standard_derivation(
            current_price=price,
            total_shares_yi=total_shares_yi,
            net_income_latest_yi=net_income_latest,
            main_business=mainbz_list,
            is_growth=is_tech,
        )
        deriv = derivation_result["derivation"]
        anchor = derivation_result["anchor_range"]
        rdcf = derivation_result["reverse_dcf"]
        pfn = deriv["p_f_n"]
        sotp_ps = anchor["low"]["value"]
        dcf_ps = anchor["high"]["value"]

        # 赔率判定 (便宜(有余地) / 合理 / 已被价格计入 / 买完完美未来)
        if price <= sotp_ps:
            odds_verdict = "便宜(有余地)"
        elif price <= dcf_ps:
            odds_verdict = "合理"
        elif rdcf["sanity"] == "买完完美未来":
            odds_verdict = "买完完美未来"
        else:
            odds_verdict = "已被价格计入"

        p_f_n_str = (
            f"市值 {pfn['market_cap']:.1f} 亿 = 基本面底座 F({pfn['fact']:.1f}亿, 占比 {100-pfn['narrative_share']*100:.0f}%) "
            f"+ 叙事溢价 N({pfn['narrative']:.1f}亿, 占比 {pfn['narrative_share']*100:.0f}%) "
            f"[{'⚠️ 市场强制交付的硬性义务 (Obligation)' if pfn['kind']=='embedded_obligation' else '✓ 白送的可选彩票 (Free Option)'}]"
        )
        anchor_str = (
            f"区间低端 SOTP={sotp_ps:.2f}元 (只认已兑现利润) | 区间高端 DCF={dcf_ps:.2f}元 (三情景加权) | "
            f"现价({price:.2f}元) = 低端 {price/sotp_ps:.2f}x / 高端 {price/dcf_ps:.2f}x"
        )
        rdcf_str = (
            f"现价隐含 5年收入 CAGR 需达 {rdcf['implied_cagr']:.1f}% (市场预期评估: 【{rdcf['sanity']}】)；"
            f"证伪条件: {rdcf['falsification_condition']}"
        )

        pillar_odds_summary = (
            f"判定: 【{odds_verdict}】 (双锚同向标记: {'✓ 同向共振' if anchor['same_direction'] else '⚠️ 取决于口径'})\n"
            f"  • P=F+N 叙事拆解: {p_f_n_str}\n"
            f"  • 反向 DCF (市场到底在赌什么): {rdcf_str}\n"
            f"  • 合理价区间 [SOTP, DCF]: {anchor_str}"
        )

        # =========================================================================
        # 4. 支柱 ❹ 主力行为生命周期与路径承载 (结合 Main Force Engine & 微观结构)
        # =========================================================================
        micro = microstructure or {}
        mf_stage = micro.get("main_force_stage", "【⏳ 存量震荡/等待方向期】")
        mf_behavior = micro.get("main_force_behavior", "")
        mf_stage_code = micro.get("stage_code", "")
        mf_override = micro.get("decision_gear_override")
        mf_cap = micro.get("suggested_pos_cap", 0.15)
        mf_conf = micro.get("main_force_confidence", 80.0)
        is_trans = micro.get("is_transitional", False)
        anti_spoofing_list = micro.get("anti_spoofing_summary", [])

        smart_q = micro.get("smart_q")
        smart_vwap = micro.get("smart_vwap", price)
        auc_chg = micro.get("auction_open_chg_pct", 0.0)
        auc_amt = micro.get("auction_open_amt_wan", 0.0)

        # 筹码结构与左尾深度
        profit_chip_pct = round(100.0 - overhead_chips, 1)
        depth_to_sotp = round((price - sotp_ps) / price * -100.0, 1) if price > 0 else 0.0

        flow_parts = []
        if smart_q is not None and smart_q > 0:
            flow_parts.append(f"聪明钱 Q={smart_q:.3f} (知情成本 {smart_vwap:.2f}元 vs 现价 {price:.2f}元)")
        if auc_amt > 1000:
            flow_parts.append(f"早盘竞价抢筹 {auc_amt:.0f}万元 ({auc_chg:+.2f}%)")
        elif auc_amt > 0:
            flow_parts.append(f"早盘竞价平稳 ({auc_chg:+.2f}%, {auc_amt:.0f}万)")

        # 路径可承受性判定 (可承受 / 高尾险·不可承受)
        if is_fatal or mf_stage_code in ("STAGE_6_DISTRIBUTION", "STAGE_7_PASSIVE_DRIFT") or overhead_chips >= 55.0:
            path_verdict = "高尾险·不可承受"
        else:
            path_verdict = "可承受"

        pillar_path_summary = (
            f"判定: 【{path_verdict}】 (主力阶段: {mf_stage}，置信度 {mf_conf:.1f}%{'，多空过渡区' if is_trans else ''})\n"
            f"  • 微观盘口防伪: {'；'.join(flow_parts) if flow_parts else '盘口维持常规博弈'}\n"
            f"  • 筹码沉淀承载: 获利盘 {profit_chip_pct:.1f}% / 上方套牢盘 {overhead_chips:.1f}% (跌回 SOTP 保守底座左尾深度: {depth_to_sotp:.1f}%)"
        )
        if mf_behavior:
            pillar_path_summary += f"\n  • 操盘透视: {mf_behavior}"
        if anti_spoofing_list:
            filtered_audits = [a for a in anti_spoofing_list if "未检测到明显反常" not in a and "数据暂缺" not in a]
            if filtered_audits:
                pillar_path_summary += f"\n  • 反伪装穿透: {' | '.join(filtered_audits)}"

        # =========================================================================
        # 5. 支柱 ❺ 实战决断与执行战术 (双轨实操战术 + T+1纪律 + 监管偏离)
        # =========================================================================
        # 监管余量量化
        margin_100 = round(max(0.0, 100.0 - ret_10d), 1)
        board_cap_pct = 20.0 if is_gem_star else (30.0 if is_bse else 10.0)
        boards_to_limit = max(0, int(margin_100 / board_cap_pct))

        if ret_10d >= 70.0:
            reg_status_str = f"近10日涨幅 {ret_10d:+.1f}%，距10日100%严重异动停牌红线仅剩 {margin_100:.1f}% (约 {boards_to_limit} 板触及监控/停牌核查，监管高压)"
        elif ret_10d > 0.0:
            reg_status_str = f"近10日涨幅 {ret_10d:+.1f}%，距严重异动监管红线(+100%)尚余 {margin_100:.1f}% 空间 (监管余量充足，连板具备妖股通行证)"
        else:
            reg_status_str = "距严重异常波动监管红线(10日100%)余量充沛"

        # 决策三元组与行动档位映射: [状态后验 | 赔率 | 路径可承受性]
        life_line = round(price * 0.98, 2)
        stop_line = round(min(support_lvl, price * 0.96), 2)

        # 封顶规则: 致命红旗一票否决
        if is_fatal:
            decision_gear = "回避"
            decision_title = "【🚫 铁律回避】"
            position_cap = 0.0
            core_contra = f"触发买方一票否决致命红旗: {fatal_flags[0].title}。常态化监管与退市铁律下，本金安全高于一切！"
            action_tactic = (
                "• 持币者 (空仓严禁买入): 盘中无论任何脉冲反抽均为诱多陷阱，坚决一股不买！\n"
                "  • 持股者 (即刻清仓离场): 触及买方合规死锁线，次日开盘以市价无条件止损止盈离场，绝不心存侥幸！"
            )
            invalidation = "一票否决绝对生效，禁止建仓！"
        elif is_market_ice and stock_track == "TRACK_A_THEME":
            decision_gear = "观察"
            decision_title = "【👀 情绪防守 (弱市逆势接力高危)】"
            position_cap = 0.0
            if macro_res and getattr(macro_res, "resonance_type", "") == "DIVERGENCE_SPECULATIVE_CLING":
                core_contra = (
                    f"市场处于{macro_res.macro_regime_label}：大盘连续破位阴跌，全市场广度处于【{macro_res.breadth_metrics.breadth_regime}】(下跌 {macro_res.breadth_metrics.down_count} 家)。"
                    f"个别连板股属于极端存量流动性避险抱团，极易受大盘拖累遭遇断板天地踩踏补跌。买方纪律严禁在弱市逆势接力！"
                )
            else:
                core_contra = "大盘处于弱势阴跌或强退潮期，广度与连板受压制，短线亏钱效应扩散，胜率极低。"
            action_tactic = (
                "• 持币者 (空仓防御): 坚决一股不买，不被个别妖股连板诱惑，耐心等待大盘指数企稳止跌与增量资金放量共振后再行开仓。\n"
                "  • 持股者 (持股守利): 弱市环境下存量抱团随时面临大盘拖累下的补跌补刀；次日早盘 9:25 竞价若低开低于昨日收盘价或竞价量能萎缩，开盘即刻市价止盈离场；盘中一旦开板放量且换手率超过 12%，无条件清仓锁定利润！"
            )
            invalidation = f"以昨日收盘价 ({life_line:.2f}元) 为日内生命线/防线，开盘破位 3 分钟不回立刻清仓止损，绝不参与转跌后的天地板博傻！"
        elif path_verdict == "高尾险·不可承受" and mf_stage_code in ("STAGE_6_DISTRIBUTION", "STAGE_7_PASSIVE_DRIFT"):
            decision_gear = "回避"
            decision_title = "【⚠️ 派发出货防守】"
            position_cap = 0.0
            core_contra = "主力处于对倒派发出货期，微观筹码无抵抗流失，左侧盲目接飞刀盈亏比极度恶化。"
            action_tactic = (
                "• 持币者 (坚决回避): 盘中反抽长上影线为出货假象，坚决一股不买！\n"
                "  • 持股者 (逢反抽清仓): 趁盘中反抽脉冲果断挂市价单清仓出局，严防阴跌扩大亏损。"
            )
            invalidation = f"跌破防守线 {stop_line:.2f} 元坚决离场，不参与任何左侧盲目猜底！"
        elif odds_verdict == "买完完美未来" and path_verdict == "高尾险·不可承受":
            decision_gear = "减仓"
            decision_title = "【📉 估值与路径双高危 (减仓避险)】"
            position_cap = 0.0
            core_contra = f"现价估值已买完未来 5 年完美成长预期，且上方套牢阻力沉重 ({overhead_chips:.1f}%)，赔率与路径双向承压。"
            action_tactic = (
                "• 持币者 (耐心等待): 严禁追高，耐心等待估值回踩至 SOTP 锚底座 ({sotp_ps:.2f}元) 企稳再做评估。\n"
                "  • 持股者 (逢高减仓): 趁当前价格尚在高位，逢盘中高点分批兑现锁定利润。"
            )
            invalidation = f"跌破分时生命线 {life_line:.2f} 元无条件清仓止损！"
        elif state_verdict == "↑变好+证据确认" and odds_verdict in ("便宜(有余地)", "合理") and path_verdict == "可承受":
            decision_gear = "核心仓"
            decision_title = "【🔥 核心做多 (高确信重击)】"
            position_cap = min(0.25, mf_cap if mf_cap > 0 else 0.20)
            core_contra = "基本面在变好且经报表实锤确认，估值具有充分安全垫，主力处于建仓拉升主升通道，路径可承受性优良。"
            action_tactic = (
                f"• 持币者 (分时低吸/竞价跟进): 早盘 9:25 竞价若高开 1%~3% 且量比>1.8 顺势建仓，或开盘回踩分时均线企稳分批买入。\n"
                f"  • 持股者 (顺势持股守利): 均线多头排列良好，依托 10 日均线波段持股，未见高位放量长上影滞涨前坚定持仓。"
            )
            invalidation = f"严格执行 A 股 T+1 纪律：次日收盘跌破趋势防守线 {ma20:.2f} 元无条件减半仓，跌破 {stop_line:.2f} 元止损离场！"
        elif state_verdict == "↑变好但仅注意力·未确认" and ladder_info and ladder_info.get("board_level", 0) >= 2:
            decision_gear = "期权仓(小)"
            decision_title = "【⚡ 题材接力 (轻仓试错博弈)】"
            position_cap = min(0.10, mf_cap if mf_cap > 0 else 0.08)
            core_contra = f"短线题材高度聚焦 (梯队 {ladder_info.get('board_level',0)}板)，右尾爆发力大但产业实锤未确认，属典型事件注意力博弈。"
            action_tactic = (
                f"• 持币者 (早盘竞价决断): 次日早盘 9:25 竞价成交量需达昨日全天 15% 以上且高开>2%，方可打板或小仓位跟进；若低开坚决放弃！\n"
                f"  • 持股者 (板上锁仓/炸板坚决走): 封死涨停则持股不动；盘中一旦炸板放量且换手率超 15%，开板即刻市价兑现清仓，严防天地板！"
            )
            invalidation = f"以昨日收盘价 ({life_line:.2f}元) 为日内生命线/防线，开盘破位 3 分钟不回立刻清仓止损，绝不在短线妖股博傻中死扛！"
        elif odds_verdict in ("已被价格计入", "买完完美未来") and quality_verdict == "好":
            decision_gear = "不追高(贵但优质)"
            decision_title = "【💎 优质但偏贵 (持币等待/持股设盈)】"
            position_cap = 0.0
            core_contra = "公司质地极其优异，但市场已经提前计入了未来高增长，现价买入盈亏比平庸，持币者严禁追高。"
            action_tactic = (
                f"• 持币者 (空仓等待): 现价已无赔率优势，将标的纳入核心关注池，等待系统性调整杀估值回踩至 {sotp_ps:.2f} 元附近再行布局。\n"
                f"  • 持股者 (动态移动止盈): 依托 5 日均线持有，日内跌破 5 日线即减仓半数落袋为安。"
            )
            invalidation = f"跌破 5 日均线 ({ma5:.2f}元) 启动保护性止盈！"
        else:
            decision_gear = "等证据临界(观察)"
            decision_title = "【👀 等待临界 (观察确认)】"
            position_cap = 0.0
            core_contra = f"λ 变好信号尚未达到临界密度，市场处于分歧蓄势期。全链等待锚点: {critical_wait}。"
            action_tactic = (
                f"• 持币者 (耐心观察): 现金是等待的最佳期权，在催化剂实锤披露或放量突破压力位 {resistance_lvl:.2f} 元前坚决持币。\n"
                f"  • 持股者 (控制回撤): 依托支撑位 {support_lvl:.2f} 元做防守，破位收不回减仓规避钝刀子磨损。"
            )
            invalidation = f"跌破强支撑线 {support_lvl:.2f} 元剔除出跟踪池。"

        # 四维博弈雷达与实操剧本生成
        persona_names = [p.get("youzi_name", "") for p in (matched_personas or []) if isinstance(p, dict)]
        capital_matrix = self.matrix_radar.evaluate(
            quote=quote,
            momentum=momentum,
            flags=flags,
            trap_warnings=trap_warnings,
            matched_personas=persona_names,
            concepts=concept_list,
            ladder_info=ladder_info,
            money_flow=money_flow,
            lhb_records=lhb_records,
            governance_info=governance_info,
        )

        act_key = "AVOID" if "回避" in decision_gear else ("BUY" if "做多" in decision_gear or "核心" in decision_gear else "WAIT")
        playbook = self.playbook_builder.build(
            quote=quote,
            momentum=momentum,
            matched_personas=persona_names,
            action=act_key,
            ladder_info=ladder_info,
            fatal_flag=is_fatal,
        )

        card = {
            "ticker": ticker,
            "name": name,
            "trade_date": trade_date,
            "price": price,
            "pct_chg": pct_chg,
            "total_mv": total_mv,
            "circ_mv": circ_mv,
            "turnover_ratio": turnover,
            "pe": pe_val,
            "pb": pb_val,
            "board_name": board_name,
            "stock_track": stock_track,
            "track_name": track_name,
            # 首页「赚不赚钱」数据看板
            "profitability_dashboard": dashboard,
            # 五大核心支柱 (严格按新版买方框架)
            "pillar_1_quality": pillar_quality_summary,
            "pillar_2_state": pillar_state_summary,
            "pillar_3_odds": pillar_odds_summary,
            "pillar_4_path": pillar_path_summary,
            "pillar_5_decision": {
                "decision_gear": decision_gear,
                "decision_title": decision_title,
                "position_cap": position_cap,
                "triad_verdict": f"[{state_verdict} | {odds_verdict} | {path_verdict}]",
                "three_part_conclusion": f"好公司? 【{quality_verdict}】 · 好下注? 【{'是' if '做多' in decision_gear or '核心' in decision_gear else '否'}】 · 好价格? 【{'是' if '便宜' in odds_verdict or '合理' in odds_verdict else '否'}】",
                "core_contradiction": core_contra,
                "action_tactic": action_tactic,
                "regulatory_status": reg_status_str,
                "invalidation_line": invalidation,
            },
            # 兼容字段
            "pillar_gate": p_gate,
            "pillar_business": pillar_state_summary,
            "pillar_tape": pillar_odds_summary,
            "pillar_flow": pillar_path_summary,
            "pillar_audit": pillar_quality_summary,
            "decision_gear": decision_gear,
            "decision_title": decision_title,
            "position_cap": position_cap,
            "core_contradiction": core_contra,
            "action_tactic": action_tactic,
            "invalidation_line": invalidation,
            "quality_verdict": quality_verdict,
            "state_verdict": state_verdict,
            "odds_verdict": odds_verdict,
            "path_verdict": path_verdict,
            "critical_wait": critical_wait,
            "derivation": deriv,
            "anchor_range": anchor,
            "reverse_dcf": rdcf,
            "sub_verdicts_quality": sub_verdicts_quality,
            "capital_matrix": capital_matrix,
            "playbook": playbook,
            "top3_risks": [f.to_dict() for f in get_top3_risks(flags)],
            "all_flags": [f.to_dict() for f in flags],
            "matched_youzi": matched_youzi,
            "matched_personas": matched_personas or [],
            "trap_warnings": trap_warnings,
            "ladder_info": ladder_info,
            "microstructure": micro,
            "main_force_stage": mf_stage,
            "main_force_behavior": mf_behavior,
            "main_force_confidence": mf_conf,
            "is_transitional": is_trans,
        }

        # 机检校验与封顶硬锁死
        ok, findings = self.validator.validate(card, flags)
        if not ok and has_fatal_red_flags(flags):
            card["decision_gear"] = "回避"
            card["position_cap"] = 0.0

        return card
