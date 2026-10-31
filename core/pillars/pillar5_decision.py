"""Pillar 5 Builder: 实战双轨决断与战术执行 (行动档位、仓位上限、龙虎榜量化砸盘提示性预警)."""
from __future__ import annotations

from typing import Any
import config
from core.red_flags import RedFlagItem
from core.seat_matcher import evaluate_lhb_dump_risk
from core.types import (
    DecisionVerdict,
    OddsVerdict,
    PathVerdict,
    QualityVerdict,
    SingleStockContext,
    StateVerdict,
)

#: 行动档位 → AVOID 分支
DECISION_GEAR_AVOID: frozenset[str] = frozenset({"回避", "减仓"})
#: 弱市需走防守分支的轨道
TRACK_A_THEME = "TRACK_A_THEME"
TRACK_UNVERIFIED = "TRACK_UNVERIFIED"
TRACK_DEFENSIVE_ON_ICE: frozenset[str] = frozenset({TRACK_A_THEME, TRACK_UNVERIFIED})

#: 一字跌停不可卖流动性免责提示 (P1-7 残余修复)
DISCLAIMER_LIMIT_DOWN = "（⚠️ 提示: 若遇一字跌停等流动性锁死极端行情，市价单将无法成交，须挂跌停价排队等待撮合，实际损失可能超出计划）"


def is_avoid_gear(decision_gear: str | None) -> bool:
    """行动档位是否属于回避类。"""
    return (decision_gear or "") in DECISION_GEAR_AVOID


def is_good_company(quality_verdict: str | None) -> bool:
    """质地判定是否为"好公司"。显式白名单，杜绝「不好」被子串匹配误判为「好」。"""
    return (quality_verdict or "") in {"好", "部分好"}


def is_good_price(odds_verdict: str | None) -> bool:
    """赔率判定是否为"好价格"。"""
    return (odds_verdict or "") in {"便宜(有余地)", "合理"}


def format_three_part_conclusion(
    quality_verdict: str | None,
    position_cap: float,
    odds_verdict: str | None,
    suffix: str = "",
) -> str:
    """生成三分结论串 — 全系统唯一出口。"""
    good_company = "是" if is_good_company(quality_verdict) else "否/存疑"
    good_bet = "是" if position_cap > 0 else "否"
    good_price = "是" if is_good_price(odds_verdict) else "否"
    tail = f" ({suffix})" if suffix else ""
    return f"好公司? 【{good_company}】 · 好下注? 【{good_bet}】 · 好价格? 【{good_price}】{tail}"


def resolve_position_cap(
    mf_cap: float | None,
    mf_confidence: float | None,
    left_tail_depth_pct: float | None = None,
    *,
    small_track: bool = False,
) -> float:
    """按主力引擎置信度在「常规档 / 极端档」之间裁决单票仓位上限，并对左尾风险腰斩。"""
    halved_cap = config.MAX_SINGLE_POSITION / 2.0  # 腰斩档 = 10%

    if small_track:
        base = mf_cap if mf_cap is not None else halved_cap * 0.8
        cap = min(halved_cap, base)
    elif (
        mf_cap is not None
        and mf_cap >= config.POSITION_EXTREME_MIN_STAGE_CAP
        and (mf_confidence or 0.0) >= config.POSITION_EXTREME_MIN_CONFIDENCE
    ):
        cap = config.MAX_SINGLE_POSITION_EXTREME
    else:
        base = mf_cap if mf_cap is not None else config.MAX_SINGLE_POSITION
        cap = min(config.MAX_SINGLE_POSITION, base)

    # 左尾腰斩
    if left_tail_depth_pct is not None and left_tail_depth_pct / 100.0 > config.LEFT_TAIL_WARN_THRESHOLD:
        cap = min(cap, halved_cap)

    return round(max(0.0, cap), 6)


