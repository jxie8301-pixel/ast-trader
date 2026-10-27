"""实盘级短线交易执行剧本与战术卡生成器 (严格对齐 UZI-Skill execution.py)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class ExecutionPlaybook:
    action: str                     # BUY (主升做多), WAIT (等待确认), REDUCE (冲高减仓), AVOID (铁律回避)
    action_label: str               # 简明行动标签
    entry_tactic: str               # 具体买入战术 (竞价低吸/分时均线低吸/突破半路/封板确认)
    entry_price_range: str          # 建议挂单参考价区间
    base_position_pct: int          # 首仓基准比例 (%)
    add_position_pct: int           # 盘中加仓比例 (%)
    max_position_pct: int           # 单票封顶仓位上限 (%)
    take_profit_target: str         # 动态止盈目标位与策略
    stop_loss_line: str             # 移动止损线
    invalidation_rule: str          # 铁律死锁退出失效线


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
    ) -> ExecutionPlaybook:
        close = quote.get("close", 0.0)
        pre_close = quote.get("pre_close", close)
        support = momentum.get("support_level", round(close * 0.95, 2))
        resistance = momentum.get("resistance_level", round(close * 1.05, 2))
        is_leader = ladder_info.get("is_leader", False) if ladder_info else False
        board_level = ladder_info.get("board_level", 1) if ladder_info else 1

        if fatal_flag or action == "AVOID":
            return ExecutionPlaybook(
                action="AVOID",
                action_label="🚫 铁律回避 (禁止开仓)",
                entry_tactic="触发财务审计红旗或破位杀猪特征，严禁任何形式的买入与抄底",
                entry_price_range="N/A",
                base_position_pct=0,
                add_position_pct=0,
                max_position_pct=0,
                take_profit_target="若有持仓立即挂跌停板竞价出局",
                stop_loss_line="立即止损，不留幻想",
                invalidation_rule="一票否决生效：无论盘中如何拉升，坚决不参与",
            )

        if action == "BUY":
            if is_leader or board_level >= 2:
                tactic = "【龙头加速打板/早盘弱转强】9:25 竞价小幅高开 2%~4% 且量比>2 挂涨停价抢筹，或分时首封板瞬间打板确认"
                entry_range = f"{round(close * 0.99, 2)} ~ {round(close * 1.03, 2)} 元"
                base_pos = 15
                add_pos = 10
                max_pos = 25
            else:
                tactic = "【分时均线(VWAP)回踩低吸】开盘回踩日均线不破企稳时挂单介入，严禁冲高追涨"
                entry_range = f"{round(close * 0.97, 2)} ~ {round(close * 0.99, 2)} 元"
                base_pos = 10
                add_pos = 10
                max_pos = 20

            tp_target = f"首目标压力位 {resistance} 元 (分批止盈 50%)，余仓移动止盈跟随至跌破 5 日线"
            sl_line = f"跌破分时均线(VWAP)或下方强支撑 {support} 元"
            invalid_rule = f"死锁退出线: 买入后分时跌破均线超 15 分钟未收回，或跌幅达 -3.5%，坚决市价止损出局"

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
            return ExecutionPlaybook(
                action="WAIT",
                action_label="👀 观望确认 (等待临界点)",
                entry_tactic="【筹码分歧观察】今日存在炸板或放量分歧，次日早盘必须观察是否缩量弱转强，未确认前禁止伸手",
                entry_price_range=f"观望区间: {support} ~ {close} 元",
                base_position_pct=0,
                add_position_pct=10,
                max_position_pct=15,
                take_profit_target="待弱转强确认后再设止盈目标",
                stop_loss_line=f"下破 {support} 元彻底破坏形态",
                invalidation_rule=f"若次日早盘直接低开低走跌破昨日最低点，放弃该标的交易机会",
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
            invalidation_rule="放量滞涨即为减仓信号，严禁反向加仓",
        )
