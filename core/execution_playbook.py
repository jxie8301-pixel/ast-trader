"""实盘级短线交易执行剧本与战术卡生成器 (严格对齐 UZI-Skill execution.py)."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import config
from .youzi_personas import SEATS

logger = logging.getLogger("ast_trader.playbook")


def _dump_risk_personas(matched_personas: list[str] | None) -> list[str]:
    """从命中的游资名称中筛出具备「次日砸盘 / 一日游 / 散户拥挤」属性的席位 (E-4)。

    `matched_personas` 此前被 `build()` 声明却从未使用 —— 调用方传入的游资名单被静默丢弃。
    这里按 `youzi_personas.SEATS` 的 `style` 做属性判定，把名单转化为可执行的防砸纪律。
    """
    hits: list[str] = []
    for name in matched_personas or []:
        info = SEATS.get(name)
        if not info:
            continue
        style = str(info.get("style") or "")
        if any(k in style for k in config.PLAYBOOK_DUMP_RISK_STYLE_KEYWORDS):
            hits.append(name)
    return hits


DISCLAIMER_LIMIT_DOWN = "（⚠️ 提示: 若遇一字跌停等流动性锁死极端行情，市价单将无法成交，须挂跌停价排队等待撮合，实际损失可能超出计划）"


@dataclass
class ExecutionPlaybook:
    # BUY 主升做多 / WAIT 观望确认 / AUCTION 次日竞价条件单 / REDUCE 冲高减仓 / AVOID 铁律回避
    action: str
    action_label: str               # 简明行动标签
    entry_tactic: str               # 具体买入战术 (竞价低吸/分时均线低吸/突破半路/封板确认)
    entry_price_range: str          # 建议挂单参考价区间
    base_position_pct: int          # 首仓基准比例 (%)
    add_position_pct: int           # 盘中加仓比例 (%)
    max_position_pct: int           # 单票封顶仓位上限 (%)
    take_profit_target: str         # 动态止盈目标位与策略
    stop_loss_line: str             # 移动止损线
    invalidation_rule: str          # 铁律死锁退出失效线
    # ★ AI 情景研判（默认空串）。刻意**不覆盖** entry_tactic：后者含具体挂单价位，
    #   而 AI 被明令禁止输出任何价格（见 prompts/tactic.md），整体替换会把
    #   价格单点真理抹掉。AI 关闭时恒为空串，输出与历史逐字一致。
    scenario_note: str = ""


#: 由**微观资金面**触发熔断的两档主力阶段。处于这两档时，`suggested_pos_cap=0.0`
#: 会一路传导成「坚决一股不买 / 次日无条件离场」的刚性指令。
DISTRIBUTION_STAGES: tuple[str, ...] = ("STAGE_6_DISTRIBUTION", "STAGE_7_PASSIVE_DRIFT")


def reversal_invalidation_suffix(main_force_stage: str | None) -> str:
    """F-10：为资金面触发的刚性指令追加**反转失效条件**。

    ★ 缺口：``build()`` 此前不接收 ``main_force_stage``，指令与产生它的那个
      微观信号之间**没有数据耦合**，因此不可能表达"若次日资金面反转则本指令
      作废"。全部退出线都是价格/量触发，没有一条以主力阶段反转为条件。

      后果（第三方评审）：报告把一个阶段性状态当成持续趋势，用「不可承受」
      的定性关闭了修正的可能性 —— 10 月 28 日科达利放量主力净流入，
      而报告仍挂着"坚决回避"。

    ★ 语义边界：本函数**只放宽时效描述，不削弱否决强度**。
      财务红旗（``fatal_flag``）触发的否决**不调用**本函数，仍为绝对禁令。
    """
    if main_force_stage in DISTRIBUTION_STAGES:
        return (
            "；⏱️ 但本指令由**当日盘中**派发/阴跌切片触发，仅对当日有效 —— "
            "若次日主力阶段退出派发区且资金转为净流入，本指令即告作废，须重新评估，严禁跨日沿用"
        )
    return ""


class PlaybookBuilder:
    """根据标的形态、梯队地位、游资画像与盘口特征生成实操执行手册。"""

    def build(
        self,
        quote: dict[str, Any],
        momentum: dict[str, Any],
        matched_personas: list[str],
        action: str,
        ladder_info: dict[str, Any] | None = None,
        fatal_flag: bool = False,
        position_cap: float | None = None,
        ai: dict[str, Any] | None = None,
        main_force_stage: str | None = None,
    ) -> ExecutionPlaybook:
        """``main_force_stage`` 供 F-10 指令失效机制使用：

        刚性指令（AVOID / REDUCE）若是由**微观资金面**（派发期 / 阴跌出清期）
        触发的，须附带反转失效条件 —— 该信号是日内切片，次日资金面反转时
        本指令即应作废。由财务红旗（``fatal_flag``）触发的否决**不受影响**，
        仍然绝对有效。
        """
        """生成执行剧本，并在 AI 启用时**追加**情景研判。

        ★ `ai` 只影响 `scenario_note`，绝不触碰 `entry_tactic` / 价格 / 仓位 ——
          那些是量化中台的领域，AI 无数值权限。AI 关闭时 `scenario_note`
          恒为空串，输出与历史逐字一致。
        """
        playbook = self._build_core(
            quote=quote,
            momentum=momentum,
            matched_personas=matched_personas,
            action=action,
            ladder_info=ladder_info,
            fatal_flag=fatal_flag,
            position_cap=position_cap,
            main_force_stage=main_force_stage,
        )
        if ai:
            try:
                from core.ai_coprocessor import apply_text

                playbook.scenario_note = apply_text("", ai.get("tactic"))
            except Exception as exc:                        # noqa: BLE001
                logger.warning("AI 情景研判并入失败（已忽略）: %s", exc)
        return playbook

    def _build_core(
        self,
        quote: dict[str, Any],
        momentum: dict[str, Any],
        matched_personas: list[str],
        action: str,
        ladder_info: dict[str, Any] | None = None,
        fatal_flag: bool = False,
        position_cap: float | None = None,
        main_force_stage: str | None = None,
    ) -> ExecutionPlaybook:
        """生成执行剧本。

        Args:
            position_cap: 决断卡裁定的单票仓位上限（**小数**，如 0.20）。
                传入时剧本仓位配比由它换算，确保剧本与卡面单点真理一致；
                为 ``None``（遗留调用方与单测）时回退到 ``config.MAX_SINGLE_POSITION``。
                无论何种来源，最终都受双档上限封顶。
        """
        close = quote.get("close", 0.0)
        pre_close = quote.get("pre_close", close)
        support = momentum.get("support_level", round(close * 0.95, 2))
        resistance = momentum.get("resistance_level", round(close * 1.05, 2))
        is_leader = ladder_info.get("is_leader", False) if ladder_info else False
        board_level = ladder_info.get("board_level", 1) if ladder_info else 1

        if fatal_flag or action == "AVOID":
            # F-10：财务红旗导致的否决是**永久性**的（与资金面无关），不加时效条件；
            # 仅由微观派发/阴跌切片导致的回避才附反转失效条件。
            reversal = "" if fatal_flag else reversal_invalidation_suffix(main_force_stage)
            return ExecutionPlaybook(
                action="AVOID",
                action_label="🚫 铁律回避 (禁止开仓)",
                entry_tactic="触发买方风控回避或一票否决红线，严禁任何形式的买入与抄底",
                entry_price_range="无 (零仓位防守不设买入区间)",
                base_position_pct=0,
                add_position_pct=0,
                max_position_pct=0,
                take_profit_target="若有持仓立即挂跌停板竞价出局",
                stop_loss_line="立即止损，不留幻想",
                invalidation_rule="一票否决生效：无论盘中如何拉升，坚决不参与" + reversal,
            )

        if action == "BUY":
            # E-1: 单票仓位上限统一由决断卡裁定值换算，并受双档上限封顶。
            # 剧本不再出现裸数字 25%，杜绝"剧本 25% / 卡面 20% / config 20%" 三处不一致。
            cap = position_cap if position_cap is not None else config.MAX_SINGLE_POSITION
            cap = min(max(0.0, float(cap)), config.MAX_SINGLE_POSITION_EXTREME)
            if not (is_leader or board_level >= 2):
                cap *= config.PLAYBOOK_NON_LEADER_CAP_RATIO
            max_pos = int(round(cap * 100))
            base_pos = int(round(max_pos * config.PLAYBOOK_BASE_POSITION_RATIO))
            add_pos = max_pos - base_pos

            if is_leader or board_level >= 2:
                tactic = "【龙头加速打板/早盘弱转强】9:25 竞价小幅高开 2%~4% 且量比>2 挂涨停价抢筹，或分时首封板瞬间打板确认"
                entry_range = f"{round(close * 0.99, 2)} ~ {round(close * 1.03, 2)} 元"
            else:
                tactic = "【分时均线(VWAP)回踩低吸】开盘回踩日均线不破企稳时挂单介入，严禁冲高追涨"
                entry_range = f"{round(close * 0.97, 2)} ~ {round(close * 0.99, 2)} 元"

            tp_target = f"首目标压力位 {resistance} 元 (分批止盈 50%)，余仓移动止盈跟随至跌破 5 日线"
            sl_line = f"跌破分时均线(VWAP)或下方强支撑 {support} 元"
            invalid_rule = f"死锁退出线 (严守 A 股 T+1 纪律): 建仓日不可卖出；次日开盘若低开直接跌破支撑 {support} 元或反抽不过分时均线超 15 分钟，坚决市价止损出局，严禁违背纪律死扛{DISCLAIMER_LIMIT_DOWN}"

            # E-4: 席位属性落地为防砸纪律 —— 挂单区间整体下移、禁止 9:25 抢筹、收紧退出
            dump_risk = _dump_risk_personas(matched_personas)
            if dump_risk:
                if is_leader or board_level >= 2:
                    entry_range = f"{round(close * 0.975, 2)} ~ {round(close * 1.005, 2)} 元"
                else:
                    entry_range = f"{round(close * 0.955, 2)} ~ {round(close * 0.975, 2)} 元"
                tactic = (
                    f"⚠️ 命中砸盘属性席位（{'、'.join(dump_risk[:2])}）："
                    f"严禁 9:25 高开抢筹，仅在回踩区间低吸，"
                ) + tactic
                sl_line = f"防砸纪律：跌破分时均线(VWAP) 或 {support} 元即刻减半仓，不等收盘确认"
                invalid_rule = (
                    "防砸退出线: 次日竞价低开或 9:35 前出现大额抛压，立即市价止损出局，"
                    "绝不在砸盘属性席位主导的标的上恋战；"
                ) + invalid_rule

            return ExecutionPlaybook(
                action="BUY",
                action_label="🔥 主升做多 (分批布局)",
                entry_tactic=tactic,
                entry_price_range=entry_range,
                base_position_pct=base_pos,
                add_position_pct=add_pos,
                max_position_pct=max_pos,
                take_profit_target=tp_target,
                stop_loss_line=sl_line,
                invalidation_rule=invalid_rule,
            )

        if action == "WAIT":
            pct_chg = quote.get("pct_chg", 0.0)
            is_zero_cap = position_cap is not None and float(position_cap) <= 0.0
            if is_zero_cap:
                wait_tactic = "【零仓位防御】当前处于买方风控防守或证据匮乏期，仓位上限锁定为 0%，坚决不伸手建仓"
                entry_range = "无 (零仓位防守不设买入区间)"
                base_pos = 0
                add_pos = 0
                max_pos = 0
                action_lbl = "👀 观望防御 (仓位锁定 0%)"
                tp_tgt = "无持仓 / 保持空仓"
                inv_rule = "风控死锁防线: 维持零仓位防守，未见增量放量与基本面反转前严禁建仓"
            else:
                max_pos = int(round(float(position_cap) * 100)) if position_cap is not None else 15
                base_pos = 0
                add_pos = max_pos
                entry_range = f"观望区间: {support} ~ {close} 元"
                action_lbl = "👀 观望确认 (等待临界点)"
                tp_tgt = "待弱转强确认后再设止盈目标"
                inv_rule = "死锁退出线: 若次日早盘直接低开低走跌破昨日最低点，坚决放弃该标的交易机会"
                if pct_chg < 0:
                    wait_tactic = "【破位/分歧观察】标的处于日线空头或破位调整中，次日早盘必须观察是否缩量企稳并形成反包弱转强，未确认企稳前严禁伸手抄底"
                elif pct_chg >= 5.0:
                    wait_tactic = "【冲高回踩观察】短线涨幅偏大，防高位追高被套，等待分时均线回踩企稳获得承接后再行介入"
                else:
                    wait_tactic = "【筹码分歧观察】多空处于存量震荡博弈中，次日早盘观察是否有增量大单打破平衡"

            return ExecutionPlaybook(
                action="WAIT",
                action_label=action_lbl,
                entry_tactic=wait_tactic,
                entry_price_range=entry_range,
                base_position_pct=base_pos,
                add_position_pct=add_pos,
                max_position_pct=max_pos,
                take_profit_target=tp_tgt,
                stop_loss_line=f"下破 {support} 元彻底破坏形态",
                invalidation_rule=inv_rule,
            )

        if action == "AUCTION":
            # ★ 解开「首板死锁」的第五态。
            #   盘后选股是为次日（T+1）做预案，首板当日涨停是**客观事实**，
            #   不能因为"涨停=日内涨幅过大"就把次日仓位直接清零 —— 那会让系统
            #   变成"辛辛苦苦选出涨停板，然后宣布一口都不能吃"的看戏器。
            #   正确做法：当日不建仓（base=0），把决策权交给次日 9:25 可被客观
            #   验证的竞价条件；满足才建试错仓，不满足即废单。
            open_pct = config.AUCTION_MIN_OPEN_PCT
            vol_ratio_pct = config.AUCTION_MIN_VOLUME_RATIO * 100
            trial = int(round(config.AUCTION_TRIAL_POSITION_PCT * 100))

            return ExecutionPlaybook(
                action="AUCTION",
                action_label="⏳ 次日竞价确认 (条件单)",
                entry_tactic=(
                    f"【次日 9:25 弱转强竞价确认】今日已封板，次日不追高、不打板；"
                    f"仅在 ①高开 ≥ {open_pct:.1f}% 且 ②竞价成交量 ≥ 昨日全天成交量的 "
                    f"{vol_ratio_pct:.0f}% 两个条件**同时满足**时，于 9:30 开盘后挂单介入；"
                    f"平开或低开一律废单，当日绝不参与"
                ),
                entry_price_range=f"竞价确认后挂单区间: {round(close * 0.99, 2)} ~ {round(close * 1.03, 2)} 元",
                base_position_pct=0,          # 当日绝不建仓
                add_position_pct=trial,       # 竞价条件满足后的试错仓
                max_position_pct=trial,
                take_profit_target=f"首目标压力位 {resistance} 元 (分批止盈 50%)，余仓跌破 5 日线离场",
                stop_loss_line=f"跌破分时均线(VWAP)或下方强支撑 {support} 元",
                invalidation_rule=(
                    f"竞价废单线: 次日 9:25 高开 < {open_pct:.1f}% 或竞价量 < 昨日全天 "
                    f"{vol_ratio_pct:.0f}% 即放弃本次机会，严禁在条件不满足时临时改判追高；"
                    f"已建仓则严守 T+1 纪律，次日低开跌破 {support} 元市价止损出局{DISCLAIMER_LIMIT_DOWN}"
                ),
            )

        # REDUCE
        return ExecutionPlaybook(
            action="REDUCE",
            action_label="⚠️ 冲高减仓 (分歧落袋)",
            entry_tactic="【高位减持】筹码松动或主力大单流出，只减不买，利用早盘冲高逢高派发",
            entry_price_range=f"派发区间: {round(close * 1.01, 2)} ~ {resistance} 元",
            base_position_pct=0,
            add_position_pct=0,
            max_position_pct=0,
            take_profit_target=f"趁盘中脉冲快速落袋为安，保护浮盈",
            stop_loss_line=f"破 5 日线即刻清仓",
            invalidation_rule="放量滞涨即为减仓信号，严禁反向加仓"
            + reversal_invalidation_suffix(main_force_stage),
        )