def cap_of_gear(
    decision_gear: str,
    mf_cap: float | None,
    mf_confidence: float | None,
    left_tail_depth_pct: float | None = None,
    *,
    is_micro_degraded: bool = False,
    ni_is_verified: bool = True,
) -> float:
    """档位 → 仓位上限的**唯一**映射。

    ★ 20261029 审计 P0-2：AI 节点（或任何后续逻辑）一旦改动 `decision_gear`，
      必须**按新档位重算** `position_cap`。此前档位被覆写而仓位沿用旧值，
      真实产物出现「档位: 期权仓(小) + 仓位 0%」这种自相矛盾的指令
      （reports/002273_SZ_20261029.html）。档位与仓位从此同源，不再各算各的。

    ★ 除「核心仓 / 期权仓(小)」外一律 0 仓位 —— 观察/不追高/减仓/回避都是
      「不建议下注」的档位，给它们非零仓位等于把「好下注? 【否】」的三分结论
      写成假的。
    """
    if decision_gear == "核心仓":
        if is_micro_degraded or mf_cap == 0.0 or not ni_is_verified:
            return 0.0
        return resolve_position_cap(mf_cap, mf_confidence, left_tail_depth_pct)
    if decision_gear == "期权仓(小)":
        if is_micro_degraded or mf_cap == 0.0:
            return 0.0
        return resolve_position_cap(
            mf_cap, mf_confidence, left_tail_depth_pct, small_track=True
        )
    return 0.0


