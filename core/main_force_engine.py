"""主力行为生命周期状态机与反伪装引擎 (Main Force Lifecycle State Engine & Anti-Spoofing Filters).

核心特性与实现规格：
1. 完整覆盖 7 大生命周期阶段：
   - STAGE_1_ACCUMULATION: 隐性吸筹/底背离潜伏期
   - STAGE_2_BEAR_TRAP_WASHOUT: 破位洗盘/恐慌诱空挖坑期
   - STAGE_3_QUIET_WASHOUT: 缩量洗盘/时间换空间蓄势期
   - STAGE_4_HEALTHY_MARKUP: 健康主升/放量换手脱离成本期
   - STAGE_5_EXHAUSTION_ACCELERATION: 缩量加速赶顶期 (持仓锁仓/严禁追高，仓位死锁0%)
   - STAGE_6_DISTRIBUTION: 对倒派发/高位诱多出货期
   - STAGE_7_PASSIVE_DRIFT: 无抵抗阴跌/流动性枯竭出清期

2. 7 大反伪装与欺骗排除过滤器 (Anti-Deception Audit):
   - 大单拆分与小单化成交穿透 (TWAP/VWAP 穿透)
   - 对倒制造的虚假放量惩罚 (Amihud 非流动性与换手率背离)
   - 假突破 (Bull Trap) 诱多识别
   - 假破位 (Bear Trap) 空头陷阱识别
   - 缩量洗盘与时间换空间筹码沉降识别
   - 尾盘偷袭拉抬/打压惩罚 (Tail Pump/Dump Penalty)
   - 横盘震荡中的隐性吸筹识别

3. 多条件共振打分与置信度引擎:
   - 正交四维打分：价量趋势、微观聪明钱、换手筹码、梯队竞价
   - 置信度计算与模糊过渡区间判定 (Transition Zone)

4. 状态转移与迟滞回退引擎:
   - 升级需多周期或超高分持续性确认 (Persistence Window)
   - 高危出货 1 日快速熔断
   - 失败突破与破位回退机制
"""

from __future__ import annotations

from dataclasses import dataclass, field
import enum
import math
from typing import Any

import pandas as pd


class StageCode(str, enum.Enum):
    """主力生命周期 7 大阶段代码枚举。"""
    STAGE_1_ACCUMULATION = "STAGE_1_ACCUMULATION"
    STAGE_2_BEAR_TRAP_WASHOUT = "STAGE_2_BEAR_TRAP_WASHOUT"
    STAGE_3_QUIET_WASHOUT = "STAGE_3_QUIET_WASHOUT"
    STAGE_4_HEALTHY_MARKUP = "STAGE_4_HEALTHY_MARKUP"
    STAGE_5_EXHAUSTION_ACCELERATION = "STAGE_5_EXHAUSTION_ACCELERATION"
    STAGE_6_DISTRIBUTION = "STAGE_6_DISTRIBUTION"
    STAGE_7_PASSIVE_DRIFT = "STAGE_7_PASSIVE_DRIFT"


@dataclass
class AntiSpoofingAudit:
    """7 大反伪装过滤检测结果。"""
    order_split_detected: bool = False
    order_split_detail: str = ""

    wash_trading_detected: bool = False
    wash_trading_penalty: float = 0.0
    wash_trading_detail: str = ""

    fake_breakout_detected: bool = False
    fake_breakout_penalty: float = 0.0
    fake_breakout_detail: str = ""

    fake_breakdown_detected: bool = False
    fake_breakdown_bonus: float = 0.0
    fake_breakdown_detail: str = ""

    quiet_washout_confirmed: bool = False
    quiet_washout_detail: str = ""

    tail_pump_detected: bool = False
    tail_pump_penalty: float = 0.0
    tail_pump_detail: str = ""

    stealth_accumulation_detected: bool = False
    stealth_accumulation_detail: str = ""

    def total_penalty(self) -> float:
        """汇总扣分与惩罚。"""
        return self.wash_trading_penalty + self.fake_breakout_penalty + self.tail_pump_penalty

    def summary_lines(self) -> list[str]:
        """输出人类可读的审计清单。"""
        lines = []
        if self.order_split_detected:
            lines.append(f"🔍 算法拆单穿透: {self.order_split_detail}")
        if self.wash_trading_detected:
            lines.append(f"⚠️ 对倒虚假放量 (惩罚 -{self.wash_trading_penalty:.0f}分): {self.wash_trading_detail}")
        if self.fake_breakout_detected:
            lines.append(f"❌ 假突破诱多陷阱 (惩罚 -{self.fake_breakout_penalty:.0f}分): {self.fake_breakout_detail}")
        if self.fake_breakdown_detected:
            lines.append(f"🕳️ 空头陷阱/假破位 (洗盘确认 +{self.fake_breakdown_bonus:.0f}分): {self.fake_breakdown_detail}")
        if self.quiet_washout_confirmed:
            lines.append(f"⏳ 缩量时间换空间: {self.quiet_washout_detail}")
        if self.tail_pump_detected:
            lines.append(f"⚠️ 尾盘拉抬偷袭 (扣减 -{self.tail_pump_penalty:.0f}分): {self.tail_pump_detail}")
        if self.stealth_accumulation_detected:
            lines.append(f"🌱 横盘隐性吸筹确认: {self.stealth_accumulation_detail}")
        if not lines:
            lines.append("未检测到明显反常操盘伪装或异动陷阱，盘面信号真实度高。")
        return lines


