"""Five-node judgment chain synthesizer for AST-Trader."""
from __future__ import annotations

from typing import Any

import config
from core.capital_matrix import CapitalMatrixRadar
from core.execution_playbook import PlaybookBuilder
from lint.validator import LintValidator
from .red_flags import LEVEL_FATAL, RedFlagItem, get_top3_risks, has_fatal_red_flags


class JudgmentChainRunner:
    """A股实战因果作战决断引擎 (物种分流 + 双轨决策 + 本土二元排雷 + T+1纪律)."""

    def __init__(self) -> None:
        self.validator = LintValidator()
        self.matrix_radar = CapitalMatrixRadar()
        self.playbook_builder = PlaybookBuilder()

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
    ) -> dict[str, Any]:
        """按 A 股双轨逻辑合成作战决断卡 (深度穿透业务纯度、封板生态、资金动向、本土排雷与双轨实战决断)."""
        price = quote.get("close", 0.0)
        pct_chg = quote.get("pct_chg", 0.0)
        turnover = quote.get("turnover_ratio", 0.0)
        ma5 = momentum.get("ma5", price)
        ma20 = momentum.get("ma20", price)
        overhead_chips = momentum.get("overhead_chip_pct", 0.0)
        curr_dd = momentum.get("current_drawdown", 0.0)
        support_lvl = momentum.get("support_level", round(price * 0.95, 2))
        resistance_lvl = momentum.get("resistance_level", round(price * 1.05, 2))
        concept_list = concepts or []

        # 1. 交易制度识别：主板 (10%)、双创板 (20%)、北交所 (30%)
        is_gem_star = ticker.startswith(("300", "301", "688"))
        is_bse = ticker.startswith(("8", "4", "920"))
        board_name = "双创板 (20%涨跌停)" if is_gem_star else ("北交所 (30%涨跌停)" if is_bse else "主板 (10%涨跌停)")

        # 2. 标的物种判定 (Asset Classification)
        stock_track, track_name = self.classify_stock_track(quote, ladder_info, concept_list)

        # 3. 本土排雷二元过滤 (Fatal Red Flag Check)
        fatal_flags = [f for f in flags if f.level == LEVEL_FATAL]
        high_flags = [f for f in flags if f.level == "🟠"]
        is_fatal = len(fatal_flags) > 0

        # 计算 10 日累计涨幅以精准测算监管余量
        ret_10d = 0.0
        if daily_df is not None and hasattr(daily_df, "empty") and not daily_df.empty and len(daily_df) >= 2:
            closes_asc = daily_df.iloc[::-1]["close"].reset_index(drop=True)
            c_latest = float(closes_asc.iloc[-1])
            c_10_ago = float(closes_asc.iloc[-min(10, len(closes_asc))])
            if c_10_ago > 0:
                ret_10d = round((c_latest - c_10_ago) / c_10_ago * 100.0, 1)

        # ─── 支柱 ❶ 宏观闸门 / 情绪周期 (多维大盘与情绪交叉验证) ───
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

        # ─── 支柱 ❷ 业务纯度 / 题材身位 ───
        main_biz = (governance_info or {}).get("main_business", [])
        top_biz_name = "未披露主营明细"
        top_biz_ratio = 0.0
        if main_biz:
            top_b = main_biz[0]
            for b in main_biz:
                if "其他" not in b.get("name", "") and b.get("ratio", 0) > top_b.get("ratio", 0):
                    top_b = b
            top_biz_name = top_b.get("name", "主营业务")
            top_biz_ratio = float(top_b.get("ratio", 0.0))

        c_names = concept_list[:4]
        has_reorg = any("重组" in c or "国企改革" in c or "上海" in c or "国资" in c or "并购" in c for c in concept_list)
        has_tech = any("AI" in c or "算力" in c or "半导体" in c or "芯片" in c or "机器人" in c for c in concept_list)
        has_consume = any("零售" in c or "百货" in c or "消费" in c or "商业" in c for c in concept_list)

        if ladder_info:
            t_name = ladder_info.get("theme_name", "主线热点")
            b_lvl = ladder_info.get("board_level", 1)
            l_rk = ladder_info.get("leader_rank", 1)
            t_zt = ladder_info.get("theme_zt_count", 1)
            rk_desc = "板块龙头领涨" if l_rk == 1 else ("前排中军" if l_rk <= 3 else "后排跟风")

            # 催化溯源分析
            if has_reorg:
                catalyst_reason = f"【{t_name} + 地方国资重组/并购整合预期】驱动，属存量游资题材抱团博傻，去伪存真处于纯预期博弈阶段，无实质主营业绩拐点"
            elif has_tech and top_biz_ratio < 40.0:
                catalyst_reason = f"【{t_name}跨界映射/概念炒作】，核心业务尚未实质贡献利润，典型炒概念阶段"
            elif has_tech:
                catalyst_reason = f"【{t_name}核心产业逻辑驱动】，行业景气度周期共振"
            elif has_consume:
                catalyst_reason = f"【消费内需政策博弈 + 超跌轮动】，属存量游资避险接力"
            else:
                catalyst_reason = f"【{t_name}热点事件催化】，概念标签: {', '.join(c_names) if c_names else '概念脉冲'}"

            p_biz_purity = f"主营【{top_biz_name}】营收占比 {top_biz_ratio:.1f}%" if top_biz_ratio > 0 else "主营业务传统"
            pure_level = "主营业务纯度较高" if top_biz_ratio >= 60 else ("主营构成相对多元" if top_biz_ratio >= 30 else "概念相关度偏低，存在纯蹭热点嫌疑")

            p_business = (
                f"• 核心主营: {p_biz_purity} ({pure_level})\n"
                f"  • 催化溯源: {catalyst_reason}\n"
                f"  • 梯队身位: 所属【{t_name}】主线第 {l_rk} 身位 ({b_lvl}板 {rk_desc}，板块内涨停共 {t_zt} 家)"
            )
        else:
            if top_biz_ratio >= 60.0:
                p_biz_eval = f"✓ 核心主营【{top_biz_name}】营收占比 {top_biz_ratio:.1f}%，主营纯度高，具备坚实产业壁垒"
            elif top_biz_ratio >= 30.0:
                p_biz_eval = f"核心主营【{top_biz_name}】营收占比 {top_biz_ratio:.1f}%，多元化综合经营"
            else:
                p_biz_eval = "主营构成相对分散，未见绝对单一支柱业务"

            c_str = f"聚焦概念: {', '.join(c_names)}" if c_names else "缺乏高辨识度主线题材"
            p_business = f"• 主营纯度: {p_biz_eval}\n  • 题材映射: {c_str}，当前未进入全市场连板梯队前排"

        # ─── 支柱 ❸ 筹码阻力 / 封板生态 ───
        circ_mv = quote.get("circ_mv", 0.0)
        day_amount = quote.get("amount", 0.0)
        profit_chip_pct = round(100.0 - overhead_chips, 1)

        if ladder_info:
            s_amt = float(ladder_info.get("seal_amount", 0.0) or 0.0)
            brk = int(ladder_info.get("broken_count", 0) or 0)
            lim_time = str(ladder_info.get("limit_time", "") or "")

            seal_turn_ratio = (s_amt / day_amount * 100.0) if day_amount > 0 else 0.0
            seal_circ_ratio = (s_amt / circ_mv * 100.0) if circ_mv > 0 else 0.0

            if seal_turn_ratio >= 50.0:
                seal_strength = "极强缩量封死"
            elif seal_turn_ratio >= 20.0:
                seal_strength = "强力封板"
            elif seal_turn_ratio >= 10.0:
                seal_strength = "中等承接封板"
            else:
                seal_strength = "弱封/承接脆弱"

            if lim_time and lim_time < "09:35:00":
                time_desc = f"{lim_time} 秒封 (游资合力开盘抢筹)"
            elif lim_time and lim_time < "11:30:00":
                time_desc = f"{lim_time} 早盘换手封板"
            elif lim_time and lim_time < "14:30:00":
                time_desc = f"{lim_time} 午后脉冲封板"
            elif lim_time:
                time_desc = f"{lim_time} 尾盘偷袭拉板 (次日溢价脆弱)"
            else:
                time_desc = "日内封板"

            brk_desc = f"日内炸板 {brk} 次 (分歧明显)" if brk > 0 else "日内一封到底零炸板"

            if profit_chip_pct >= 95.0:
                chip_desc = f"全市场获利盘高达 {profit_chip_pct:.1f}% (浮盈盘极度丰厚)，上方已无套牢阻力峰；但浮盈筹码锁仓成本极低，次日一旦分歧极易遭遇获利盘集体砸盘"
            elif overhead_chips >= 40.0:
                chip_desc = f"上方套牢筹码达 {overhead_chips:.1f}%，距阶段密集成交套牢区仅差临门一脚，反弹面临解套盘集中砸盘阻力"
            else:
                chip_desc = f"获利盘占比 {profit_chip_pct:.1f}% / 套牢盘 {overhead_chips:.1f}%，筹码结构处于良性沉淀区间"

            p_tape = (
                f"• 封板质量: 封单 {s_amt/1e4:.0f} 万元 (封成比 {seal_turn_ratio:.1f}% [{seal_strength}] | 占流通盘 {seal_circ_ratio:.2f}%)，{time_desc}，{brk_desc}\n"
                f"  • 筹码博弈: {chip_desc}"
            )
        else:
            if overhead_chips > 50.0:
                chip_eval = f"❌ 上方套牢盘沉重高达 {overhead_chips:.1f}%，距阶段高点回撤 {curr_dd:.1f}%，反弹面临解套盘集中砸盘"
            elif overhead_chips < 20.0 and curr_dd > -10.0:
                chip_eval = f"✓ 上方套牢筹码仅 {overhead_chips:.1f}%，获利盘 {profit_chip_pct:.1f}%，筹码锁定优良，回撤阻力较轻"
            else:
                chip_eval = f"上方套牢盘 {overhead_chips:.1f}% (获利盘 {profit_chip_pct:.1f}%)，距高点回撤 {curr_dd:.1f}%，处于中性震荡消化区间"

            p_tape = f"• 筹码分布: {chip_eval}\n  • 均线偏离: MA5偏离度 {momentum.get('ma5_bias', 0.0):+.1f}%，换手率 {turnover:.2f}%"

        # ─── 支柱 ❹ 资金动向 / 主力生命周期与监管余量 ───
        mf = money_flow or {}
        main_net = mf.get("main_net_wan", 0.0)
        pe_val = quote.get("pe", 0.0)
        pb_val = quote.get("pb", 0.0)

        micro = microstructure or {}
        mf_stage = micro.get("main_force_stage", "【⏳ 存量震荡/等待方向期】")
        mf_behavior = micro.get("main_force_behavior", "")
        mf_risk = micro.get("main_force_risk", "")
        mf_stage_code = micro.get("stage_code", "")
        mf_override = micro.get("decision_gear_override")
        mf_cap = micro.get("suggested_pos_cap", 0.15)
        mf_rec_act = micro.get("recommended_action", "")
        mf_conf = micro.get("main_force_confidence", 80.0)
        is_trans = micro.get("is_transitional", False)
        anti_spoofing_list = micro.get("anti_spoofing_summary", [])

        smart_q = micro.get("smart_q")
        smart_phase = micro.get("smart_phase", "NEUTRAL")
        smart_vwap = micro.get("smart_vwap", price)
        smart_buy = micro.get("smart_buy_ratio", 50.0)
        smart_sell = micro.get("smart_sell_ratio", 50.0)
        auc_chg = micro.get("auction_open_chg_pct", 0.0)
        auc_amt = micro.get("auction_open_amt_wan", 0.0)

        flow_parts = []
        if smart_q is not None and smart_q > 0:
            flow_parts.append(f"聪明钱 Q={smart_q:.3f} (知情成本 {smart_vwap:.2f}元 vs 现价 {price:.2f}元)")
            if auc_amt > 1000:
                flow_parts.append(f"竞价抢筹 {auc_amt:.0f}万元 ({auc_chg:+.2f}%)")
            elif auc_amt > 0:
                flow_parts.append(f"竞价偏淡 ({auc_chg:+.2f}%, {auc_amt:.0f}万)")
        else:
            flow_parts.append(f"主力大单净额 {main_net/100:+.1f} 亿元")

        if stock_track == "TRACK_B_INSTITUTIONAL":
            flow_parts.append(f"估值 PE(TTM) {pe_val:.1f}x / PB {pb_val:.1f}x")

        # 监管偏离值硬核量化
        margin_100 = round(max(0.0, 100.0 - ret_10d), 1)
        board_cap_pct = 20.0 if is_gem_star else (30.0 if is_bse else 10.0)
        boards_to_limit = max(0, int(margin_100 / board_cap_pct))

        if ret_10d >= 70.0:
            reg_margin_str = f"近 10 日累计涨幅 {ret_10d:+.1f}%，距 10 日 100% 严重异常波动停牌红线仅剩 {margin_100:.1f}% (约 {boards_to_limit} 个板即触碰重点监控/停牌核查，监管高压！)"
        elif ret_10d > 0.0:
            reg_margin_str = f"近 10 日累计涨幅 {ret_10d:+.1f}%，距严重异常波动监管红线(+100%)尚余 {margin_100:.1f}% 空间 (监管余量相对充足)"
        else:
            reg_margin_str = "距严重异常波动监管红线(10日100%)余量充足"

        flow_parts.append(reg_margin_str)

        p_flow = f"主力阶段: {mf_stage} (置信度: {mf_conf:.1f}%{'，多空过渡区' if is_trans else ''})\n  • 微观指纹: " + "；".join(flow_parts)
        if mf_behavior:
            p_flow += f"\n  • 操盘透视: {mf_behavior}"
        if anti_spoofing_list:
            meaningful_audits = []
            for a in anti_spoofing_list:
                if "未检测到明显反常" in a or "数据暂缺" in a:
                    continue
                # 消除语义冲突：在高标赶顶期屏蔽低吸字眼
                if mf_stage_code in ("STAGE_5_EXHAUSTION_ACCELERATION", "STAGE_6_DISTRIBUTION"):
                    a = a.replace("【主动低吸收集】", "【高位封单锁仓/大单扫货】")
                    a = a.replace("主动低吸收集", "高位锁仓推升")
                meaningful_audits.append(a)
            if meaningful_audits:
                p_flow += "\n  • 反伪装穿透: " + " | ".join(meaningful_audits)

        # ─── 支柱 ❺ 本土二元排雷 (短线致命陷阱与财务风控) ───
        has_reduction = bool((governance_info or {}).get("has_reduction_plan", False))
        pledge_ratio = float((governance_info or {}).get("pledge_ratio", 0.0) or 0.0)

        short_term_traps = []
        if has_reduction:
            short_term_traps.append("⚠️ 存在在途大股东/董监高减持计划 (随时面临高位减持公告利空背刺)")
        else:
            short_term_traps.append("✓ 无在途大股东减持计划")

        if pledge_ratio >= 50.0:
            short_term_traps.append(f"🔴 控股股东质押率达 {pledge_ratio:.1f}% (高质押爆仓风险)")
        elif pledge_ratio > 0:
            short_term_traps.append(f"✓ 控股股东质押率 {pledge_ratio:.1f}% (处于安全线内)")
        else:
            short_term_traps.append("✓ 控股股东质押率 0.0% (无质押平仓风险)")

        pe_str = f"市盈率 PE(TTM) {pe_val:.1f}x" if pe_val > 0 else "微利或亏损"
        if pe_val > 100.0 or pe_val <= 0:
            pure_warn = f"⚠️ 估值风险: {pe_str}，业绩弹性不足，题材炒作若预期落空将面临估值与情绪双杀"
        else:
            pure_warn = f"✓ 估值处于合理区间 ({pe_str})"

        if is_fatal:
            p_audit = (
                f"🔴 触发买方一票否决: {fatal_flags[0].title} (存贷/商誉/质押/退市指标触及红线，坚决一票否决)\n"
                f"  • 治理与减持: {' | '.join(short_term_traps)}"
            )
        elif high_flags:
            p_audit = (
                f"⚠️ 存在财务或治理瑕疵: {high_flags[0].title} (需加强防守盯盘)\n"
                f"  • 治理与减持: {' | '.join(short_term_traps)}\n"
                f"  • 估值纯度: {pure_warn}"
            )
        else:
            p_audit = (
                f"✓ 存贷双高、商誉减值、控股质押与退市指标全面排查，未见致命财务红旗 (0红旗)\n"
                f"  • 治理与减持: {' | '.join(short_term_traps)}\n"
                f"  • 估值纯度: {pure_warn}"
            )

        # ─── 最终买方决断与实操纪律 (双轨分流 + 具体价位与分时条件) ───
        life_line = round(price * 0.98, 2)
        stop_line = round(min(support_lvl, price * 0.96), 2)

        if is_fatal:
            decision_gear = "回避"
            decision_title = "【🚫 铁律回避】"
            position_cap = 0.0
            core_contra = f"公司触及买方合规红线: {fatal_flags[0].title}。在 A 股常态化退市与强监管下，本金安全高于一切，坚决一票否决！"
            action_tactic = (
                "• 持币者 (空仓严禁买入): 无论盘中如何快速脉冲拉升，均为诱多陷阱，坚决一股不买！\n"
                "  • 持股者 (即刻清仓离场): 触及买方合规死锁线，次日开盘即以市价止损止盈清仓，绝不心存侥幸！"
            )
            invalidation = "一票否决绝对生效，禁止建仓！"
        elif is_market_ice and stock_track == "TRACK_A_THEME":
            decision_gear = "观察"
            decision_title = "【👀 情绪防守】"
            position_cap = 0.0
            if macro_res and macro_res.resonance_type == "DIVERGENCE_SPECULATIVE_CLING":
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
            invalidation = f"分时均线与昨日收盘生命线 ({life_line:.2f}元) 为绝对防线，日内跌破 3 分钟未收回即全仓止盈止损，绝不参与转跌后的天地板博傻！"
        elif mf_stage_code == "STAGE_5_EXHAUSTION_ACCELERATION":
            decision_gear = "观察"
            decision_title = "【🚀 缩量加速赶顶 (持股锁仓 / 严禁追高)】"
            position_cap = 0.0
            b_lvl = (ladder_info or {}).get("board_level", 0)
            profit_pct = ((price - smart_vwap) / smart_vwap * 100.0) if smart_vwap > 0 else 0.0
            core_contra = (
                f"标的处于高位加速冲顶阶段 (连板身位: {b_lvl}板)；底仓知情资金建仓均价 {smart_vwap:.2f} 元 (浮盈达 +{profit_pct:.1f}%)，"
                f"筹码极度锁定。A股向来'缩量加速即见顶'，此阶段持股者锁仓享受溢价，持币者新开仓盈亏比极度恶化，买方新开仓位硬性锁死为 0%！"
            )
            action_tactic = (
                "• 持币者 (空仓观望): 坚决一股不买，严禁在加速末日轮追高接飞刀；若要参与必须等待日内放量大分歧换手充分后的企稳承接。\n"
                "  • 持股者 (持股守利): 次日早盘 9:25 竞价若低开低于昨天收盘价或竞价成交额不及前日 15%，视为承接衰竭，开盘即刻市价全部获利了结；盘中一旦开板放量且换手率超过 15%，无条件止盈清仓，严防天地板！"
            )
            invalidation = f"分时生命线 ({life_line:.2f}元) 为日内绝对退出线，一旦跌破 3 分钟未收回或早盘竞价大幅低开，即刻全仓止盈离场，绝不犹豫！"
        elif mf_stage_code == "STAGE_6_DISTRIBUTION" or mf_override == "回避":
            decision_gear = "回避"
            decision_title = "【⚠️ 派发出货防守】"
            position_cap = 0.0
            core_contra = "主力行为生命周期处于【⚠️ 对倒派发出货期】：微观呈现高效率卖盘持续出逃，量价严重背离，任何盘中脉冲均是诱多陷阱，买方铁律严禁接盘！"
            action_tactic = (
                "• 持币者 (坚决回避): 盘中任何快速反抽脉冲均为诱多，坚决一股不买！\n"
                "  • 持股者 (逢高止损止盈): 已有持仓逢反抽立即挂市价单清仓离场，绝不拖泥带水！"
            )
            invalidation = "派发期未结束前，绝不盲目抄底！"
        elif mf_stage_code == "STAGE_7_PASSIVE_DRIFT":
            decision_gear = "观察"
            decision_title = "【📉 无抵抗阴跌 (防守观望)】"
            position_cap = 0.0
            core_contra = f"标的主力处于【📉 无抵抗阴跌出清期】：上方套牢盘高达 {overhead_chips:.1f}%，现价跌破知情均线 ({smart_vwap:.2f}元)，机构被动躺平缺乏护盘托底，左侧接飞刀极易被钝刀子割肉。"
            action_tactic = (
                f"• 持币者 (空仓观望): 严禁左侧盲目猜底，下方强支撑位 {support_lvl:.2f} 元；耐心等待放量长阳收复 5 日线并构筑右侧底分型后再行评估。\n"
                f"  • 持股者 (逢反抽减亏): 若次日早盘继续低开跌破昨日最低点，果断止损离场，绝不任由钝刀子割肉拉大亏损。"
            )
            invalidation = f"严格执行 A 股 T+1 纪律：跌破强支撑位 {stop_line:.2f} 元坚决离场防守，严禁盲目左侧接飞刀！"
        elif stock_track == "TRACK_B_INSTITUTIONAL":
            is_bull = momentum.get("is_bullish_ma", False)
            if not is_bull or overhead_chips > 45.0 or pct_chg < -2.0 or mf_stage_code not in ("STAGE_4_HEALTHY_MARKUP", "STAGE_3_QUIET_WASHOUT") or is_market_ice:
                decision_gear = "观察"
                decision_title = "【👀 观望防守】"
                position_cap = 0.0
                if is_market_ice:
                    core_contra = f"大盘整体处于破位阴跌/弱势退潮生态 (宏观闸门收紧)，系统性 Beta 风险显著，个股难以独善其身。买方铁律严禁在系统性杀跌中盲目做多！"
                else:
                    core_contra = f"基本面健康且估值具备安全垫 (PE {pe_val:.1f}x)，但短期日线受阻于解套抛压 ({overhead_chips:.1f}%)。在未见放量长阳收复 5 日线前，绝不盲目抄底！"
                action_tactic = (
                    f"• 持币者 (耐心等待): 下方强支撑位 {support_lvl:.2f} 元；必须等待在支撑位缩量企稳并收复 5 日线后再寻右侧入场点。\n"
                    f"  • 持股者 (控制回撤): 依托 20 日均线 ({ma20:.2f}元) 防守，若破位收不回减半仓防守。"
                )
                invalidation = f"严格执行 A 股 T+1 纪律：跌破防守线 {stop_line:.2f} 元放弃交易机会，严禁盲目左侧接飞刀！"
            else:
                decision_gear = "买入"
                decision_title = "【🔥 趋势做多】"
                position_cap = min(0.20, mf_cap if mf_cap > 0 else 0.15)
                core_contra = f"核心主营纯度高，行业处于景气复苏通道，均线多头趋势健康，主力处于{mf_stage}，大资金温和承接，具备中长期波段配置价值。"
                action_tactic = (
                    f"• 持币者 (回踩低吸): 依托 5 日线 ({ma5:.2f}元) 或分时均线企稳低吸，目标看至上方阻力位 {resistance_lvl:.2f} 元。\n"
                    f"  • 持股者 (顺势持股): 均线多头排列良好，依托 10 日线波段持股，未见放量滞涨长上影线前耐心持股守利。"
                )
                invalidation = f"严格执行 A 股 T+1 纪律：建仓日不可卖出；次日若收盘跌破 MA20 趋势破位线 ({ma20:.2f}元)，坚决离场防守。"
        else:
            is_leader = ladder_info.get("is_leader", False) if ladder_info else False
            if (is_leader or pct_chg >= 4.0) and mf_stage_code in ("STAGE_4_HEALTHY_MARKUP", "STAGE_1_ACCUMULATION", "STAGE_3_QUIET_WASHOUT"):
                decision_gear = "买入"
                decision_title = "【🔥 主升做多】"
                position_cap = min(0.20, mf_cap if mf_cap > 0 else 0.15)
                core_contra = f"题材热点聚焦，标的处于梯队前排核心，主力处于{mf_stage}且通过反伪装检验，具备涨停接力与隔夜溢价预期。"
                action_tactic = (
                    f"• 持币者 (竞价跟进/分时低吸): 次日早盘 9:25 竞价若高开 1%~3% 且量比>2 顺势跟进，或开盘回踩分时均线不破企稳低吸。\n"
                    f"  • 持股者 (加速锁仓/分歧减半): 早盘若快速封板则持股不动，若开盘放量滞涨或冲高回落，逢高兑现半仓锁定利润。"
                )
                invalidation = f"严格执行 A 股 T+1 纪律：建仓日无法卖出；次日开盘若大幅低开破位 ({life_line:.2f}元) 或日内反抽无力，坚决市价止损出局，严禁死扛！"
            else:
                decision_gear = "观察"
                decision_title = "【👀 观望确认】"
                position_cap = 0.0
                core_contra = f"处于题材分歧震荡阶段 (主力阶段: {mf_stage})，板块尚未形成高确定性合力，追高盈亏比不足。"
                action_tactic = (
                    "• 持币者 (观察等待): 观察次日早盘能否放量弱转强并向上突破临界点，未确认前坚决列入观察池。\n"
                    "  • 持股者 (逢高减仓): 震荡受阻于上方阻力位，可逢冲高适度减仓控制风险。"
                )
                invalidation = f"跌破支撑位 {support_lvl:.2f} 元放弃。"

        # 四维资金博弈雷达与实操剧本 (集成)
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

        act_key = "AVOID" if decision_gear == "回避" else ("BUY" if decision_gear == "买入" else "WAIT")
        playbook = self.playbook_builder.build(
            quote=quote,
            momentum=momentum,
            matched_personas=persona_names,
            action=act_key,
            ladder_info=ladder_info,
            fatal_flag=is_fatal,
        )

        # 兼容旧接口字段
        quality_verdict = p_audit
        state_verdict = f"[{board_name}] {'均线多头' if momentum.get('is_bullish_ma') else '均线空头'} (MA5={ma5:.2f}, MA20={ma20:.2f})"
        odds_verdict = f"参考支撑 {support_lvl:.2f} 元，上方阻力 {resistance_lvl:.2f} 元"
        path_verdict = p_tape

        card = {
            "ticker": ticker,
            "name": name,
            "trade_date": trade_date,
            "price": price,
            "pct_chg": pct_chg,
            "total_mv": quote.get("total_mv", 0.0),
            "circ_mv": quote.get("circ_mv", 0.0),
            "turnover_ratio": turnover,
            "pe": quote.get("pe", 0.0),
            "pb": quote.get("pb", 0.0),
            "board_name": board_name,
            "stock_track": stock_track,
            "track_name": track_name,
            "pillar_gate": p_gate,
            "pillar_business": p_business,
            "pillar_tape": p_tape,
            "pillar_flow": p_flow,
            "pillar_audit": p_audit,
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
            "market_gate_verdict": p_gate,
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
            "main_force_risk": mf_risk,
            "main_force_confidence": mf_conf,
            "is_transitional": is_trans,
            "suggested_pos_cap": mf_cap,
            "recommended_action": mf_rec_act,
            "anti_spoofing_summary": anti_spoofing_list,
            "stage_scores": micro.get("scores", {}),
        }

        # 门控机检自动修复
        ok, findings = self.validator.validate(card, flags)
        if not ok and has_fatal_red_flags(flags):
            card["decision_gear"] = "回避"
            card["position_cap"] = 0.0

        return card