def build_pillar_5_decision(
    ctx: SingleStockContext,
    q_verdict: QualityVerdict,
    s_verdict: StateVerdict,
    o_verdict: OddsVerdict,
    p_verdict: PathVerdict,
    stock_track: str,
    is_market_ice: bool,
    macro_res: Any | None,
    ret_10d: float,
    is_gem_star: bool,
    is_bse: bool,
    overhead_chips: float,
    ma5: float,
    ma20: float,
    support_lvl: float,
    resistance_lvl: float,
    nodes: dict[str, Any] | None = None,
) -> DecisionVerdict:
    """支柱 ❺: 纯函数决策策略表：映射买方行动档位、建议仓位与执行战术。"""
    price = ctx.quote.get("close", 0.0)
    state_verdict = s_verdict.verdict
    odds_verdict = o_verdict.verdict
    path_verdict = p_verdict.verdict
    quality_verdict = q_verdict.verdict
    is_fatal = q_verdict.is_fatal
    fatal_flags = q_verdict.fatal_flags

    mf_stage_code = p_verdict.mf_stage_code
    mf_override = p_verdict.mf_override
    is_micro_degraded = p_verdict.is_micro_degraded
    mf_cap = p_verdict.mf_cap
    mf_confidence = p_verdict.mf_conf
    left_tail_depth_pct = abs(p_verdict.depth_to_sotp) if (p_verdict.depth_to_sotp is not None and p_verdict.depth_to_sotp < 0) else None
    ni_is_verified = o_verdict.ni_is_verified
    sotp_ps = o_verdict.sotp_ps or 0.0
    dcf_ps = o_verdict.dcf_ps or 0.0
    critical_wait = s_verdict.critical_wait
    ladder_info = ctx.ladder_info
    microstructure = ctx.microstructure

    margin_100 = round(max(0.0, 100.0 - ret_10d), 1)
    board_cap_pct = 20.0 if is_gem_star else (30.0 if is_bse else 10.0)
    boards_to_limit = max(0, int(margin_100 / board_cap_pct))

    if ret_10d >= 70.0:
        reg_status_str = f"近10日涨幅 {ret_10d:+.1f}%，距10日100%严重异动停牌红线仅剩 {margin_100:.1f}% (约 {boards_to_limit} 板触及监控/停牌核查，监管高压)"
    elif ret_10d > 0.0:
        reg_status_str = f"近10日涨幅 {ret_10d:+.1f}%，距严重异动监管红线(+100%)尚余 {margin_100:.1f}% 空间 (监管余量充足，连板具备妖股通行证)"
    else:
        reg_status_str = "距严重异常波动监管红线(10日100%)余量充沛"

    # ★ 20261029 审计 P1-7：原 ``life_line = price * 0.98`` 是**不可执行的指令** ——
    #   文案写的是「以昨日收盘价为日内生命线」，实际给的却是"当前价的 98%"：
    #   盘中压根不存在这个价位，执行者照做只会挂出一个永远不成交/乱成交的单。
    #   现取真实前收盘 ``pre_close``（quote 里有）；取不到就如实标注未核验，
    #   绝不用现价折算冒充"昨收"（NFR-02：缺失≠可以造一个）。
    _pre_close = float(ctx.quote.get("pre_close") or 0.0)
    life_line = round(_pre_close, 2) if _pre_close > 0 else None
    life_line_desc = f"{life_line:.2f}元" if life_line is not None else "未核验(前收盘价缺失)"
    stop_line = round(min(support_lvl, price * 0.96), 2)

    if is_fatal:
        decision_gear = "回避"
        decision_title = "【🚫 铁律回避】"
        position_cap = 0.0
        core_contra = f"触发买方一票否决致命红旗: {fatal_flags[0].title}。常态化监管与退市铁律下，本金安全高于一切！"
        action_tactic = (
            "• 持币者 (空仓严禁买入): 盘中无论任何脉冲反抽均为诱多陷阱，坚决一股不买！\n"
            f"  • 持股者 (即刻清仓离场): 触及买方合规死锁线，次日开盘以市价无条件止损止盈离场，绝不心存侥幸！{DISCLAIMER_LIMIT_DOWN}"
        )
        invalidation = "一票否决绝对生效，禁止建仓！"
    elif is_market_ice and stock_track in TRACK_DEFENSIVE_ON_ICE:
        decision_gear = "观察"
        decision_title = (
            "【👀 情绪防守 (弱市高危·物种未核验)】"
            if stock_track == TRACK_UNVERIFIED
            else "【👀 情绪防守 (弱市逆势接力高危)】"
        )
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
            f"  • 持股者 (持股守利): 弱市环境下存量抱团随时面临大盘拖累下的补跌补刀；次日早盘 9:25 竞价若低开低于昨日收盘价或竞价量能萎缩，开盘即刻市价止盈离场；盘中一旦开板放量且换手率超过 12%，无条件清仓锁定利润！{DISCLAIMER_LIMIT_DOWN}"
        )
        invalidation = f"以昨日收盘价 ({life_line_desc}) 为日内生命线/防线，开盘破位 3 分钟不回立刻清仓止损，绝不参与转跌后的天地板博傻！"
    elif path_verdict == "高尾险·不可承受" and mf_stage_code in ("STAGE_6_DISTRIBUTION", "STAGE_7_PASSIVE_DRIFT"):
        micro_d = microstructure or {}
        s_buy = float(micro_d.get("smart_buy_ratio") or 50.0)
        s_sell = float(micro_d.get("smart_sell_ratio") or 50.0)
        is_distribution = mf_stage_code == "STAGE_6_DISTRIBUTION"

        if is_distribution:
            decision_title = "【⚠️ 派发出货防守】"
            stage_word = "对倒派发出货期"
        else:
            decision_title = "【📉 阴跌出清防守】"
            stage_word = "无抵抗阴跌出清期"

        decision_gear = "回避"
        position_cap = 0.0

        if s_sell > s_buy:
            flow_word = f"微观卖盘 {s_sell:.1f}% 压过买盘 {s_buy:.1f}%，筹码呈无抵抗流失"
        else:
            flow_word = (
                f"但微观买盘 {s_buy:.1f}% 仍高于卖盘 {s_sell:.1f}%，尚存承接迹象 —— "
                f"这与「{stage_word}」的定性存在张力，须以次日数据复核确认"
            )
        core_contra = (
            f"主力处于{stage_word}：上方套牢量占比 {overhead_chips:.1f}%（60日量能代理口径）沉重，{flow_word}，"
            f"左侧盲目接飞刀盈亏比恶化。"
        )
        conf = float(mf_confidence or 0.0)
        if conf < 70.0:
            action_tactic = (
                f"• 持币者 (暂缓介入·待确认): 本判定置信度仅 {conf:.1f}%（多空过渡区），"
                f"资金面尚未形成一致方向，建议等待次日确认，不宜据此执行刚性清仓。\n"
                f"  • 持股者 (控制风险·分批减): 可在反抽时分批降低仓位，"
                f"不必因单日切片信号一次性清空。"
            )
        else:
            action_tactic = (
                "• 持币者 (坚决回避): 盘中反抽长上影线为出货假象，坚决一股不买！\n"
                f"  • 持股者 (逢反抽清仓): 趁盘中反抽脉冲果断挂市价单清仓出局，严防阴跌扩大亏损。{DISCLAIMER_LIMIT_DOWN}"
            )
        invalidation = f"跌破防守线 {stop_line:.2f} 元坚决离场，不参与任何左侧盲目猜底！"
    elif odds_verdict == "买完完美未来" and path_verdict == "高尾险·不可承受":
        decision_gear = "减仓"
        decision_title = "【📉 估值与路径双高危 (减仓避险)】"
        position_cap = 0.0
        core_contra = f"现价估值已买完未来 5 年完美成长预期，且上方套牢阻力沉重 ({overhead_chips:.1f}%)，赔率与路径双向承压。"
        action_tactic = (
            f"• 持币者 (耐心等待): 严禁追高，耐心等待估值回踩至 SOTP 锚底座 ({sotp_ps:.2f}元) 企稳再做评估。\n"
            "  • 持股者 (逢高减仓): 趁当前价格尚在高位，逢盘中高点分批兑现锁定利润。"
        )
        invalidation = f"跌破分时生命线 {life_line_desc} 无条件清仓止损！"
    elif state_verdict == "↑变好+证据确认" and odds_verdict in ("便宜(有余地)", "合理") and path_verdict == "可承受":
        decision_gear = "核心仓"
        decision_title = "【🔥 核心做多 (高确信重击)】"
        if is_micro_degraded or mf_cap == 0.0 or not ni_is_verified:
            position_cap = 0.0
            decision_gear = "等证据临界(观察)"
            decision_title = "【👀 等待微观/估值核验 (观察)】"
        else:
            position_cap = resolve_position_cap(
                mf_cap, mf_confidence, left_tail_depth_pct
            )
        core_contra = "基本面在变好且经报表实锤确认，估值具有充分安全垫，主力处于建仓拉升主升通道，路径可承受性优良。"
        action_tactic = (
            f"• 持币者 (分时低吸/竞价跟进): 早盘 9:25 竞价若高开 1%~3% 且量比>1.8 顺势建仓，或开盘回踩分时均线企稳分批买入。\n"
            f"  • 持股者 (顺势持股守利): 均线多头排列良好，依托 10 日均线波段持股，未见高位放量长上影滞涨前坚定持仓。"
        )
        invalidation = f"严格执行 A 股 T+1 纪律：次日收盘跌破趋势防守线 {ma20:.2f} 元无条件减半仓，跌破 {stop_line:.2f} 元止损离场！"
    elif state_verdict == "↑变好但仅注意力·未确认" and ladder_info and ladder_info.get("board_level", 0) >= 2:
        decision_gear = "期权仓(小)"
        decision_title = "【⚡ 题材接力 (轻仓试错博弈)】"
        if is_micro_degraded or mf_cap == 0.0:
            position_cap = 0.0
            decision_gear = "等证据临界(观察)"
            decision_title = "【👀 等待微观核验 (观察)】"
        else:
            position_cap = resolve_position_cap(
                mf_cap, mf_confidence, left_tail_depth_pct, small_track=True
            )
        core_contra = f"短线题材高度聚焦 (梯队 {ladder_info.get('board_level',0)}板)，右尾爆发力大但产业实锤未确认，属典型事件注意力博弈。"
        action_tactic = (
            f"• 持币者 (早盘竞价决断): 次日早盘 9:25 竞价成交量需达昨日全天 15% 以上且高开>2%，方可打板或小仓位跟进；若低开坚决放弃！\n"
            f"  • 持股者 (板上锁仓/炸板坚决走): 封死涨停则持股不动；盘中一旦炸板放量且换手率超 15%，开板即刻市价兑现清仓，严防天地板！{DISCLAIMER_LIMIT_DOWN}"
        )
        invalidation = f"以昨日收盘价 ({life_line_desc}) 为日内生命线/防线，开盘破位 3 分钟不回立刻清仓止损，绝不在短线妖股博傻中死扛！"
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
        holding_def_default = (
            f"依托关键防守支撑线 {support_lvl:.2f} 元持有；破位收不回减仓规避钝刀子磨损。"
            if abs(support_lvl - stop_line) < 0.1
            else f"以 20 日线 ({ma20:.2f}元) 为第一预警线，强支撑线 {support_lvl:.2f} 元为最终防守线持有；破位减仓规避钝刀子磨损。"
        )
        action_tactic = (
            f"• 持币者 (耐心观察): 现金是等待的最佳期权，在催化剂实锤披露或放量突破近端压力位 {resistance_lvl:.2f} 元前坚决持币。\n"
            f"  • 持股者 (控制回撤): {holding_def_default}"
        )
        invalidation = f"跌破强支撑线 {support_lvl:.2f} 元剔除出跟踪池。"

    # AI 节点模型推导
    if nodes:
        _node = nodes.get("node_decision")
        _nv = getattr(_node, "verdict", None) if _node else None
        if _nv and not is_fatal:
            # ★ 20261029 审计 P0-2：原为裸覆写 ``decision_gear = _nv`` ——
            #   ① AI 可以把「回避」抬成「期权仓(小)」（升级后门）；
            #   ② 覆写后不重算 position_cap，导致「档位: 期权仓(小) + 仓位: 0%」。
            #   现走降级单向阀（只能变保守），且档位一变就按新档位重算仓位。
            from core.ai_coprocessor import apply_verdict_downgrade_only as _apply_verdict
            _guarded = _apply_verdict(decision_gear, _node, "node_decision")
            if _guarded != decision_gear:
                decision_gear = _guarded
                decision_title = f"【🤖 大模型裁定 · {_guarded}】"
                position_cap = cap_of_gear(
                    _guarded, mf_cap, mf_confidence, left_tail_depth_pct,
                    is_micro_degraded=is_micro_degraded, ni_is_verified=ni_is_verified,
                )
                ai_judgment = getattr(_node, "judgment", "")
                if ai_judgment and isinstance(ai_judgment, str) and ai_judgment.strip():
                    from presentation.plain_language import smart_natural_cutoff
                    core_contra = f"大模型裁定需等证据核销落袋：{smart_natural_cutoff(ai_judgment.strip(), max_chars=220)}"

                if position_cap == 0.0:
                    if _guarded in ("等证据临界(观察)", "观察"):
                        holding_desc = (
                            f"依托关键防守支撑线 {support_lvl:.2f} 元防守持有；盘中若有效破位则启动保护性减仓止损，规避钝刀子磨损。"
                            if abs(support_lvl - stop_line) < 0.1
                            else f"依托 20 日均线 ({ma20:.2f}元) 与强支撑线 {support_lvl:.2f} 元分级防守持有；盘中若破位则减仓止损，规避钝刀子磨损。"
                        )
                        action_tactic = (
                            f"• 持币者 (空仓观望·等待右侧突破): 暂不建仓开新仓。建议加入自选跟踪池，在下一期财报/订单实锤落地前，或放量突破近端压力位 {resistance_lvl:.2f} 元前坚决持币，不盲目左侧接飞刀。\n"
                            f"  • 持股者 (防守设盈·依托均线): {holding_desc}"
                        )
                    elif _guarded in ("回避", "减仓"):
                        action_tactic = (
                            f"• 持币者 (空仓回避): 触发风控降级，坚决一股不买！\n"
                            f"  • 持股者 (逢反抽清仓): 趁盘中反抽脉冲果断减仓出局，跌破防守线 {stop_line:.2f} 元立刻清仓止损。{DISCLAIMER_LIMIT_DOWN}"
                        )

        _pa = nodes.get("node_path")
        _analysis = getattr(_pa, "analysis", None) or {}
        _fal = _analysis.get("falsification") if isinstance(_analysis, dict) else None
        if isinstance(_fal, str) and _fal.strip():
            invalidation = _fal.strip()

    # 主力阶段硬核死锁重载
    if mf_override and not is_fatal:
        decision_gear = mf_override
        # ★ 与 AI 覆写同理：档位改了，仓位必须按新档位重算（P0-2）
        position_cap = cap_of_gear(
            mf_override, mf_cap, mf_confidence, left_tail_depth_pct,
            is_micro_degraded=is_micro_degraded, ni_is_verified=ni_is_verified,
        )

    # 龙虎榜量化砸盘提示性文字预警 (提示性预警不阻断)
    has_dump_risk, dump_warning = evaluate_lhb_dump_risk(ctx.matched_youzi or ctx.lhb_records)
    if has_dump_risk and dump_warning:
        action_tactic += f"\n  • ⚡ {dump_warning}"

    # 买方战术下注点位与盈亏比卡 (Tactical Odds)
    risk_pct = round(max(0.1, (price - stop_line) / price * 100), 1) if price > 0 else 0.0
    reward_target = dcf_ps if (dcf_ps and dcf_ps > price) else resistance_lvl
    if reward_target <= price:
        reward_target = round(price * 1.15, 2)
    reward_pct = round(max(0.1, (reward_target - price) / price * 100), 1) if price > 0 else 0.0
    odds_ratio = round(reward_pct / max(risk_pct, 0.5), 2) if risk_pct > 0 else 0.0

    if decision_gear in DECISION_GEAR_AVOID or position_cap <= 0.0:
        tactical_odds = {
            "is_circuit_broken": True,
            "circuit_breaker_reason": f"当前定调为【{decision_gear}】(仓位上限 {int(position_cap*100)}%)，触发买方防御熔断，禁止设定买入区间与向上目标价",
            "entry_range": "禁止买入 (买方防守熔断)",
            "stop_loss": f"{stop_line:.2f}元 (-{risk_pct:.1f}%)" if stop_line > 0 else "无",
            "target_price": "无 (回避档位不设目标价)",
            "risk_reward_ratio": "0.00:1 (盈亏比关闭)",
            "key_support": f"{support_lvl:.2f}元" if support_lvl > 0 else "无",
            "key_resistance": f"{resistance_lvl:.2f}元" if resistance_lvl > 0 else "无",
            "stop_price": stop_line,
        }
    else:
        tactical_odds = {
            "entry_range": f"{support_lvl:.2f} ~ {price:.2f}元",
            "stop_loss": f"{stop_line:.2f}元 (-{risk_pct:.1f}%)",
            "target_price": f"{reward_target:.2f}元 (+{reward_pct:.1f}%)",
            "risk_reward_ratio": f"{odds_ratio:.2f}:1",
            "key_support": f"{support_lvl:.2f}元",
            "key_resistance": f"{resistance_lvl:.2f}元",
            "stop_price": stop_line,
        }

    return DecisionVerdict(
        decision_gear=decision_gear,
        decision_title=decision_title,
        position_cap=position_cap,
        core_contradiction=core_contra,
        action_tactic=action_tactic,
        invalidation_line=invalidation,
        regulatory_status=reg_status_str,
        three_part_conclusion=format_three_part_conclusion(quality_verdict, position_cap, odds_verdict),
        triad_verdict=f"[{state_verdict} | {odds_verdict} | {path_verdict}]",
        dump_warning=dump_warning if has_dump_risk else None,
        tactical_odds=tactical_odds,
    )
