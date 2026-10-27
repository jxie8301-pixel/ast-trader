"""Macro Market Regime Engine (宏观大盘与全市场情绪多维研判引擎).

解耦大盘宏观指数环境 (Macro Index Beta) 与超短投机水温 (Speculative Micro-climate)，
建立多维度交叉验证与共振/背离判别框架，杜绝单一分支硬切与个股代表大盘的错误逻辑。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

logger = logging.getLogger("ast_trader.core.macro_regime")


@dataclass(frozen=True)
class IndexTrendMetrics:
    """大盘指数趋势与均线结构度量。"""
    code: str
    name: str
    close: float
    pct_chg: float
    ma5: float
    ma10: float
    ma20: float
    ma60: float
    ma_alignment: str  # BULL (多头排列), BEAR (空头排列), TANGLED (均线纠缠)
    consecutive_down_days: int
    consecutive_up_days: int
    ret_5d: float
    ret_20d: float
    trend_regime: str  # 破位阴跌探底, 均线纠缠震荡, 多头主升加速, 高位滞涨见顶
    score: float       # 0 - 100


@dataclass(frozen=True)
class MarketBreadthMetrics:
    """全市场广度与赚钱效应分布度量。"""
    up_count: int
    down_count: int
    neutral_count: int
    total_count: int
    breadth_ratio: float  # up / (up + down)
    breadth_regime: str   # 极端普跌冰点, 弱势退潮分化, 结构分化平衡, 普涨赚钱活跃
    score: float          # 0 - 100


@dataclass(frozen=True)
class MarketVolumeMetrics:
    """全市场量能与流动性水位度量。"""
    total_amount: float     # 当日成交额 (元)
    avg_amount_5d: float    # 近5日均量 (元)
    amount_ratio: float     # 当日成交额 / 5日均量
    volume_regime: str      # 放量杀跌, 缩量阴跌, 放量拉升, 缩量弱反, 量能平稳
    score: float            # 0 - 100


@dataclass(frozen=True)
class SpeculativeMetrics:
    """超短连板投机水温度量。"""
    space_board_level: int
    space_board_tickers: list[str]
    limit_up_count: int
    limit_down_count: int
    broken_count: int
    broken_rate_pct: float
    speculative_regime: str  # 弱市妖股逆势抱团, 短线主升加速发酵, 高位共振放量分歧, 全线冰点恐慌踩踏, 震荡轮动试盘
    score: float             # 0 - 100


@dataclass(frozen=True)
class MacroRegimeResult:
    """宏观大盘与全市场情绪综合研判结果。"""
    trade_date: str
    composite_score: float             # 综合评分 0 - 100
    is_gate_open: bool                 # 情绪闸门是否放行
    macro_regime_label: str            # 综合状态标签
    macro_trend_regime: str            # 大盘宏观趋势
    speculative_regime: str            # 短线投机状态
    resonance_type: str                # 共振/背离类型
    suggested_position_cap_pct: int    # 建议仓位上限 (0 - 100)
    gate_description: str              # 终端展示描述
    index_metrics: IndexTrendMetrics
    breadth_metrics: MarketBreadthMetrics
    volume_metrics: MarketVolumeMetrics
    speculative_metrics: SpeculativeMetrics
    risk_warnings: list[str] = field(default_factory=list)


class MacroRegimeEngine:
    """宏观大盘与全市场情绪多维量化引擎。"""

    def evaluate(
        self,
        trade_date: str,
        index_daily_df: pd.DataFrame,
        market_stat_dict: dict[str, Any],
        ladder_overview: Any,
        secondary_index_df: pd.DataFrame | None = None,
    ) -> MacroRegimeResult:
        """多维交叉验证并评估宏观大盘闸门。

        参数:
            trade_date: 评估日期 (YYYYMMDD)
            index_daily_df: 上证指数日线数据 (包含 open, high, low, close, amount, pct_chg, 倒序排列)
            market_stat_dict: 全市场统计字典 (up_count, down_count, neutral_count, total_amount)
            ladder_overview: 连板天梯概览对象 (含 space_board_level, tickers, zt, dt, broken_rate)
            secondary_index_df: 辅助参考指数 (如创业板指)
        """
        # 1. 维度 1: 大盘指数趋势与均线结构 (35%)
        index_metrics = self._calc_index_metrics(index_daily_df)

        # 2. 维度 2: 全市场广度 (30%)
        breadth_metrics = self._calc_breadth_metrics(market_stat_dict)

        # 3. 维度 3: 全市场量能与流动性 (15%)
        volume_metrics = self._calc_volume_metrics(market_stat_dict, index_daily_df, index_metrics)

        # 4. 维度 4: 超短连板投机水温 (20%)
        spec_metrics = self._calc_speculative_metrics(ladder_overview, index_metrics, breadth_metrics)

        # 5. 维度 5: 宏观与微观的“共振 / 背离”交叉判定
        resonance_type, macro_label, warnings, position_cap, is_gate_open = self._evaluate_cross_resonance(
            index_metrics=index_metrics,
            breadth_metrics=breadth_metrics,
            volume_metrics=volume_metrics,
            spec_metrics=spec_metrics,
        )

        # 综合加权评分 (0 - 100)
        composite_score = round(
            index_metrics.score * 0.35 +
            breadth_metrics.score * 0.30 +
            volume_metrics.score * 0.15 +
            spec_metrics.score * 0.20,
            1,
        )

        # 如果属于极端背离 (大盘阴跌但妖股逆势抱团)，强制封锁闸门防线
        if resonance_type == "DIVERGENCE_SPECULATIVE_CLING":
            is_gate_open = False
            position_cap = min(position_cap, 20)

        # 构建买方穿透式闸门描述文本
        gate_desc = self._build_gate_description(
            is_gate_open=is_gate_open,
            composite_score=composite_score,
            macro_label=macro_label,
            position_cap=position_cap,
            index_m=index_metrics,
            breadth_m=breadth_metrics,
            volume_m=volume_metrics,
            spec_m=spec_metrics,
            warnings=warnings,
        )

        return MacroRegimeResult(
            trade_date=trade_date,
            composite_score=composite_score,
            is_gate_open=is_gate_open,
            macro_regime_label=macro_label,
            macro_trend_regime=index_metrics.trend_regime,
            speculative_regime=spec_metrics.speculative_regime,
            resonance_type=resonance_type,
            suggested_position_cap_pct=position_cap,
            gate_description=gate_desc,
            index_metrics=index_metrics,
            breadth_metrics=breadth_metrics,
            volume_metrics=volume_metrics,
            speculative_metrics=spec_metrics,
            risk_warnings=warnings,
        )

    # ─────────────────────────────────────────────────────────────
    # 内部量化计算子模块
    # ─────────────────────────────────────────────────────────────

    def _calc_index_metrics(self, df: pd.DataFrame) -> IndexTrendMetrics:
        """计算大盘基准均线结构与连跌趋势。"""
        if df.empty or len(df) < 5:
            return IndexTrendMetrics(
                code="sh000001",
                name="上证指数",
                close=0.0,
                pct_chg=0.0,
                ma5=0.0,
                ma10=0.0,
                ma20=0.0,
                ma60=0.0,
                ma_alignment="TANGLED",
                consecutive_down_days=0,
                consecutive_up_days=0,
                ret_5d=0.0,
                ret_20d=0.0,
                trend_regime="数据缺失",
                score=50.0,
            )

        # df 约定按日期倒序 (第 0 行是最新的)
        # 转为正序计算均线
        asc_df = df.iloc[::-1].copy().reset_index(drop=True)
        closes = asc_df["close"]

        c_now = float(closes.iloc[-1])
        pct_chg = float(asc_df["pct_chg"].iloc[-1]) if "pct_chg" in asc_df.columns else 0.0

        ma5 = float(closes.rolling(5).mean().iloc[-1]) if len(closes) >= 5 else c_now
        ma10 = float(closes.rolling(10).mean().iloc[-1]) if len(closes) >= 10 else ma5
        ma20 = float(closes.rolling(20).mean().iloc[-1]) if len(closes) >= 20 else ma10
        ma60 = float(closes.rolling(min(60, len(closes))).mean().iloc[-1]) if len(closes) >= 20 else ma20

        # 连续涨跌天数
        consec_down = 0
        consec_up = 0
        for i in range(len(asc_df) - 1, -1, -1):
            row_chg = float(asc_df["pct_chg"].iloc[i]) if "pct_chg" in asc_df.columns else 0.0
            if row_chg < -0.05:  # 明确收阴
                if consec_up > 0:
                    break
                consec_down += 1
            elif row_chg > 0.05:  # 明确收阳
                if consec_down > 0:
                    break
                consec_up += 1
            else:
                break

        # 区间收益
        c_5d_ago = float(closes.iloc[-5]) if len(closes) >= 5 else float(closes.iloc[0])
        ret_5d = round((c_now - c_5d_ago) / c_5d_ago * 100.0, 2)

        c_20d_ago = float(closes.iloc[-20]) if len(closes) >= 20 else float(closes.iloc[0])
        ret_20d = round((c_now - c_20d_ago) / c_20d_ago * 100.0, 2)

        # 均线排列判断
        if c_now > ma5 and (len(closes) < 10 or ma5 >= ma20):
            ma_alignment = "BULL"
        elif c_now < ma5 and (len(closes) < 10 or ma5 <= ma20):
            ma_alignment = "BEAR"
        else:
            ma_alignment = "TANGLED"

        # 趋势定性与打分 (0 - 100)
        score = 50.0
        if c_now < ma20 and (ma_alignment == "BEAR" or consec_down >= 2):
            # 明确破位 MA20 且连跌或空头排列
            trend_regime = "破位阴跌探底"
            score = 25.0
            if consec_down >= 3:
                score -= 10.0
            if c_now < ma60:
                score -= 5.0
            if ret_5d < -2.0:
                score -= 5.0
        elif c_now >= ma20:
            if consec_down >= 2 or (ret_5d > 4.0 and pct_chg < -0.2):
                trend_regime = "高位滞涨见顶"
                score = 55.0
            else:
                trend_regime = "多头主升加速"
                score = 80.0
        else:
            trend_regime = "均线纠缠震荡"
            score = 45.0
            if consec_down >= 2:
                score -= 10.0

        score = max(0.0, min(100.0, score))

        return IndexTrendMetrics(
            code="sh000001",
            name="上证指数",
            close=round(c_now, 2),
            pct_chg=round(pct_chg, 2),
            ma5=round(ma5, 2),
            ma10=round(ma10, 2),
            ma20=round(ma20, 2),
            ma60=round(ma60, 2),
            ma_alignment=ma_alignment,
            consecutive_down_days=consec_down,
            consecutive_up_days=consec_up,
            ret_5d=ret_5d,
            ret_20d=ret_20d,
            trend_regime=trend_regime,
            score=score,
        )

    def _calc_breadth_metrics(self, stat_dict: dict[str, Any]) -> MarketBreadthMetrics:
        """计算全市场广度与涨跌家数比率。"""
        up = int(stat_dict.get("up_count", 0))
        down = int(stat_dict.get("down_count", 0))
        neutral = int(stat_dict.get("neutral_count", 0))
        total = int(stat_dict.get("total_count", up + down + neutral))

        # 容错：若误乘 10 倍，按真实 A 股 5000+ 家规模自动归一
        if total > 15000:
            up = round(up / 10)
            down = round(down / 10)
            neutral = round(neutral / 10)
            total = round(total / 10)

        effective_total = up + down
        ratio = (up / effective_total) if effective_total > 0 else 0.5

        if ratio < 0.20:
            regime = "极端普跌冰点"
            score = 15.0 + (ratio / 0.20) * 15.0  # 15 ~ 30
        elif ratio < 0.40:
            regime = "弱势退潮分化"
            score = 30.0 + ((ratio - 0.20) / 0.20) * 20.0  # 30 ~ 50
        elif ratio < 0.60:
            regime = "结构分化平衡"
            score = 50.0 + ((ratio - 0.40) / 0.20) * 20.0  # 50 ~ 70
        else:
            regime = "普涨赚钱活跃"
            score = 70.0 + min(30.0, ((ratio - 0.60) / 0.40) * 30.0)  # 70 ~ 100

        return MarketBreadthMetrics(
            up_count=up,
            down_count=down,
            neutral_count=neutral,
            total_count=total,
            breadth_ratio=round(ratio, 3),
            breadth_regime=regime,
            score=round(score, 1),
        )

    def _calc_volume_metrics(
        self,
        stat_dict: dict[str, Any],
        daily_df: pd.DataFrame,
        index_m: IndexTrendMetrics,
    ) -> MarketVolumeMetrics:
        """计算全市场成交额及量能背离特征。"""
        tot_amt = float(stat_dict.get("total_amount", 0.0))

        # 估算 5 日均量 (若大盘日线有 amount，取 5 日均值比率)
        avg_amt_5d = tot_amt
        amt_ratio = 1.0
        if not daily_df.empty and len(daily_df) >= 5 and "amount" in daily_df.columns:
            recent_amts = daily_df["amount"].head(5)
            if recent_amts.mean() > 0:
                amt_ratio = float(recent_amts.iloc[0] / recent_amts.mean())
                avg_amt_5d = tot_amt / amt_ratio if amt_ratio > 0 else tot_amt

        # 量价关系分析
        is_down = index_m.pct_chg < -0.1
        is_up = index_m.pct_chg > 0.1

        if is_down and amt_ratio > 1.15:
            regime = "放量杀跌"
            score = 25.0
        elif is_down and amt_ratio < 0.85:
            regime = "缩量阴跌"
            score = 30.0
        elif is_up and amt_ratio > 1.15:
            regime = "放量拉升"
            score = 85.0
        elif is_up and amt_ratio < 0.85:
            regime = "缩量弱反"
            score = 45.0
        else:
            regime = "量能平稳"
            score = 50.0

        return MarketVolumeMetrics(
            total_amount=round(tot_amt, 2),
            avg_amount_5d=round(avg_amt_5d, 2),
            amount_ratio=round(amt_ratio, 2),
            volume_regime=regime,
            score=score,
        )

    def _calc_speculative_metrics(
        self,
        overview: Any,
        index_m: IndexTrendMetrics,
        breadth_m: MarketBreadthMetrics,
    ) -> SpeculativeMetrics:
        """评估短线游资投机水温，精准辨识妖股逆势抱团。"""
        space = getattr(overview, "space_board_level", 0) if overview else 0
        tickers = getattr(overview, "space_board_tickers", []) if overview else []
        zt = getattr(overview, "total_limit_up_count", 0) if overview else 0
        dt = getattr(overview, "total_limit_down_count", 0) if overview else 0
        broken = getattr(overview, "total_broken_count", 0) if overview else 0
        bk_rate = getattr(overview, "broken_rate_pct", 0.0) if overview else 0.0

        # 归一化容错
        if zt > 500:
            zt = round(zt / 10)
        if dt > 500:
            dt = round(dt / 10)

        # 核心判断：大盘弱势但个股打板很高的背离场景 (弱市妖股逆势抱团)
        is_macro_bear = (index_m.trend_regime == "破位阴跌探底" or breadth_m.breadth_regime == "极端普跌冰点")
        
        score = 50.0
        if is_macro_bear and space >= 4:
            regime = "弱市妖股逆势抱团 (流动性避险博傻)"
            # 妖股活跃但后排惨烈，投机得分不宜过高
            score = 35.0
            if dt >= 15 or bk_rate >= 35.0:
                score -= 10.0
        elif dt >= 20 or (space <= 2 and zt <= 25):
            regime = "全线冰点恐慌踩踏"
            score = 15.0
        elif space >= 4 and zt >= 40 and dt <= 8 and bk_rate < 30.0 and not is_macro_bear:
            regime = "短线主升加速发酵"
            score = 85.0
        elif (space >= 4 or zt >= 40) and (dt >= 12 or bk_rate >= 35.0):
            regime = "高位共振放量分歧 (筹码集中派发)"
            score = 40.0
        else:
            regime = "震荡轮动试盘"
            score = 50.0

        return SpeculativeMetrics(
            space_board_level=space,
            space_board_tickers=tickers,
            limit_up_count=zt,
            limit_down_count=dt,
            broken_count=broken,
            broken_rate_pct=bk_rate,
            speculative_regime=regime,
            score=max(0.0, min(100.0, score)),
        )

    def _evaluate_cross_resonance(
        self,
        index_metrics: IndexTrendMetrics,
        breadth_metrics: MarketBreadthMetrics,
        volume_metrics: MarketVolumeMetrics,
        spec_metrics: SpeculativeMetrics,
    ) -> tuple[str, str, list[str], int, bool]:
        """交叉验证矩阵：输出共振类型、宏观标签、风险警示、仓位上限与闸门开关。"""
        warnings: list[str] = []
        index_m = index_metrics
        breadth_m = breadth_metrics
        volume_m = volume_metrics
        spec_m = spec_metrics
        is_macro_bear = (index_m.trend_regime == "破位阴跌探底" or breadth_m.breadth_ratio < 0.25)
        is_macro_bull = (index_m.trend_regime == "多头主升加速" and breadth_m.breadth_ratio >= 0.55)

        # 场景 1: 大盘破位阴跌 + 妖股逆势抱团 (当前市场典型形态)
        if is_macro_bear and spec_m.space_board_level >= 4:
            resonance_type = "DIVERGENCE_SPECULATIVE_CLING"
            macro_label = "【大盘破位阴跌 + 局部妖股逆势抱团】"
            warnings.append(
                f"大盘连跌 {index_m.consecutive_down_days} 日且全市场逾 {breadth_m.down_count} 只股票下跌，"
                f"个别连板股 [{ '、'.join(spec_m.space_board_tickers[:2]) }] 仅为极端存量流动性博傻，"
                f"谨防随时被大盘拖累引发天地板踩踏补跌"
            )
            position_cap = 20
            is_gate_open = False
            return resonance_type, macro_label, warnings, position_cap, is_gate_open

        # 场景 2: 大盘多头 + 短线情绪共振主升
        if is_macro_bull and spec_m.space_board_level >= 3 and spec_m.limit_down_count <= 8:
            resonance_type = "RESONANCE_BULL"
            macro_label = "【大盘与短线情绪共振主升】"
            position_cap = 80
            is_gate_open = True
            return resonance_type, macro_label, warnings, position_cap, is_gate_open

        # 场景 3: 高位共振放量分歧
        if (index_m.close > index_m.ma20 or index_m.ret_5d > 2.0) and (spec_m.limit_down_count >= 12 or spec_m.broken_rate_pct >= 35.0):
            resonance_type = "RESONANCE_HIGH_DISTRIBUTION"
            macro_label = "【高位放量滞涨与获利盘派发】"
            warnings.append(f"短线炸板率高达 {spec_m.broken_rate_pct:.1f}%，跌停 {spec_m.limit_down_count} 家，高位多杀多踩踏扩散")
            position_cap = 30
            is_gate_open = False
            return resonance_type, macro_label, warnings, position_cap, is_gate_open

        # 场景 4: 大盘与情绪全线恐慌冰点
        if is_macro_bear and (spec_m.space_board_level <= 2 or spec_m.limit_down_count >= 15):
            resonance_type = "RESONANCE_BEAR_PANIC"
            macro_label = "【大盘破位与短线全线冰点退潮】"
            warnings.append(f"全市场仅 {breadth_m.up_count} 只个股上涨，系统性亏钱效应蔓延，买盘承接极度脆弱")
            position_cap = 10
            is_gate_open = False
            return resonance_type, macro_label, warnings, position_cap, is_gate_open

        # 场景 5: 结构性震荡轮动
        resonance_type = "CHOPPY_ROTATION"
        macro_label = "【大盘震荡分化与结构轮动】"
        position_cap = 40
        is_gate_open = (breadth_m.breadth_ratio >= 0.40 and index_m.score >= 45.0)
        return resonance_type, macro_label, warnings, position_cap, is_gate_open

    def _build_gate_description(
        self,
        is_gate_open: bool,
        composite_score: float,
        macro_label: str,
        position_cap: int,
        index_m: IndexTrendMetrics,
        breadth_m: MarketBreadthMetrics,
        volume_m: MarketVolumeMetrics,
        spec_m: SpeculativeMetrics,
        warnings: list[str],
    ) -> str:
        """构建专业买方穿透式闸门决断描述文本。"""
        status_icon = "✓ 情绪闸门放行" if is_gate_open else "⚠️ 情绪闸门收紧"
        space_str = "、".join(spec_m.space_board_tickers[:2]) if spec_m.space_board_tickers else "无"
        tot_amt_trillion = volume_m.total_amount / 1e12

        lines = [
            f"{status_icon} (市场处于{macro_label}，宏观综合评分: {composite_score:.0f}/100)",
            f"  • 大盘基准: {index_m.name}({index_m.code}) 收盘 {index_m.close:.2f} ({index_m.pct_chg:+.2f}%)，"
            f"均线处于【{index_m.ma_alignment}】状态 (MA5:{index_m.ma5:.2f} / MA20:{index_m.ma20:.2f})，"
            f"连跌 {index_m.consecutive_down_days} 日，5日累计动量 {index_m.ret_5d:+.2f}%",
            f"  • 全市场广度: 【{breadth_m.breadth_regime}】 上涨 {breadth_m.up_count}家 / 下跌 {breadth_m.down_count}家 "
            f"(涨跌比 {breadth_m.breadth_ratio*100:.1f}%)，全市场总成交 {tot_amt_trillion:.2f}万亿 ({volume_m.volume_regime})",
            f"  • 超短局部生态: 【{spec_m.speculative_regime}】 空间板 {spec_m.space_board_level}板 [{space_str}]，"
            f"涨停 {spec_m.limit_up_count}家 / 跌停 {spec_m.limit_down_count}家 / 炸板 {spec_m.broken_count}家 (炸板率 {spec_m.broken_rate_pct:.1f}%)",
        ]

        if warnings:
            for w in warnings:
                lines.append(f"  • 核心警示: {w}")

        lines.append(f"  • 买方策略决断: 建议总仓位上限严控在【{position_cap}%】以内，严格执行顺势风控纪律")
        return "\n".join(lines)
