"""A-share Market Microstructure & Main Force Informed Trading Analyzer.

Based on quantitative financial engineering research (Kaiyuan Quant, Huatai Quant):
1. Smart Money Q-Factor: S_t = |R_t| / sqrt(V_t), top 20% volume time-slicing
2. APM Intraday Decomposition: Morning (09:30-11:30) vs Afternoon (13:00-15:00) vs Tail (14:30-15:00)
3. Opening Call Auction: 09:20-09:25 non-cancellable price impact and unmatched orders
4. Main Force Lifecycle State Engine: Sits at the intersection of microstructural Q,
   auction aggression, medium-term turnover sedimentation, and chip distribution.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any
import pandas as pd

from .main_force_engine import (
    MainForceDecision,
    MainForceStateEngine,
    StageCode,
    AntiSpoofingAudit,
)


@dataclass
class MicrostructureProfile:
    """微观结构与知情交易分析画像。"""
    smart_q: float                      # 聪明钱 Q 因子 (VWAP_smart / VWAP_all)
    smart_vwap: float                   # 聪明钱加权均价
    all_vwap: float                     # 全市场加权均价
    smart_buy_ratio: float              # 聪明钱时段主动推升成交占比 (%)
    smart_sell_ratio: float             # 聪明钱时段打压派发成交占比 (%)
    smart_phase: str                    # 聪明钱意图: ACCUMULATION / DISTRIBUTION / PASSIVE_FALL / NEUTRAL
    apm_pattern: str                    # 日内时段形态: AM_PUMP_PM_DUMP / PM_ABSORPTION / PASSIVE_DRIFT / NEUTRAL
    am_return_pct: float                # 早盘平均收益率 (%)
    pm_return_pct: float                # 午后平均收益率 (%)
    tail_vol_ratio: float               # 尾盘半小时成交占比 (%)
    auction_open_amt_wan: float         # 今日竞价成交额 (万元)
    auction_open_chg_pct: float         # 今日竞价开盘涨幅 (%)
    verdict_text: str                   # 综合微观诊断结论
    # ── 主力行为生命周期阶段 (两大核心拼图补齐) ──
    main_force_stage: str               # 显式主力阶段标签: 如 "【🚀 缩量加速赶顶期 (持仓锁仓/严禁追高)】"
    main_force_behavior: str            # 主力行为深度穿透解读
    main_force_risk: str                # 做多证伪与风险触发条件
    cum_turnover_20d: float             # 20日累计换手率 (%)
    price_position_60d: float           # 60日价格分位 (0.0~1.0)
    # ── 生产级状态机与反伪装扩展字段 ──
    main_force_confidence: float = 80.0
    is_transitional: bool = False
    suggested_pos_cap: float = 0.15
    recommended_action: str = ""
    decision_gear_override: str | None = None
    stage_code: str = "STAGE_3_QUIET_WASHOUT"
    anti_spoofing_summary: list[str] = field(default_factory=list)
    scores: dict[str, float] = field(default_factory=dict)


class MicrostructureAnalyzer:
    """微观结构分析器：穿透拆单算法与盘口伪装。"""

    def __init__(self, engine: MainForceStateEngine | None = None) -> None:
        self.engine = engine or MainForceStateEngine()

    def analyze(
        self,
        five_min_bars: list[Any],
        auction_data: Any | None = None,
        current_price: float = 0.0,
        daily_df: pd.DataFrame | None = None,
        momentum: dict[str, Any] | None = None,
        ladder_info: dict[str, Any] | None = None,
        float_share: float = 0.0,
        quote: dict[str, Any] | None = None,
        ticker: str = "DEFAULT",
    ) -> MicrostructureProfile:
        """分析 5 分钟 K 线、集合竞价、中周期换手沉淀与主力生命周期。"""
        if not five_min_bars or len(five_min_bars) < 20:
            return self._build_default_profile(current_price)

        # 1. 整理 5 分钟 K 线序列
        rows = []
        for b in five_min_bars:
            op = float(getattr(b, "open", 0.0) or 0.0)
            cl = float(getattr(b, "close", 0.0) or 0.0)
            vol = float(getattr(b, "volume_lots", 0.0) or getattr(b, "volume", 0.0) or 0.0)
            amt = float(getattr(b, "amount", 0.0) or 0.0)
            tm = getattr(b, "time", None)

            if op <= 0 or vol <= 0:
                continue

            # 日内收益率绝对值与成交量
            ret_pct = abs((cl - op) / op * 100.0)
            raw_ret = (cl - op) / op * 100.0
            
            # S_t 聪明度指标: 单位成交量引起的价格变动效率
            s_metric = ret_pct / (math.sqrt(vol) + 1e-6)

            rows.append({
                "time": tm,
                "open": op,
                "close": cl,
                "volume": vol,
                "amount": amt,
                "ret_pct": ret_pct,
                "raw_ret": raw_ret,
                "s_metric": s_metric,
                "is_up": cl >= op,
            })

        df = pd.DataFrame(rows)
        if df.empty or df["volume"].sum() <= 0:
            return self._build_default_profile(current_price)

        total_vol = df["volume"].sum()
        total_amt = df["amount"].sum()
        all_vwap = (total_amt / (total_vol * 100.0)) if total_vol > 0 else current_price

        # 2. 聪明钱 Q 因子计算 (开源金工 S 因子切割)
        df_sorted = df.sort_values("s_metric", ascending=False).reset_index(drop=True)
        df_sorted["cum_vol"] = df_sorted["volume"].cumsum()
        vol_threshold = total_vol * 0.20  # 累计成交量前 20% 的高效分钟

        smart_df = df_sorted[df_sorted["cum_vol"] <= vol_threshold]
        if smart_df.empty:
            smart_df = df_sorted.head(max(1, int(len(df_sorted) * 0.20)))

        smart_vol = smart_df["volume"].sum()
        smart_amt = smart_df["amount"].sum()
        smart_vwap = (smart_amt / (smart_vol * 100.0)) if smart_vol > 0 else all_vwap

        q_factor = round(smart_vwap / all_vwap, 4) if all_vwap > 0 else 1.0

        # 分析聪明钱时段的主动方向
        smart_up_vol = smart_df[smart_df["is_up"]]["volume"].sum()
        smart_down_vol = smart_df[~smart_df["is_up"]]["volume"].sum()
        smart_buy_ratio = round((smart_up_vol / smart_vol) * 100.0, 1) if smart_vol > 0 else 50.0
        smart_sell_ratio = round((smart_down_vol / smart_vol) * 100.0, 1) if smart_vol > 0 else 50.0

        # 判定聪明钱意图 (初筛)
        if q_factor < 0.985 and smart_buy_ratio > 52.0:
            smart_phase = "ACCUMULATION"
        elif q_factor > 1.015 and smart_sell_ratio > 52.0:
            smart_phase = "DISTRIBUTION"
        elif smart_sell_ratio > 60.0 and current_price < smart_vwap * 0.95:
            smart_phase = "PASSIVE_FALL"
        else:
            smart_phase = "NEUTRAL"

        # 3. APM 日内时段切割 (早盘 09:30-11:30 vs 午后 13:00-15:00)
        am_rets = []
        pm_rets = []
        tail_vols = 0.0
        all_day_vols = 0.0

        for _, r in df.iterrows():
            tm = r["time"]
            all_day_vols += r["volume"]
            if tm is not None:
                hour = tm.hour if hasattr(tm, "hour") else 10
                minute = tm.minute if hasattr(tm, "minute") else 0
                time_val = hour * 100 + minute

                if 930 <= time_val <= 1130:
                    am_rets.append(r["raw_ret"])
                elif 1300 <= time_val <= 1500:
                    pm_rets.append(r["raw_ret"])
                if 1430 <= time_val <= 1500:
                    tail_vols += r["volume"]

        avg_am_ret = round(float(pd.Series(am_rets).mean()), 2) if am_rets else 0.0
        avg_pm_ret = round(float(pd.Series(pm_rets).mean()), 2) if pm_rets else 0.0
        tail_vol_ratio = round((tail_vols / all_day_vols) * 100.0, 1) if all_day_vols > 0 else 0.0

        # 判定日内形态 (APM Pattern)
        if avg_am_ret > 0.3 and avg_pm_ret < -0.3:
            apm_pattern = "AM_PUMP_PM_DUMP"   # 早盘脉冲诱多，午后跌破均价线出货
        elif avg_am_ret < -0.2 and avg_pm_ret > 0.2:
            apm_pattern = "PM_ABSORPTION"     # 早盘恐慌洗盘，午后真金白银逆势承接
        elif avg_am_ret < 0 and avg_pm_ret < 0:
            apm_pattern = "PASSIVE_DRIFT"     # 全天缺乏机构承接，单边弱势阴跌
        else:
            apm_pattern = "NEUTRAL"

        # 4. 集合竞价微观特征
        auction_amt_wan = 0.0
        auction_chg_pct = 0.0
        if auction_data is not None:
            raw_amt = getattr(auction_data, "open_amount", 0.0) or 0.0
            auction_amt_wan = round(raw_amt / 10000.0, 1)
            raw_chg = getattr(auction_data, "open_change_pct", 0.0) or 0.0
            auction_chg_pct = round(raw_chg, 2)

        # 5. 中周期筹码换手与价格带位置测算 (20~60日换手沉降)
        cum_turnover_20d = 0.0
        price_position_60d = 0.5
        if daily_df is not None and not daily_df.empty:
            head_60 = daily_df.head(60)
            low_60 = head_60["low"].min() if "low" in head_60 else current_price
            high_60 = head_60["high"].max() if "high" in head_60 else current_price
            if high_60 > low_60:
                price_position_60d = round(float((current_price - low_60) / (high_60 - low_60)), 3)

            # 20日换手
            if "vol" in daily_df and float_share > 0:
                vol_20d = daily_df.head(20)["vol"].sum() * 100.0
                cum_turnover_20d = round(float(vol_20d / float_share * 100.0), 1)

        # 6. 调用主力行为生命周期状态机与反伪装引擎
        micro_dict = {
            "smart_q": q_factor,
            "smart_vwap": smart_vwap,
            "all_vwap": all_vwap,
            "smart_buy_ratio": smart_buy_ratio,
            "smart_sell_ratio": smart_sell_ratio,
            "smart_phase": smart_phase,
            "apm_pattern": apm_pattern,
            "tail_vol_ratio": tail_vol_ratio,
            "auction_open_amt_wan": auction_amt_wan,
            "auction_open_chg_pct": auction_chg_pct,
        }
        calc_quote = quote or {}
        if current_price > 0 and "close" not in calc_quote:
            calc_quote = dict(calc_quote)
            calc_quote["close"] = current_price

        decision: MainForceDecision = self.engine.evaluate(
            ticker=ticker,
            current_price=current_price,
            quote=calc_quote,
            daily_df=daily_df,
            microstructure=micro_dict,
            momentum=momentum or {},
            ladder_info=ladder_info,
            float_share=float_share,
        )

        stage_name = decision.stage_name
        behavior_text = decision.behavior_desc
        risk_text = decision.risk_alert

        # 综合诊断描述
        verdict = self._synthesize_verdict(
            stage_name=stage_name,
            q_factor=q_factor,
            smart_vwap=smart_vwap,
            all_vwap=all_vwap,
            current_price=current_price,
            smart_buy_ratio=smart_buy_ratio,
            smart_sell_ratio=smart_sell_ratio,
            smart_phase=smart_phase,
            apm_pattern=apm_pattern,
            tail_vol_ratio=tail_vol_ratio,
            auction_amt_wan=auction_amt_wan,
            auction_chg_pct=auction_chg_pct,
            price_position_60d=price_position_60d,
        )

        return MicrostructureProfile(
            smart_q=q_factor,
            smart_vwap=round(smart_vwap, 2),
            all_vwap=round(all_vwap, 2),
            smart_buy_ratio=smart_buy_ratio,
            smart_sell_ratio=smart_sell_ratio,
            smart_phase=smart_phase,
            apm_pattern=apm_pattern,
            am_return_pct=avg_am_ret,
            pm_return_pct=avg_pm_ret,
            tail_vol_ratio=tail_vol_ratio,
            auction_open_amt_wan=auction_amt_wan,
            auction_open_chg_pct=auction_chg_pct,
            verdict_text=verdict,
            main_force_stage=stage_name,
            main_force_behavior=behavior_text,
            main_force_risk=risk_text,
            cum_turnover_20d=cum_turnover_20d,
            price_position_60d=price_position_60d,
            main_force_confidence=decision.confidence,
            is_transitional=decision.is_transitional,
            suggested_pos_cap=decision.suggested_pos_cap,
            recommended_action=decision.recommended_action,
            decision_gear_override=decision.decision_gear_override,
            stage_code=decision.stage_code.value,
            anti_spoofing_summary=decision.anti_spoofing.summary_lines(),
            scores=decision.scores,
        )

    def _detect_main_force_stage(
        self,
        q_factor: float,
        smart_vwap: float,
        all_vwap: float,
        current_price: float,
        smart_buy_ratio: float,
        smart_sell_ratio: float,
        smart_phase: str,
        apm_pattern: str,
        auction_amt_wan: float,
        auction_chg_pct: float,
        cum_turnover_20d: float,
        price_position_60d: float,
        momentum: dict[str, Any],
        ladder_info: dict[str, Any] | None,
    ) -> tuple[str, str, str]:
        """向后兼容主力生命周期判定接口。"""
        micro_dict = {
            "smart_q": q_factor,
            "smart_vwap": smart_vwap,
            "all_vwap": all_vwap,
            "smart_buy_ratio": smart_buy_ratio,
            "smart_sell_ratio": smart_sell_ratio,
            "smart_phase": smart_phase,
            "apm_pattern": apm_pattern,
            "tail_vol_ratio": 10.0,
            "auction_open_amt_wan": auction_amt_wan,
            "auction_open_chg_pct": auction_chg_pct,
        }
        quote = {"close": current_price}
        decision = self.engine.evaluate(
            ticker="COMPAT",
            current_price=current_price,
            quote=quote,
            daily_df=None,
            microstructure=micro_dict,
            momentum=momentum or {},
            ladder_info=ladder_info,
        )
        return decision.stage_name, decision.behavior_desc, decision.risk_alert

    def _synthesize_verdict(
        self,
        stage_name: str,
        q_factor: float,
        smart_vwap: float,
        all_vwap: float,
        current_price: float,
        smart_buy_ratio: float,
        smart_sell_ratio: float,
        smart_phase: str,
        apm_pattern: str,
        tail_vol_ratio: float,
        auction_amt_wan: float,
        auction_chg_pct: float,
        price_position_60d: float,
    ) -> str:
        """合成一针见血的买方微观结构研判。"""
        parts = [f"主力行为处于{stage_name}"]

        # 聪明钱 Q 因子诊断
        if smart_phase == "ACCUMULATION":
            parts.append(f"聪明钱呈【低吸潜伏】(Q={q_factor:.3f}，高效率推升买盘 {smart_buy_ratio:.1f}%)")
        elif smart_phase == "DISTRIBUTION":
            parts.append(f"聪明钱呈【冲高派发】(Q={q_factor:.3f}，高位打压卖盘 {smart_sell_ratio:.1f}%)")
        elif smart_phase == "PASSIVE_FALL":
            parts.append(f"聪明钱【放弃抵抗/破位下砸】(高效率下砸成交占比 {smart_sell_ratio:.1f}%，现价低于知情成本线 {smart_vwap:.2f}元)")
        else:
            parts.append(f"聪明钱 Q={q_factor:.3f} (知情成本 {smart_vwap:.2f}元 vs 现价 {current_price:.2f}元，多空博弈均衡)")

        # APM 日内时段诊断
        if apm_pattern == "AM_PUMP_PM_DUMP":
            parts.append("日内多次呈现【早盘诱多冲高、午后算法持续撤退】的出货痕迹")
        elif apm_pattern == "PM_ABSORPTION":
            parts.append("日内呈现【早盘分歧探底、午后机构真金白银逆势承接】结构")
        elif apm_pattern == "PASSIVE_DRIFT":
            parts.append("日内缺乏机构主动买单托底，呈现无量阴跌态势")

        # 竞价与尾盘
        if auction_amt_wan > 1000:
            parts.append(f"开盘竞价成交 {auction_amt_wan:.0f}万元 ({auction_chg_pct:+.2f}%)")
        elif auction_amt_wan > 0:
            parts.append(f"开盘竞价偏淡 ({auction_chg_pct:+.2f}%, {auction_amt_wan:.0f}万)")

        return "；".join(parts)

    def _build_default_profile(self, current_price: float) -> MicrostructureProfile:
        return MicrostructureProfile(
            smart_q=1.0,
            smart_vwap=current_price,
            all_vwap=current_price,
            smart_buy_ratio=50.0,
            smart_sell_ratio=50.0,
            smart_phase="NEUTRAL",
            apm_pattern="NEUTRAL",
            am_return_pct=0.0,
            pm_return_pct=0.0,
            tail_vol_ratio=0.0,
            auction_open_amt_wan=0.0,
            auction_open_chg_pct=0.0,
            verdict_text="微观分钟数据不足，采用中性假定",
            main_force_stage="【⏳ 存量震荡/等待方向期】",
            main_force_behavior="分钟数据不足，无法准确刻画主力微观意图",
            main_force_risk="需观察日线均线与放量突破信号",
            cum_turnover_20d=0.0,
            price_position_60d=0.5,
            main_force_confidence=50.0,
            is_transitional=True,
            suggested_pos_cap=0.0,
            recommended_action="【观望等待方向明朗】",
            decision_gear_override=None,
            stage_code="STAGE_3_QUIET_WASHOUT",
            anti_spoofing_summary=["微观数据不足，反伪装过滤器已挂起。"],
            scores={},
        )
