"""A-share Market Microstructure & Main Force Informed Trading Analyzer.

Based on quantitative financial engineering research (Kaiyuan Quant, Huatai Quant):
1. Smart Money Q-Factor: S_t = |R_t| / sqrt(V_t), top 20% volume time-slicing
2. APM Intraday Decomposition: Morning (09:30-11:30) vs Afternoon (13:00-15:00) vs Tail (14:30-15:00)
3. Opening Call Auction: 09:20-09:25 non-cancellable price impact and unmatched orders
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any
import pandas as pd


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


class MicrostructureAnalyzer:
    """微观结构分析器：穿透拆单算法与盘口伪装。"""

    def analyze(
        self,
        five_min_bars: list[Any],
        auction_data: Any | None = None,
        current_price: float = 0.0,
    ) -> MicrostructureProfile:
        """分析 5 分钟 K 线历史序列与当日集合竞价。"""
        if not five_min_bars or len(five_min_bars) < 20:
            return self._build_default_profile(current_price)

        # 1. 整理 5 分钟 K 线序列
        rows = []
        for b in five_min_bars:
            op = float(getattr(b, "open", 0.0) or 0.0)
            cl = float(getattr(b, "close", 0.0) or 0.0)
            vol = float(getattr(b, "volume_lots", 0.0) or 0.0)
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
        # 全周期成交均价 (元/股)
        all_vwap = (total_amt / (total_vol * 100.0)) if total_vol > 0 else current_price

        # 2. 聪明钱 Q 因子计算 (开源金工 S 因子切割)
        # 按 S 聪明度从大到小排序
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

        # 判定聪明钱意图
        if q_factor < 0.985 and smart_buy_ratio > 52.0:
            smart_phase = "ACCUMULATION"   # 聪明钱在全天低均价区密集买入 (低吸潜伏)
        elif q_factor > 1.015 and smart_sell_ratio > 52.0:
            smart_phase = "DISTRIBUTION"   # 聪明钱在全天高均价区密集抛售 (冲高派发)
        elif smart_sell_ratio > 60.0 and current_price < smart_vwap * 0.95:
            smart_phase = "PASSIVE_FALL"   # 聪明钱放弃抵抗，大单下砸破位
        else:
            smart_phase = "NEUTRAL"        # 存量博弈，无极端知情单向异动

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

        # 5. 合成综合买方诊断结论
        verdict = self._synthesize_verdict(
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
        )

    def _synthesize_verdict(
        self,
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
    ) -> str:
        """合成一针见血的买方微观结构研判。"""
        parts = []

        # 聪明钱 Q 因子诊断
        if smart_phase == "ACCUMULATION":
            parts.append(f"✓ 聪明钱呈【低吸潜伏】态势 (Q={q_factor:.3f}，高效率成交偏向水下买盘 {smart_buy_ratio:.1f}%)")
        elif smart_phase == "DISTRIBUTION":
            parts.append(f"❌ 聪明钱呈【冲高派发】特征 (Q={q_factor:.3f}，高效率成交集中于高位砸盘 {smart_sell_ratio:.1f}%)")
        elif smart_phase == "PASSIVE_FALL":
            parts.append(f"❌ 聪明钱【放弃抵抗/破位下砸】(高效率下砸成交占比高达 {smart_sell_ratio:.1f}%，现价远低于知情成本线 {smart_vwap:.2f}元)")
        else:
            parts.append(f"聪明钱 Q={q_factor:.3f} (知情成本 {smart_vwap:.2f}元 vs 全天均价 {all_vwap:.2f}元，多空博弈均衡)")

        # APM 日内时段诊断
        if apm_pattern == "AM_PUMP_PM_DUMP":
            parts.append("日内多次呈现【早盘诱多冲高、午后算法持续撤退】的出货痕迹")
        elif apm_pattern == "PM_ABSORPTION":
            parts.append("日内呈现【早盘分歧探底、午后机构真金白银逆势承接】结构")
        elif apm_pattern == "PASSIVE_DRIFT":
            parts.append("日内缺乏机构主动买单托底，呈现无量阴跌态势")

        # 竞价与尾盘
        if auction_amt_wan > 0:
            if auction_chg_pct < -1.0:
                parts.append(f"早盘竞价开盘偏弱 ({auction_chg_pct:+.2f}%, 成交 {auction_amt_wan:.0f}万)")
            elif auction_chg_pct > 1.5:
                parts.append(f"早盘竞价高开进攻 ({auction_chg_pct:+.2f}%, 成交 {auction_amt_wan:.0f}万)")

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
        )