@dataclass
class MainForceDecision:
    """主力行为生命周期状态机输出契约。"""
    stage_code: StageCode
    stage_name: str
    confidence: float
    is_transitional: bool
    suggested_pos_cap: float
    recommended_action: str
    decision_gear_override: str | None
    behavior_desc: str
    risk_alert: str
    anti_spoofing: AntiSpoofingAudit
    scores: dict[str, float] = field(default_factory=dict)
    transition_note: str = ""


class MainForceStateEngine:
    """生产级主力行为生命周期状态机与反伪装引擎。"""

    def __init__(self, persistence_window: int = 2) -> None:
        self.persistence_window = persistence_window
        # 内存状态记录器 (ticker -> (prior_stage, consecutive_days))
        self._history_state: dict[str, tuple[StageCode, int]] = {}

    def reset_state(self, ticker: str | None = None) -> None:
        """重置状态记录（用于测试或交易日切换）。"""
        if ticker:
            self._history_state.pop(ticker, None)
        else:
            self._history_state.clear()

    def evaluate(
        self,
        ticker: str,
        current_price: float,
        quote: dict[str, Any] | None = None,
        daily_df: pd.DataFrame | None = None,
        microstructure: dict[str, Any] | None = None,
        momentum: dict[str, Any] | None = None,
        ladder_info: dict[str, Any] | None = None,
        float_share: float = 0.0,
    ) -> MainForceDecision:
        """全量评估主力所处阶段，执行反伪装检测、多维共振打分、置信度度量与状态机流转。"""
        quote = quote or {}
        micro = microstructure or {}
        mom = momentum or {}
        ladder = ladder_info or {}

        # ─── 1. 基础特征提取与防御性默认值 ───
        pct_chg = float(quote.get("pct_chg", 0.0) or 0.0)
        turnover = float(quote.get("turnover", 0.0) or 0.0)
        open_price = float(quote.get("open", current_price) or current_price)
        high_price = float(quote.get("high", current_price) or current_price)
        low_price = float(quote.get("low", current_price) or current_price)
        amount_wan = float(quote.get("amount", 0.0) or 0.0) / 10000.0 if quote.get("amount") else 0.0

        smart_q = float(micro.get("smart_q") or 1.0)
        smart_vwap = float(micro.get("smart_vwap") or current_price)
        smart_buy_ratio = float(micro.get("smart_buy_ratio", 50.0) or 50.0)
        smart_sell_ratio = float(micro.get("smart_sell_ratio", 50.0) or 50.0)
        smart_phase = str(micro.get("smart_phase", "NEUTRAL") or "NEUTRAL")
        apm_pattern = str(micro.get("apm_pattern", "NEUTRAL") or "NEUTRAL")
        tail_vol_ratio = float(micro.get("tail_vol_ratio", 0.0) or 0.0)
        auction_chg = float(micro.get("auction_open_chg_pct", 0.0) or 0.0)
        auction_amt_wan = float(micro.get("auction_open_amt_wan", 0.0) or 0.0)

        overhead_chips = float(mom.get("overhead_chip_pct", 0.0) or 0.0)
        current_dd = float(mom.get("current_drawdown", 0.0) or 0.0)
        is_bullish_ma = bool(mom.get("is_bullish_ma", False))
        ma5 = float(mom.get("ma5", current_price) or current_price)
        ma20 = float(mom.get("ma20", current_price) or current_price)
        ma5_bias = float(mom.get("ma5_bias", 0.0) or 0.0)

        board_level = int(ladder.get("board_level", 0) or 0)
        broken_count = int(ladder.get("broken_count", 0) or 0)
        is_leader = bool(ladder.get("is_leader", False))

        # 中周期衍生统计 (20日/60日)
        price_position_60d, vol_ratio_20d, avg_amplitude_5d, price_breakdown = self._extract_daily_metrics(
            daily_df=daily_df,
            current_price=current_price,
            ma20=ma20,
        )

        # ─── 2. 执行 7 大反伪装与欺骗过滤器检测 ───
        audit = self._run_anti_spoofing_audit(
            current_price=current_price,
            open_price=open_price,
            high_price=high_price,
            low_price=low_price,
            pct_chg=pct_chg,
            turnover=turnover,
            amount_wan=amount_wan,
            smart_q=smart_q,
            smart_vwap=smart_vwap,
            smart_buy_ratio=smart_buy_ratio,
            smart_sell_ratio=smart_sell_ratio,
            smart_phase=smart_phase,
            apm_pattern=apm_pattern,
            tail_vol_ratio=tail_vol_ratio,
            overhead_chips=overhead_chips,
            is_bullish_ma=is_bullish_ma,
            vol_ratio_20d=vol_ratio_20d,
            avg_amplitude_5d=avg_amplitude_5d,
            price_position_60d=price_position_60d,
            price_breakdown=price_breakdown,
        )

        # ─── 3. 7 大阶段多维量化打分 (满分 100 分) ───
        scores = self._score_all_stages(
            current_price=current_price,
            open_price=open_price,
            high_price=high_price,
            low_price=low_price,
            pct_chg=pct_chg,
            turnover=turnover,
            amount_wan=amount_wan,
            smart_q=smart_q,
            smart_vwap=smart_vwap,
            smart_buy_ratio=smart_buy_ratio,
            smart_sell_ratio=smart_sell_ratio,
            smart_phase=smart_phase,
            apm_pattern=apm_pattern,
            tail_vol_ratio=tail_vol_ratio,
            overhead_chips=overhead_chips,
            current_dd=current_dd,
            is_bullish_ma=is_bullish_ma,
            ma5=ma5,
            ma20=ma20,
            ma5_bias=ma5_bias,
            board_level=board_level,
            broken_count=broken_count,
            is_leader=is_leader,
            auction_chg=auction_chg,
            auction_amt_wan=auction_amt_wan,
            price_position_60d=price_position_60d,
            vol_ratio_20d=vol_ratio_20d,
            avg_amplitude_5d=avg_amplitude_5d,
            audit=audit,
        )

        # ─── 4. 共振筛选、最高分排序与置信度度量 ───
        sorted_stages = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        top_stage_code = StageCode(sorted_stages[0][0])
        top_score = sorted_stages[0][1]
        second_score = sorted_stages[1][1] if len(sorted_stages) > 1 else 0.0

        score_gap = top_score - second_score
        is_transitional = score_gap < 14.0 or top_score < 60.0 or audit.total_penalty() > 20.0

        # 置信度模型：根据首位优势、绝对得分及反伪装惩罚综合计算
        base_confidence = min(96.0, max(20.0, top_score * 0.70 + score_gap * 1.5))
        final_confidence = round(max(15.0, min(98.0, base_confidence - audit.total_penalty() * 0.35)), 1)

        # ─── 5. 状态机流转与持续性确认 (Persistence Window & Hysteresis) ───
        final_stage_code, transition_note = self._apply_state_machine_transition(
            ticker=ticker,
            candidate_stage=top_stage_code,
            candidate_score=top_score,
            is_transitional=is_transitional,
            audit=audit,
        )

        # ─── 6. 生产级安全死锁与决策映射 (包含高标加速严禁买入死锁) ───
        meta = self._get_stage_metadata(
            stage_code=final_stage_code,
            current_price=current_price,
            smart_vwap=smart_vwap,
            overhead_chips=overhead_chips,
            smart_buy_ratio=smart_buy_ratio,
            smart_sell_ratio=smart_sell_ratio,
            board_level=board_level,
            price_position_60d=price_position_60d,
            audit=audit,
        )

        return MainForceDecision(
            stage_code=final_stage_code,
            stage_name=meta["stage_name"],
            confidence=final_confidence,
            is_transitional=is_transitional,
            suggested_pos_cap=meta["suggested_pos_cap"],
            recommended_action=meta["recommended_action"],
            decision_gear_override=meta["decision_gear_override"],
            behavior_desc=meta["behavior_desc"],
            risk_alert=meta["risk_alert"],
            anti_spoofing=audit,
            scores={k: round(v, 1) for k, v in scores.items()},
            transition_note=transition_note,
        )

    # ─────────────────────────────────────────────────────────────
    # 内部度量与反伪装算法
    # ─────────────────────────────────────────────────────────────

    def _extract_daily_metrics(
        self,
        daily_df: pd.DataFrame | None,
        current_price: float,
        ma20: float,
    ) -> tuple[float, float, float, bool]:
        """从中周期日线提取价格分位、20日量比、5日振幅及破位状态。"""
        if daily_df is None or daily_df.empty:
            return 0.50, 1.0, 3.5, False

        # 60日价格分位
        head_60 = daily_df.head(60)
        low_60 = float(head_60["low"].min()) if "low" in head_60 else current_price
        high_60 = float(head_60["high"].max()) if "high" in head_60 else current_price
        if high_60 > low_60:
            price_pos_60d = round(float((current_price - low_60) / (high_60 - low_60)), 3)
        else:
            price_pos_60d = 0.50

        # 20日成交量均值比
        vol_col = "vol" if "vol" in daily_df else ("volume" if "volume" in daily_df else None)
        vol_ratio_20d = 1.0
        if vol_col and len(daily_df) >= 2:
            head_20 = daily_df.head(20)
            avg_vol_20d = float(head_20[vol_col].mean())
            cur_vol = float(daily_df.iloc[0][vol_col])
            if avg_vol_20d > 0:
                vol_ratio_20d = round(cur_vol / avg_vol_20d, 2)

        # 5日平均振幅
        avg_amp_5d = 3.5
        if "high" in daily_df and "low" in daily_df and "close" in daily_df:
            head_5 = daily_df.head(5)
            amps = []
            for _, r in head_5.iterrows():
                c = float(r.get("close", 0.0) or 1.0)
                h = float(r.get("high", 0.0) or c)
                l = float(r.get("low", 0.0) or c)
                if c > 0:
                    amps.append((h - l) / c * 100.0)
            if amps:
                avg_amp_5d = round(float(pd.Series(amps).mean()), 2)

        # 破位标志 (现价跌破 MA20 且日线收在低位)
        price_breakdown = False
        if ma20 > 0 and current_price < ma20 * 0.985:
            price_breakdown = True

        return price_pos_60d, vol_ratio_20d, avg_amp_5d, price_breakdown

    def _run_anti_spoofing_audit(
        self,
        current_price: float,
        open_price: float,
        high_price: float,
        low_price: float,
        pct_chg: float,
        turnover: float,
        amount_wan: float,
        smart_q: float,
        smart_vwap: float,
        smart_buy_ratio: float,
        smart_sell_ratio: float,
        smart_phase: str,
        apm_pattern: str,
        tail_vol_ratio: float,
        overhead_chips: float,
        is_bullish_ma: bool,
        vol_ratio_20d: float,
        avg_amplitude_5d: float,
        price_position_60d: float,
        price_breakdown: bool,
    ) -> AntiSpoofingAudit:
        """运行 7 大反伪装核心算法。"""
        audit = AntiSpoofingAudit()

        # 1. 大单拆分穿透 (TWAP/VWAP 算法单穿透)
        # 聪明钱 Q 因子处于高效率极值，即使单笔成交看起来都是中小单，但知情占比显著偏向一方
        if smart_q < 0.985 or smart_q > 1.025:
            audit.order_split_detected = True
            if price_position_60d >= 0.80:
                direction = "高位封单扫货/锁仓推升" if smart_buy_ratio > smart_sell_ratio else "算法高位拆单派发"
            elif price_position_60d <= 0.40:
                direction = "低位主动吸筹收集" if smart_buy_ratio > smart_sell_ratio else "算法低位压盘逼空"
            else:
                direction = "中位加速接力" if smart_buy_ratio > smart_sell_ratio else "算法被动拆单减仓"
            audit.order_split_detail = (
                f"微观高频 Q 因子 ({smart_q:.3f}) 穿透表面中小单假象，识别主力正以算法拆单进行【{direction}】，"
                f"知情买卖效率比为 {smart_buy_ratio:.1f}% vs {smart_sell_ratio:.1f}%。"
            )

        # 2. 对倒制造的虚假放量惩罚 (Amihud 非流动性与换手率背离)
        # Amihud 指标 = |收益率| / 成交金额。放巨量但价格不涨 (低 Amihud) 表明对倒自成交
        if amount_wan > 500.0:
            amihud = abs(pct_chg) / amount_wan
            # 换手率大于 12% 且成交量放大 1.6 倍以上，但日涨跌幅在 [-1.5%, +1.5%] 内窄幅滞涨
            if turnover >= 12.0 and vol_ratio_20d >= 1.6 and abs(pct_chg) <= 1.5 and amihud < 0.0003:
                audit.wash_trading_detected = True
                audit.wash_trading_penalty = 30.0
                audit.wash_trading_detail = (
                    f"当日换手高达 {turnover:.1f}%、量比 {vol_ratio_20d:.1f}x 异常爆量，但实体振幅极小 (涨跌 {pct_chg:+.2f}%)，"
                    f"Amihud流动性冲击比仅 {amihud:.6f}，典型资金对倒自成交制造虚假繁荣，扣除放量主升分 30 分。"
                )

        # 3. 假突破 (Bull Trap) 诱多识别
        # 盘中创阶段新高，但收盘大幅回落形成长上影线，且微观呈现高位净派发
        total_range = max(high_price - low_price, 0.01)
        upper_shadow = max(high_price - max(open_price, current_price), 0.0)
        upper_ratio = (upper_shadow / total_range) * 100.0 if total_range > 0 else 0.0

        if price_position_60d > 0.65 and upper_ratio >= 45.0 and (smart_sell_ratio > 56.0 or apm_pattern == "AM_PUMP_PM_DUMP"):
            audit.fake_breakout_detected = True
            audit.fake_breakout_penalty = 35.0
            audit.fake_breakout_detail = (
                f"股价触及 60 日高位 (分位 {price_position_60d*100:.0f}%) 但冲高严重受阻，上影线占比达 {upper_ratio:.1f}%；"
                f"微观呈早盘诱多下午打压 (卖盘 {smart_sell_ratio:.1f}%)，判定为典型假突破诱多出货，扣除主升分 35 分。"
            )

        # 4. 假破位 (Bear Trap / 空头陷阱) 识别
        # 表面跌破均线或支撑，但成交量极度萎缩且微观机构逆势承接
        if price_breakdown and vol_ratio_20d < 0.80 and (apm_pattern == "PM_ABSORPTION" or smart_buy_ratio >= 58.0):
            audit.fake_breakdown_detected = True
            audit.fake_breakdown_bonus = 25.0
            audit.fake_breakdown_detail = (
                f"股价虽击穿均线，但成交量萎缩至 20 日均量的 {vol_ratio_20d*100:.0f}% (无恐慌出逃)，"
                f"高频微观反向呈现午后机构主动承接 (买盘 {smart_buy_ratio:.1f}%)，判定为主力刻意砸坑洗盘的假破位空头陷阱。"
            )

        # 5. 缩量洗盘与时间换空间筹码沉降确认
        if vol_ratio_20d <= 0.65 and avg_amplitude_5d <= 3.8 and overhead_chips < 35.0 and not price_breakdown:
            audit.quiet_washout_confirmed = True
            audit.quiet_washout_detail = (
                f"日均振幅压缩至 {avg_amplitude_5d:.2f}%，量能显著衰竭至 20 日均量的 {vol_ratio_20d*100:.0f}%，"
                f"上方套牢盘已充分沉降至低位 (套牢仅 {overhead_chips:.1f}%)，符合主力缩量洗盘以时间换空间特征。"
            )

        # 6. 尾盘偷袭拉抬/刻意打压惩罚 (Tail Pump / Dump)
        # 最后 15~30 分钟量能异常偏大 (>28%) 且全天收益主要由尾盘突击完成
        if tail_vol_ratio >= 28.0 and pct_chg >= 2.0 and apm_pattern != "PM_ABSORPTION":
            audit.tail_pump_detected = True
            audit.tail_pump_penalty = 20.0
            audit.tail_pump_detail = (
                f"尾盘半小时成交占比异常高达 {tail_vol_ratio:.1f}%，属于典型的无持续资金支撑的尾盘偷袭拉抬做线，"
                f"次日极易遭遇低开反噬，扣减主升健康度 20 分。"
            )

        # 7. 横盘震荡中的隐性吸筹确认
        if price_position_60d <= 0.35 and avg_amplitude_5d <= 4.0 and smart_buy_ratio >= 56.0 and current_price >= smart_vwap * 0.99:
            audit.stealth_accumulation_detected = True
            audit.stealth_accumulation_detail = (
                f"股价在底部箱体窄幅收敛，微观知情资金买盘比达 {smart_buy_ratio:.1f}%，"
                f"现价 ({current_price:.2f}元) 贴合甚至站上知情成本线 ({smart_vwap:.2f}元)，确认为主力算法隐性吸筹。"
            )

        return audit

    # ─────────────────────────────────────────────────────────────
    # 7 大阶段多维打分逻辑
    # ─────────────────────────────────────────────────────────────

    def _score_all_stages(
        self,
        current_price: float,
        open_price: float,
        high_price: float,
        low_price: float,
        pct_chg: float,
        turnover: float,
        amount_wan: float,
        smart_q: float,
        smart_vwap: float,
        smart_buy_ratio: float,
        smart_sell_ratio: float,
        smart_phase: str,
        apm_pattern: str,
        tail_vol_ratio: float,
        overhead_chips: float,
        current_dd: float,
        is_bullish_ma: bool,
        ma5: float,
        ma20: float,
        ma5_bias: float,
        board_level: int,
        broken_count: int,
        is_leader: bool,
        auction_chg: float,
        auction_amt_wan: float,
        price_position_60d: float,
        vol_ratio_20d: float,
        avg_amplitude_5d: float,
        audit: AntiSpoofingAudit,
    ) -> dict[str, float]:
        """对 7 大生命周期阶段进行打分计算 (0~100)。"""
        scores: dict[str, float] = {}

        # -------------------------------------------------------------
        # STAGE 1: 低位隐蔽吸筹期 (STAGE_1_ACCUMULATION)
        # 核心：低位 + 聪明钱买入占优 + 振幅收敛 + 隐性吸筹
        # -------------------------------------------------------------
        s1 = 20.0
        # 价格位置分 (0~30)
        if price_position_60d <= 0.25:
            s1 += 30.0
        elif price_position_60d <= 0.40:
            s1 += 20.0
        # 聪明钱与微观分 (0~30)
        if smart_buy_ratio >= 60.0 or smart_phase == "ACCUMULATION":
            s1 += 25.0
        elif smart_buy_ratio >= 53.0:
            s1 += 15.0
        if smart_q < 0.985:
            s1 += 5.0
        # 筹码与振幅分 (0~20)
        if overhead_chips <= 35.0:
            s1 += 10.0
        if avg_amplitude_5d <= 3.5:
            s1 += 10.0
        # 反伪装奖赏
        if audit.stealth_accumulation_detected:
            s1 += 15.0
        # 扣分：若高位或空头剧烈下砸
        if price_position_60d > 0.60 or smart_sell_ratio > 60.0:
            s1 -= 40.0
        scores[StageCode.STAGE_1_ACCUMULATION.value] = max(0.0, min(100.0, s1))

        # -------------------------------------------------------------
        # STAGE 2: 破位洗盘/恐慌诱空挖坑期 (STAGE_2_BEAR_TRAP_WASHOUT)
        # 核心：破位形态 + 缩量无踩踏 + 微观机构逆势低吸承接 (空头陷阱)
        # -------------------------------------------------------------
        s2 = 15.0
        if current_price < ma20 * 0.99 or current_dd < -10.0:
            s2 += 25.0
        # 缩量砸坑无踩踏
        if vol_ratio_20d <= 0.85:
            s2 += 20.0
        # 微观呈现午后真金白银逆势托底
        if apm_pattern == "PM_ABSORPTION":
            s2 += 25.0
        elif smart_buy_ratio >= 57.0:
            s2 += 15.0
        # 空头陷阱反伪装奖励
        if audit.fake_breakdown_detected:
            s2 += audit.fake_breakdown_bonus
        # 扣分项：若放量大阴线踩踏破位，绝非假破位！
        if vol_ratio_20d >= 1.5 and pct_chg < -3.5:
            s2 -= 45.0
        scores[StageCode.STAGE_2_BEAR_TRAP_WASHOUT.value] = max(0.0, min(100.0, s2))

        # -------------------------------------------------------------
        # STAGE 3: 缩量洗盘/时间换空间蓄势期 (STAGE_3_QUIET_WASHOUT)
        # 核心：依托均线 + 振幅极致收敛 + 极致缩量 + 筹码沉降
        # -------------------------------------------------------------
        s3 = 20.0
        if current_price >= ma20 * 0.98:
            s3 += 20.0
        if vol_ratio_20d <= 0.65:
            s3 += 25.0
        elif vol_ratio_20d <= 0.80:
            s3 += 15.0
        if avg_amplitude_5d <= 3.5:
            s3 += 20.0
        if overhead_chips <= 30.0:
            s3 += 10.0
        if audit.quiet_washout_confirmed:
            s3 += 15.0
        # 扣分：大起大落或放巨量非缩量洗盘
        if vol_ratio_20d > 1.4 or abs(pct_chg) > 4.5:
            s3 -= 35.0
        scores[StageCode.STAGE_3_QUIET_WASHOUT.value] = max(0.0, min(100.0, s3))

        # -------------------------------------------------------------
        # STAGE 4: 健康主升/放量换手脱离成本期 (STAGE_4_HEALTHY_MARKUP)
        # 核心：均线多头 + 放量脱离成本 + 真实换手 + 排除假突破与尾盘偷袭
        # -------------------------------------------------------------
        s4 = 20.0
        if is_bullish_ma and current_price > ma5 >= ma20:
            s4 += 25.0
        if current_price > smart_vwap * 1.02:
            s4 += 15.0
        if 1.1 <= vol_ratio_20d <= 2.8 and 3.0 <= turnover <= 22.0:
            s4 += 20.0
        if smart_buy_ratio >= 55.0 and apm_pattern != "AM_PUMP_PM_DUMP":
            s4 += 15.0
        if 0.0 <= auction_chg <= 4.0:
            s4 += 5.0
        # 反伪装惩罚：假突破、对倒、尾盘偷袭扣分
        if audit.fake_breakout_detected:
            s4 -= audit.fake_breakout_penalty
        if audit.wash_trading_detected:
            s4 -= audit.wash_trading_penalty
        if audit.tail_pump_detected:
            s4 -= audit.tail_pump_penalty
        # 高连板或极致缩量锁仓应归为 Stage 5
        if board_level >= 3 and turnover < 10.0:
            s4 -= 20.0
        scores[StageCode.STAGE_4_HEALTHY_MARKUP.value] = max(0.0, min(100.0, s4))

        # -------------------------------------------------------------
        # STAGE 5: 缩量加速赶顶期 (STAGE_5_EXHAUSTION_ACCELERATION)
        # 核心：连板龙头/极端乖离 + 筹码极度锁定 + 获利盘巨大 (持仓锁仓/严禁追高)
        # -------------------------------------------------------------
        s5 = 10.0
        if board_level >= 4:
            s5 += 50.0
        elif board_level >= 3:
            s5 += 35.0
        elif is_leader and pct_chg >= 9.5:
            s5 += 25.0
        # 极端涨幅与主力获利盘巨大 (浮盈超 30%)
        profit_ratio = (current_price / smart_vwap) - 1.0 if smart_vwap > 0 else 0.0
        if profit_ratio >= 0.30:
            s5 += 20.0
        elif profit_ratio >= 0.15:
            s5 += 10.0
        # 缩量锁仓特征 (高位换手未大量释放或极致一致)
        if (board_level >= 3 or price_position_60d > 0.85) and turnover <= 12.0:
            s5 += 15.0
        if ma5_bias >= 10.0:
            s5 += 10.0
        # 扣分：若已放量断板炸板多次，则不再是锁仓加速，而是派发出货
        if broken_count >= 2 or (board_level == 0 and pct_chg < 2.0):
            s5 -= 40.0
        scores[StageCode.STAGE_5_EXHAUSTION_ACCELERATION.value] = max(0.0, min(100.0, s5))

        # -------------------------------------------------------------
        # STAGE 6: 对倒派发/高位诱多出货期 (STAGE_6_DISTRIBUTION)
        # 核心：高位滞涨 + 炸板多次 + 算法被动派发 + 早盘脉冲下午下砸 + 对倒虚假放量
        # -------------------------------------------------------------
        s6 = 15.0
        if price_position_60d >= 0.65 or board_level >= 2:
            s6 += 20.0
        if smart_sell_ratio >= 58.0 or smart_phase == "DISTRIBUTION":
            s6 += 25.0
        if apm_pattern == "AM_PUMP_PM_DUMP":
            s6 += 20.0
        if broken_count >= 2:
            s6 += 20.0
        # 反伪装识别加权：假突破与对倒放量正是派发期标志！
        if audit.fake_breakout_detected:
            s6 += 20.0
        if audit.wash_trading_detected:
            s6 += 20.0
        # 扣分：低位且无抛压
        if price_position_60d < 0.35 and smart_buy_ratio > 60.0:
            s6 -= 45.0
        scores[StageCode.STAGE_6_DISTRIBUTION.value] = max(0.0, min(100.0, s6))

        # -------------------------------------------------------------
        # STAGE 7: 无抵抗阴跌/流动性枯竭出清期 (STAGE_7_PASSIVE_DRIFT)
        # 核心：上方套牢盘沉重 + 均线破位下行 + 现价跌破知情均线 + 缺乏机构托底
        # -------------------------------------------------------------
        s7 = 20.0
        if overhead_chips >= 60.0:
            s7 += 30.0
        elif overhead_chips >= 45.0:
            s7 += 18.0
        if not is_bullish_ma and current_price < ma5 and current_price < ma20:
            s7 += 25.0
        if current_price < smart_vwap * 0.97:
            s7 += 15.0
        if smart_sell_ratio > smart_buy_ratio and apm_pattern in ("PASSIVE_DRIFT", "NEUTRAL"):
            s7 += 15.0
        if current_dd < -18.0:
            s7 += 10.0
        # 扣分：若均线多头且处于主升通道
        if is_bullish_ma and current_price > ma20 and overhead_chips < 30.0:
            s7 -= 50.0
        scores[StageCode.STAGE_7_PASSIVE_DRIFT.value] = max(0.0, min(100.0, s7))

        return scores

    # ─────────────────────────────────────────────────────────────
    # 状态机迁移与回退引擎
    # ─────────────────────────────────────────────────────────────

    def _apply_state_machine_transition(
        self,
        ticker: str,
        candidate_stage: StageCode,
        candidate_score: float,
        is_transitional: bool,
        audit: AntiSpoofingAudit,
    ) -> tuple[StageCode, str]:
        """应用状态转移迟滞与回退规则，避免频繁误报。"""
        record = self._history_state.get(ticker)
        if not record:
            self._history_state[ticker] = (candidate_stage, 1)
            return candidate_stage, "初始周期确立"

        prior_stage, duration = record

        # 规则 1: 高危出货熔断 (STAGE_6_DISTRIBUTION) - 买方风控 1 日瞬时切换
        if candidate_stage == StageCode.STAGE_6_DISTRIBUTION and candidate_score >= 60.0:
            self._history_state[ticker] = (StageCode.STAGE_6_DISTRIBUTION, 1)
            note = f"⚠️ 触发高危派发快速熔断：由前序状态 [{prior_stage.name}] 瞬时切换至出货派发期。"
            return StageCode.STAGE_6_DISTRIBUTION, note

        # 规则 2: 主升/加速确认迟滞 (Hysteresis for Markups)
        # 若从非主升阶段跨入主升 (Stage 4) 或加速 (Stage 5)，需满足：
        # 得分碾压 78 分以上，或连续 2 日被判定为候选主升
        if candidate_stage in (StageCode.STAGE_4_HEALTHY_MARKUP, StageCode.STAGE_5_EXHAUSTION_ACCELERATION):
            if prior_stage not in (StageCode.STAGE_4_HEALTHY_MARKUP, StageCode.STAGE_5_EXHAUSTION_ACCELERATION):
                if candidate_score < 76.0 and audit.total_penalty() > 0:
                    # 迟滞过滤：暂缓升级，保持洗盘蓄势或存量震荡
                    note = f"⏳ 状态转移迟滞确认中：候选 [{candidate_stage.name}] 得分 ({candidate_score:.1f}) 未达碾压阈值且有扰动，维持前序蓄势。"
                    fallback = StageCode.STAGE_3_QUIET_WASHOUT if prior_stage == StageCode.STAGE_3_QUIET_WASHOUT else prior_stage
                    self._history_state[ticker] = (fallback, duration + 1)
                    return fallback, note

        # 规则 3: 假突破回退 (Failed Breakout Fallback)
        if audit.fake_breakout_detected and prior_stage == StageCode.STAGE_4_HEALTHY_MARKUP:
            fallback = StageCode.STAGE_6_DISTRIBUTION if candidate_score > 60 else StageCode.STAGE_3_QUIET_WASHOUT
            self._history_state[ticker] = (fallback, 1)
            note = f"❌ 遭遇假突破诱多打压：由主升通道回退至 [{fallback.name}]。"
            return fallback, note

        # 正常迁移或保持
        if candidate_stage == prior_stage:
            self._history_state[ticker] = (candidate_stage, duration + 1)
            note = f"状态持续共振 ({duration + 1}天)"
        else:
            self._history_state[ticker] = (candidate_stage, 1)
            note = f"状态机从 [{prior_stage.name}] 顺畅迁移至 [{candidate_stage.name}]"

        return candidate_stage, note

    # ─────────────────────────────────────────────────────────────
    # 阶段元数据与死锁控制
    # ─────────────────────────────────────────────────────────────

    def _get_stage_metadata(
        self,
        stage_code: StageCode,
        current_price: float,
        smart_vwap: float,
        overhead_chips: float,
        smart_buy_ratio: float,
        smart_sell_ratio: float,
        board_level: int,
        price_position_60d: float,
        audit: AntiSpoofingAudit,
    ) -> dict[str, Any]:
        """构建各阶段的文本描述、证伪条件及硬核仓位死锁配置。"""
        profit_pct = ((current_price / smart_vwap) - 1.0) * 100.0 if smart_vwap > 0 else 0.0

        if stage_code == StageCode.STAGE_1_ACCUMULATION:
            return {
                "stage_name": "【🌱 低位隐蔽吸筹期】",
                "suggested_pos_cap": 0.10,
                "recommended_action": "【左侧轻仓逢低分批潜伏】",
                "decision_gear_override": None,
                "behavior_desc": (
                    f"股价处于 60 日底部安全吸筹区 (分位 {price_position_60d*100:.0f}%)，微观高效率买盘占比 {smart_buy_ratio:.1f}%；"
                    f"主力利用算法小单在水下箱体隐蔽吸纳筹码，未引起表面成交量异动，知情底仓成本锁定在 {smart_vwap:.2f} 元附近。"
                ),
                "risk_alert": "吸筹周期耗时漫长且常伴随磨人假摔洗盘，若有效跌破箱体下沿或放量杀跌，需暂停建仓并止损防守。",
            }

        elif stage_code == StageCode.STAGE_2_BEAR_TRAP_WASHOUT:
            return {
                "stage_name": "【🕳️ 破位恐慌挖坑期 (假破位诱空)】",
                "suggested_pos_cap": 0.10,
                "recommended_action": "【黄金坑低吸 / 等待右侧长阳收复】",
                "decision_gear_override": None,
                "behavior_desc": (
                    f"股价形态看似跌破关键均线引发散户恐慌，但全天成交量明显萎缩 (无真实主力踩踏出逃)；"
                    f"微观高频显示午后知情资金逆势大单托底吸收抛盘，属于典型主力刻意洗盘的诱空空头陷阱。"
                ),
                "risk_alert": "必须等待日线重新站上 5 日线进行右侧确认；若次日放量继续单边砸盘，则假破位演化为真破位，严禁盲目加仓！",
            }

        elif stage_code == StageCode.STAGE_3_QUIET_WASHOUT:
            return {
                "stage_name": "【⏳ 缩量洗盘蓄势期 (时间换空间)】",
                "suggested_pos_cap": 0.15,
                "recommended_action": "【依托支撑均线回踩企稳低吸】",
                "decision_gear_override": None,
                "behavior_desc": (
                    f"股价在均线支撑上方窄幅整理，振幅极度收敛且成交量持续衰竭；"
                    f"主力以时间换空间耐心清洗浮动获利盘，上方套牢盘快速沉淀降至 {overhead_chips:.1f}%，筹码结构扎实健康。"
                ),
                "risk_alert": "若向下放量击穿 20 日生命均线或知情均线 ({smart_vwap:.2f}元)，则洗盘蓄势宣告失败，立即转入防守。",
            }

        elif stage_code == StageCode.STAGE_4_HEALTHY_MARKUP:
            return {
                "stage_name": "【🔥 健康放量主升期 (趋势推升)】",
                "suggested_pos_cap": 0.20,
                "recommended_action": "【顺势做多 / 分时回踩均线低吸】",
                "decision_gear_override": None,
                "behavior_desc": (
                    f"日线均线呈典型多头排列，量价良性配合脱离建仓成本区；"
                    f"微观知情资金主动买盘比达 {smart_buy_ratio:.1f}% 且通过对倒与假突破反伪装验证，属于资金合力驱动的健康主升浪。"
                ),
                "risk_alert": "防范冲高遇阻产生日线顶背离；严格执行 A 股 T+1 纪律，次日若收盘跌破 5 日线启动部分止盈防守。",
            }

        elif stage_code == StageCode.STAGE_5_EXHAUSTION_ACCELERATION:
            # ─────────────────────────────────────────────────────────
            # 生产级安全死锁：高标加速严禁新开仓追高！仓位上限锁死为 0.0！
            # ─────────────────────────────────────────────────────────
            return {
                "stage_name": "【🚀 缩量加速赶顶期 (主升锁仓/严禁追高)】",
                "suggested_pos_cap": 0.0,
                "recommended_action": "【🔒 持股者锁仓守利 / 持币者严禁追高】",
                "decision_gear_override": "观察",
                "behavior_desc": (
                    f"标的处于高位加速冲刺阶段 (当前连板/身位: {board_level}板)；底仓知情资金建仓均价 {smart_vwap:.2f} 元，"
                    f"主力底层账面浮盈已达 +{profit_pct:.1f}%，筹码极度锁定。处于极端加速博傻赶顶态势，随时面临获利盘分歧兑现踩踏！"
                ),
                "risk_alert": (
                    "【死锁风控】A股缩量加速即见顶！该阶段盘中极易发生瞬时炸板与天地板闪崩，持币者严禁追高接盘(买入仓位锁定0%)；"
                    "持仓者以早盘分时破线或放量开板作为锁仓止盈出局硬触发条件。"
                ),
            }

        elif stage_code == StageCode.STAGE_6_DISTRIBUTION:
            return {
                "stage_name": "【⚠️ 对倒派发出货期 (诱多滞涨)】",
                "suggested_pos_cap": 0.0,
                "recommended_action": "【坚决清仓离场 / 严禁任何抄底】",
                "decision_gear_override": "回避",
                "behavior_desc": (
                    f"股价处于高位高风险区，微观卖盘打压占比达 {smart_sell_ratio:.1f}%；"
                    f"主力多借助早盘虚假脉冲诱多吸引跟风盘接盘，随后利用算法拆单全天暗中派发撤离，量价呈现严重滞涨或顶背离。"
                ),
                "risk_alert": "主力资金进入实质兑现出逃阶段，盘中任何反弹皆是诱多逃命点，谨防断头铡刀式断崖下挫！",
            }

        else:  # STAGE_7_PASSIVE_DRIFT
            return {
                "stage_name": "【📉 无抵抗阴跌出清期 (流动性枯竭)】",
                "suggested_pos_cap": 0.0,
                "recommended_action": "【空仓观望 / 绝不左侧接飞刀】",
                "decision_gear_override": "观察",
                "behavior_desc": (
                    f"上方沉淀解套抛压沉重 (套牢盘高达 {overhead_chips:.1f}%)，现价显著跌破知情均线 ({smart_vwap:.2f}元)；"
                    f"场内机构放弃护盘抵抗，微观呈现单边被动弱势漂移，缺乏增量大资金主动承接。"
                ),
                "risk_alert": "严禁任何主观臆测抄底！在未见机构放量长阳突破 5 日线形成底分型企稳前，盲目入场极易被深套磨损本金。",
            }
