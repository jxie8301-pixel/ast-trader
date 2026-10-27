"""A股四维资金博弈矩阵与合力雷达 (Capital Force Matrix).
彻底剔除拟人化大师角色扮演，基于真实客观数据与买方框架，解构标的背后的四大资金主力：
1. 机构力量 (Institutional Focus): 基本盘质地、估值安全垫、中长期资金沉淀
2. 游资合力 (Hot-Money Synergy): 24 一线游资战法匹配、题材主线高度、龙头封板溢价
3. 量化动量 (Quant Momentum): 动量因子金叉、量比异常突破、换手流动性厚度
4. 散户与筹码沉淀 (Retail & Trap Risk): 杀猪盘雷达、股东户数发散度、解禁质押抛压
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from core.red_flags import RedFlagItem


@dataclass
class CapitalDimension:
    dimension_id: str                      # institutional, hot_money, quant, retail_chip
    dimension_name: str                    # 机构力量, 游资合力, 量化动量, 散户与筹码
    status: str                            # BULL (多头做多), NEUTRAL (中性整理), BEAR (偏空流出), VETO (一票否决)
    score: float                           # 维度得分 (0~100)
    summary: str                           # 核心客观判定事实
    key_metrics: dict[str, Any] = field(default_factory=dict) # 核心量化指标字典


@dataclass
class CapitalMatrixResult:
    synergy_score: float                   # 四维资金加权综合合力得分 (0~100)
    matrix_verdict: str                    # 综合资金裁决
    dominant_force: str                    # 当前盘面主导资金力量
    bull_catalyst: str                     # 多方核心进攻依据
    bear_risk: str                         # 空方主要防守风险
    dimensions: list[CapitalDimension]


class CapitalMatrixRadar:
    """四维资金博弈雷达分析引擎。"""

    def evaluate(
        self,
        quote: dict[str, Any],
        momentum: dict[str, Any],
        flags: list[RedFlagItem],
        trap_warnings: list[str],
        matched_personas: list[str],
        concepts: list[str],
        ladder_info: dict[str, Any] | None = None,
        money_flow: dict[str, Any] | None = None,
        lhb_records: list[dict[str, Any]] | None = None,
        governance_info: dict[str, Any] | None = None,
    ) -> CapitalMatrixResult:
        close = quote.get("close", 0.0)
        pe = quote.get("pe", 0.0)
        pb = quote.get("pb", 0.0)
        turnover = quote.get("turnover_ratio", 0.0)
        total_mv = quote.get("total_mv", 0.0)
        vol_ratio = momentum.get("volume_ratio", 1.0)
        is_bullish = momentum.get("is_bullish_ma", False)
        bias = momentum.get("ma5_bias", 0.0)
        overhead_chips = momentum.get("overhead_chip_pct", 0.0)
        curr_dd = momentum.get("current_drawdown", 0.0)

        fatal_flags = [f for f in flags if f.level == "🔴"]
        high_flags = [f for f in flags if f.level == "🟠"]

        is_leader = ladder_info.get("is_leader", False) if ladder_info else False
        board_level = ladder_info.get("board_level", 1) if ladder_info else 1

        dimensions: list[CapitalDimension] = []

        # ─── 维度 1: 机构力量 (基本盘、估值与机构席位) ───
        inst_buy = sum(r.get("buy_amt", 0.0) for r in (lhb_records or []) if "机构专用" in r.get("seat_name", ""))
        inst_sell = sum(r.get("sell_amt", 0.0) for r in (lhb_records or []) if "机构专用" in r.get("seat_name", ""))
        inst_net_wan = (inst_buy - inst_sell) / 10000.0

        if fatal_flags:
            inst_status = "VETO"
            inst_score = 0.0
            inst_summary = f"触及买方合规红线: {fatal_flags[0].title}，机构仓位强制清空回避"
        elif pe > 0 and pe <= 35 and pb > 0 and pb <= 4.5 and not high_flags:
            inst_status = "BULL"
            inst_score = 80.0
            inst_summary = f"基本面健康 (PE(TTM) {pe:.1f}x / PB {pb:.1f}x)，估值具备安全边际"
            if inst_net_wan > 1000:
                inst_summary += f"，近30日龙虎榜获机构净买入 +{inst_net_wan/100:.1f} 亿元"
                inst_score = min(inst_score + 10.0, 95.0)
        elif pe > 60 or pb > 8.0:
            inst_status = "BEAR"
            inst_score = 35.0
            inst_summary = f"估值偏高 (PE(TTM) {pe:.1f}x / PB {pb:.1f}x)，纯概念溢价，防估值均值回归杀跌"
        else:
            inst_status = "NEUTRAL"
            inst_score = 55.0
            inst_summary = f"估值与财务处于平衡区间 (PE(TTM) {pe:.1f}x / PB {pb:.1f}x)"

        dimensions.append(CapitalDimension(
            dimension_id="institutional",
            dimension_name="机构力量 (基本盘与估值)",
            status=inst_status,
            score=inst_score,
            summary=inst_summary,
            key_metrics={"pe": pe, "pb": pb, "inst_net_wan": inst_net_wan},
        ))

        # ─── 维度 2: 游资与主力资金 (真实资金流与连板地位) ───
        mf = money_flow or {}
        main_net_wan = mf.get("main_net_wan", 0.0)
        super_net_wan = mf.get("super_large_net_wan", 0.0)

        if fatal_flags:
            hm_status = "VETO"
            hm_score = 10.0
            hm_summary = "存在重大合规停牌或立案风险，游资极度规避黑天鹅踩踏"
        elif main_net_wan < -3000:
            hm_status = "BEAR"
            hm_score = 30.0
            hm_summary = f"主力资金显著净流出 (主力净额 {main_net_wan/100:.1f} 亿元，超大单 {super_net_wan/100:.1f} 亿元)，大单逢高派发，短线缺乏承接"
        elif is_leader or board_level >= 2:
            hm_status = "BULL"
            hm_score = 92.0
            hm_summary = f"处于连板梯队前排 ({board_level}板)，龙头效应显著，一线游资大单接力溢价"
        elif main_net_wan > 3000:
            hm_status = "BULL"
            hm_score = 85.0
            hm_summary = f"主力资金强势做多 (主力净额 +{main_net_wan/100:.1f} 亿元)，盘口大单攻击意愿明确"
        elif matched_personas and bool(concepts):
            top_p = matched_personas[:2]
            p_str = "、".join(top_p)
            hm_status = "BULL"
            hm_score = 75.0
            hm_summary = f"题材热点聚焦，契合【{p_str}】战法模型，具备短线试错意愿"
        else:
            hm_status = "NEUTRAL"
            hm_score = 45.0
            hm_summary = f"主力资金表现平淡 (主力净额 {main_net_wan/100:+.1f} 亿元)，未见强势游资合力主导"

        dimensions.append(CapitalDimension(
            dimension_id="hot_money",
            dimension_name="游资与主力 (资金流与梯队)",
            status=hm_status,
            score=hm_score,
            summary=hm_summary,
            key_metrics={
                "main_net_wan": main_net_wan,
                "super_net_wan": super_net_wan,
                "is_leader": is_leader,
                "board_level": board_level,
            },
        ))

        # ─── 维度 3: 量化动量 (量价与流动性) ───
        if is_bullish and vol_ratio >= 1.5 and turnover >= 4.0:
            quant_status = "BULL"
            quant_score = 85.0
            quant_summary = f"均线多头排列，量比 {vol_ratio:.1f} 放量，换手 {turnover:.1f}%，量价呈现积极量化趋势特征"
        elif is_bullish:
            quant_status = "NEUTRAL"
            quant_score = 65.0
            quant_summary = f"均线多头排列但量能平稳 (量比 {vol_ratio:.1f})，动能顺势跟随"
        elif not is_bullish and vol_ratio >= 2.0:
            quant_status = "BEAR"
            quant_score = 25.0
            quant_summary = f"破位放量杀跌 (量比 {vol_ratio:.1f})，量价动能彻底破位"
        else:
            quant_status = "BEAR"
            quant_score = 40.0
            quant_summary = f"均线空头排列，流动性趋缓 (换手 {turnover:.1f}%，量比 {vol_ratio:.1f})，量价动能承压"

        dimensions.append(CapitalDimension(
            dimension_id="quant",
            dimension_name="量化动量 (量价与流动性)",
            status=quant_status,
            score=quant_score,
            summary=quant_summary,
            key_metrics={
                "volume_ratio": vol_ratio,
                "turnover_ratio": turnover,
                "is_bullish_ma": is_bullish,
                "bias": bias,
            },
        ))

        # ─── 维度 4: 散户与筹码沉淀 (结构与雷达排查) ───
        holder_change = (governance_info or {}).get("holder_change_pct")

        if len(trap_warnings) >= 2 or any("高比例质押" in f.title for f in fatal_flags):
            retail_status = "VETO"
            retail_score = 15.0
            retail_summary = f"高危杀猪盘诱多风险: {trap_warnings[0] if trap_warnings else '高位抛压'}，散户筹码面临踩踏风险"
        elif overhead_chips > 50.0:
            retail_status = "BEAR"
            retail_score = 35.0
            retail_summary = f"上方套牢筹码密集 ({overhead_chips:.1f}%)，阶段回撤 {curr_dd:.1f}%，解套抛压沉重"
        elif overhead_chips < 20.0 and turnover < 15.0:
            retail_status = "BULL"
            retail_score = 80.0
            retail_summary = f"上方套牢筹码仅 {overhead_chips:.1f}%，筹码锁定优良，无沉重解套抛压"
        elif turnover > 25.0:
            retail_status = "NEUTRAL"
            retail_score = 50.0
            retail_summary = f"换手率达 {turnover:.1f}%，高位筹码松动激化，获利盘集中兑现"
        else:
            retail_status = "NEUTRAL"
            retail_score = 60.0
            retail_summary = f"筹码结构中性整理 (上方套牢盘 {overhead_chips:.1f}%，换手 {turnover:.1f}%)"

        if holder_change is not None:
            if holder_change < -3.0:
                retail_summary += f" (最新股东户数下降 {abs(holder_change):.1f}%，筹码加速集中)"
            elif holder_change > 8.0:
                retail_summary += f" (最新股东户数增加 +{holder_change:.1f}%，筹码趋于发散)"

        dimensions.append(CapitalDimension(
            dimension_id="retail_chip",
            dimension_name="散户与筹码 (结构与雷达排查)",
            status=retail_status,
            score=retail_score,
            summary=retail_summary,
            key_metrics={"trap_warnings": trap_warnings, "overhead_chips": overhead_chips, "holder_change": holder_change},
        ))

        # ─── 加权综合评分与主导力量研判 ───
        # 权重配比: 机构 25%, 游资 35%, 量化 25%, 筹码 15%
        weights = [0.25, 0.35, 0.25, 0.15]
        weighted_score = sum(d.score * w for d, w in zip(dimensions, weights))

        # 判断一票否决
        has_veto = any(d.status == "VETO" for d in dimensions)
        if has_veto:
            synergy_score = min(weighted_score, 20.0)
            verdict = "🚫 资金铁律一票否决 (触及根本性财务造假或恶性杀猪盘，全线资金回避)"
            dominant = "空头绝对出逃"
        elif weighted_score >= 80.0:
            synergy_score = weighted_score
            verdict = "🔥 机构与游资共振主升 (基本面扎实 + 游资接力 + 量化扫单，形成合力主攻)"
            dominant = "一线游资与量化多头合力"
        elif weighted_score >= 60.0:
            synergy_score = weighted_score
            verdict = "⚖️ 游资短线进攻但分歧尚存 (短线博弈占优，建议遵循实战战术高抛低吸)"
            dominant = "短线游资分歧进攻"
        else:
            synergy_score = weighted_score
            verdict = "❄️ 资金观望整理态势 (缺乏主导合力，动能尚未聚集，维持中性底仓)"
            dominant = "存量资金博弈"

        # 提炼多方进攻与空方防守核心论据
        bull_items = [d.summary for d in dimensions if d.status == "BULL"]
        bear_items = [d.summary for d in dimensions if d.status in ("BEAR", "VETO")]

        bull_cat = "；".join(bull_items[:2]) if bull_items else "多头缺乏强劲的增量合力，资金以小波段试仓为主。"
        bear_rk = "；".join(bear_items[:2]) if bear_items else "筹码锁定良好，未见机构砸盘或量化破位做空迹象。"

        return CapitalMatrixResult(
            synergy_score=round(synergy_score, 1),
            matrix_verdict=verdict,
            dominant_force=dominant,
            bull_catalyst=bull_cat,
            bear_risk=bear_rk,
            dimensions=dimensions,
        )
