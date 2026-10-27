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
    ) -> dict[str, Any]:
        """按 A 股双轨逻辑合成作战决断卡。"""
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

        # ─── 支柱 ❶ 宏观闸门 / 情绪周期 ───
        is_market_ice = False
        p_gate = "未接入大盘连板情绪"
        if sentiment_overview is not None:
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
        if stock_track == "TRACK_B_INSTITUTIONAL":
            if main_biz:
                top_b = main_biz[0]
                # 寻找最高业务占比
                for b in main_biz:
                    if "其他" not in b.get("name", "") and b.get("ratio", 0) > top_b.get("ratio", 0):
                        top_b = b
                b_name = top_b.get("name", "核心零部件")
                b_ratio = top_b.get("ratio", 0.0)
                p_business = f"✓ 核心主营【{b_name}】营收占比 {b_ratio:.1f}%，主营纯度极高，具备坚实产业壁垒"
            else:
                p_business = "主营业务构成稳健，未见显著蹭概念或空壳化"
        else:
            if ladder_info:
                t_name = ladder_info.get("theme_name", "主线热点")
                b_lvl = ladder_info.get("board_level", 1)
                l_rk = ladder_info.get("leader_rank", 1)
                rk_desc = "龙头领涨" if l_rk == 1 else ("前排中军" if l_rk <= 3 else "后排跟风")
                p_business = f"🔥 所属【{t_name}】主线，处于梯队第 {l_rk} 身位 ({b_lvl}板 {rk_desc})"
            elif concept_list:
                p_business = f"聚焦概念: {', '.join(concept_list[:3])}，但尚未进入连板梯队前排"
            else:
                p_business = "题材概念相对零散，缺乏全市场高辨识度主线催化"

        # ─── 支柱 ❸ 筹码阻力 / 封板生态 ───
        if stock_track == "TRACK_B_INSTITUTIONAL":
            if overhead_chips > 50.0:
                p_tape = f"❌ 上方套牢盘沉重高达 {overhead_chips:.1f}%，距阶段高点回撤 {curr_dd:.1f}%，反弹面临解套盘集中砸盘"
            elif overhead_chips < 20.0 and curr_dd > -10.0:
                p_tape = f"✓ 上方套牢筹码仅 {overhead_chips:.1f}%，筹码锁定优良，回撤阻力较轻"
            else:
                p_tape = f"上方套牢盘 {overhead_chips:.1f}%，距高点回撤 {curr_dd:.1f}%，处于中性震荡消化区间"
        else:
            if ladder_info:
                s_amt = ladder_info.get("seal_amount", 0.0)
                brk = ladder_info.get("broken_count", 0)
                p_tape = f"⚡ 涨停封单 {s_amt/1e4:.0f} 万元，日内炸板 {brk} 次，封板生态{'良好' if brk == 0 else '分歧较大'}"
            else:
                p_tape = f"日线均线: MA5偏离 {momentum.get('ma5_bias', 0.0):+.1f}%，换手率 {turnover:.1f}%"

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
        else:
            flow_parts.append("距异动偏离线(100%)余量充足")

        p_flow = f"主力阶段: {mf_stage} (置信度: {mf_conf:.1f}%{'，多空过渡区' if is_trans else ''})\n  • 微观指纹: " + "；".join(flow_parts)
        if mf_behavior:
            p_flow += f"\n  • 操盘透视: {mf_behavior}"
        if anti_spoofing_list:
            meaningful_audits = [a for a in anti_spoofing_list if "未检测到明显反常" not in a and "数据暂缺" not in a]
            if meaningful_audits:
                p_flow += "\n  • 反伪装穿透: " + " | ".join(meaningful_audits)

        # ─── 支柱 ❺ 本土二元排雷 ───
        if is_fatal:
            p_audit = f"🔴 触发买方一票否决: {fatal_flags[0].title} (存贷/商誉/质押/退市指标触及红线)"
        elif high_flags:
            p_audit = f"⚠️ 存在治理或财务瑕疵: {high_flags[0].title}，需加强防守盯盘"
        else:
            p_audit = "✓ 存贷双高、商誉减值、大股东质押与退市财务指标全量排查，未见致命财务红旗 (0红旗)"

        # ─── 最终买方决断与实操纪律 (T+1 纪律与主力行为死锁) ───
        if is_fatal:
            decision_gear = "回避"
            decision_title = "【🚫 铁律回避】"
            position_cap = 0.0
            core_contra = f"公司触及买方合规红线: {fatal_flags[0].title}。在 A 股常态化退市与强监管下，本金安全高于一切，坚决一票否决！"
            action_tactic = "无论盘中如何脉冲拉升，严禁任何形式的买入与抄底！若有持仓立即市价离场。"
            invalidation = "一票否决绝对生效，禁止建仓！"
        elif is_market_ice and stock_track == "TRACK_A_THEME":
            decision_gear = "观察"
            decision_title = "【👀 情绪防守】"
            position_cap = 0.0
            core_contra = "大盘处于短线冰点或强退潮期，空间板受压制且涨停家数锐减，接力亏钱效应扩散，短线胜率极低。"
            action_tactic = "【空仓防守】管住手不伸手接飞刀，耐心等待大盘出现放量共振冰点转折信号后再行开仓。"
            invalidation = "大盘退潮期禁止开新仓，严禁逆势接力！"
        elif mf_stage_code == "STAGE_5_EXHAUSTION_ACCELERATION":
            # ─────────────────────────────────────────────────────────
            # 生产级安全死锁：高标缩量加速赶顶期，持币者严禁追高！买入仓位锁定为 0.0%！
            # ─────────────────────────────────────────────────────────
            decision_gear = "观察"
            decision_title = "【🚀 缩量加速赶顶 (严禁追高)】"
            position_cap = 0.0
            b_lvl = (ladder_info or {}).get("board_level", 0)
            core_contra = (
                f"标的处于高位加速冲顶阶段 (连板身位: {b_lvl}板)；底仓知情资金建仓均价 {smart_vwap:.2f} 元，"
                f"主力底层账面浮盈巨大且筹码高度锁定。A股向来'缩量加速即见顶'，此阶段持股者锁仓享受溢价，"
                f"持币者新开仓盈亏比极度恶化，买方仓位硬性锁死为 0%！"
            )
            action_tactic = "【持仓锁仓守利 / 严禁追高开仓】未持股者严禁以任何理由追高接飞刀；持股者紧盯次日早盘分时，一旦开板放量或低开不及预期即刻市价全部获利了结！"
            invalidation = "早盘竞价大幅低开或日内放量开板瞬间破线，即刻全仓止盈离场，绝不犹豫！"
        elif mf_stage_code == "STAGE_6_DISTRIBUTION" or mf_override == "回避":
            decision_gear = "回避"
            decision_title = "【⚠️ 派发出货防守】"
            position_cap = 0.0
            core_contra = "主力行为生命周期处于【⚠️ 对倒派发出货期】：微观呈现高效率卖盘持续出逃，量价严重背离，任何盘中脉冲均是诱多陷阱，买方铁律严禁接盘！"
            action_tactic = "【坚决清仓回避】已有持仓逢高市价止损止盈离场，未持仓者坚决一股不买！"
            invalidation = "派发期未结束前，绝不盲目抄底！"
        elif mf_stage_code == "STAGE_7_PASSIVE_DRIFT":
            decision_gear = "观察"
            decision_title = "【📉 无抵抗阴跌 (防守观望)】"
            position_cap = 0.0
            core_contra = f"标的主力处于【📉 无抵抗阴跌出清期】：上方套牢盘高达 {overhead_chips:.1f}%，现价跌破知情均线 ({smart_vwap:.2f}元)，机构被动躺平缺乏护盘托底，左侧接飞刀极易被钝刀子割肉。"
            action_tactic = f"【空仓观望】严禁左侧盲目猜底，下方强支撑位 {support_lvl:.2f} 元；耐心等待放量长阳收复 5 日线并构筑右侧底分型后再行评估。"
            invalidation = f"严格执行 A 股 T+1 纪律：若次日早盘继续低开跌破昨日最低点，彻底放弃交易机会，严禁盲目左侧接飞刀！"
        elif stock_track == "TRACK_B_INSTITUTIONAL":
            # 机构中军逻辑
            is_bull = momentum.get("is_bullish_ma", False)
            if not is_bull or overhead_chips > 45.0 or pct_chg < -2.0 or mf_stage_code not in ("STAGE_4_HEALTHY_MARKUP", "STAGE_3_QUIET_WASHOUT"):
                decision_gear = "观察"
                decision_title = "【👀 观望防守】"
                position_cap = 0.0
                if smart_phase == "DISTRIBUTION":
                    flow_sub = f"微观呈现高位知情资金集中派发 (卖盘 {smart_sell:.1f}%)"
                elif smart_phase == "PASSIVE_FALL":
                    flow_sub = f"现价跌破知情均线 ({smart_vwap:.2f}元) 且缺乏机构护盘托底"
                else:
                    flow_sub = "微观知情资金处于存量观望、缺乏主动买单推升"
                core_contra = f"基本面健康且估值具备安全垫 (PE {pe_val:.1f}x)，但短期日线受阻于解套抛压 ({overhead_chips:.1f}%) 且{flow_sub}。在未见放量长阳收复 5 日线前，绝不盲目抄底！"
                action_tactic = f"【弱势等待企稳】下方强支撑位 {support_lvl:.2f} 元；必须等待在支撑位缩量企稳并收复 5 日线后再寻右侧入场点。"
                invalidation = f"严格执行 A 股 T+1 纪律：若次日早盘继续低开跌破昨日最低点，彻底放弃交易机会，严禁盲目左侧接飞刀！"
            else:
                decision_gear = "买入"
                decision_title = "【🔥 趋势做多】"
                position_cap = min(0.20, mf_cap if mf_cap > 0 else 0.15)
                core_contra = f"核心主营纯度高，行业处于景气复苏通道，均线多头趋势健康，主力处于{mf_stage}，大资金温和承接，具备中长期波段配置价值。"
                action_tactic = f"【回踩均线低吸】依托 5 日线或分时均线企稳低吸，目标看至上方阻力位 {resistance_lvl:.2f} 元。"
                invalidation = f"严格执行 A 股 T+1 纪律：建仓日不可卖出；次日若收盘跌破 MA20 趋势破位，坚决离场防守。"
        else:
            # 短线题材逻辑
            is_leader = ladder_info.get("is_leader", False) if ladder_info else False
            if (is_leader or pct_chg >= 4.0) and mf_stage_code in ("STAGE_4_HEALTHY_MARKUP", "STAGE_1_ACCUMULATION", "STAGE_3_QUIET_WASHOUT"):
                decision_gear = "买入"
                decision_title = "【🔥 主升做多】"
                position_cap = min(0.20, mf_cap if mf_cap > 0 else 0.15)
                core_contra = f"题材热点聚焦，标的处于梯队前排核心，主力处于{mf_stage}且通过反伪装检验，具备涨停接力与隔夜溢价预期。"
                action_tactic = f"【龙头加速/均线低吸】次日早盘 9:25 竞价若高开 1%~3% 且量比>2 顺势跟进，或开盘回踩分时均线不破企稳低吸。"
                invalidation = f"严格执行 A 股 T+1 纪律：建仓日无法卖出；次日开盘若大幅低开破位或日内反抽无力，坚决市价止损出局，严禁死扛！"
            else:
                decision_gear = "观察"
                decision_title = "【👀 观望确认】"
                position_cap = 0.0
                core_contra = f"处于题材分歧震荡阶段 (主力阶段: {mf_stage})，板块尚未形成高确定性合力，追高盈亏比不足。"
                action_tactic = "【等待转强确认】观察次日早盘能否放量弱转强并向上突破临界点，未确认前坚决列入观察池。"
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
