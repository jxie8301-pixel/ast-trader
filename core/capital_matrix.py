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
    ) -> CapitalMatrixResult:
        close = quote.get("close", 0.0)
        pe = quote.get("pe", 0.0)
        pb = quote.get("pb", 0.0)
        turnover = quote.get("turnover_ratio", 0.0)
        total_mv = quote.get("total_mv", 0.0)
        vol_ratio = momentum.get("volume_ratio", 1.0)
        is_bullish = momentum.get("is_bullish_ma", False)
        bias = momentum.get("ma5_bias", 0.0)

        fatal_flags = [f for f in flags if f.level == "🔴"]
        high_flags = [f for f in flags if f.level == "🟠"]

        is_leader = ladder_info.get("is_leader", False) if ladder_info else False
        board_level = ladder_info.get("board_level", 1) if ladder_info else 1

        dimensions: list[CapitalDimension] = []

        # ─── 维度 1: 机构力量 (Institutional Focus) ───
        if fatal_flags:
            inst_status = "VETO"
            inst_score = 0.0
            inst_summary = f"触及买方合规红线: {fatal_flags[0].title}，机构仓位强制清空"
        elif pe > 0 and pe <= 30 and pb > 0 and pb <= 4.0 and not high_flags:
            inst_status = "BULL"
            inst_score = 85.0
            inst_summary = f"财务底子稳健 (PE {pe:.1f}x / PB {pb:.1f}x)，估值具备安全边际，获中长期配置型机构底仓支持"
        elif pe > 60 or pb > 8.0:
            inst_status = "BEAR"
            inst_score = 35.0
            inst_summary = f"估值透支严重 (PE {pe:.1f}x / PB {pb:.1f}x)，纯题材溢价，机构资金逢高减持兑现"
        else:
            inst_status = "NEUTRAL"
            inst_score = 55.0
            inst_summary = f"估值与财务处于合理平衡区间 (PE {pe:.1f}x)，机构以被动跟随和网格对冲为主"

        dimensions.append(CapitalDimension(
            dimension_id="institutional",
            dimension_name="机构力量 (基本盘与估值)",
            status=inst_status,
            score=inst_score,
            summary=inst_summary,
            key_metrics={"pe": pe, "pb": pb, "fatal_count": len(fatal_flags)},
        ))

        # ─── 维度 2: 游资合力 (Hot-Money Synergy) ───
        if matched_personas and not fatal_flags:
            top_p = matched_personas[:2]
            p_str = "、".join(top_p)
            if is_leader or board_level >= 2:
                hm_status = "BULL"
                hm_score = 92.0
                hm_summary = f"梯队核心领涨龙头 ({board_level}板)，高度契合【{p_str}】操盘战法，一线游资大单主升接力"
            else:
                hm_status = "BULL"
                hm_score = 80.0
                hm_summary = f"题材热点聚焦，契合【{p_str}】战法模型，具备短线游资首板试错与套利意愿"
        elif fatal_flags:
            hm_status = "VETO"
            hm_score = 10.0
            hm_summary = "存在停牌暴雷与立案重伤隐患，游资资金极度厌恶黑天鹅，坚决撤离避免封死跌停"
        else:
            hm_status = "NEUTRAL"
            hm_score = 45.0
            hm_summary = "当前尚未形成一线顶级游资共振合力，盘面以散兵游勇轮动为主"

        dimensions.append(CapitalDimension(
            dimension_id="hot_money",
            dimension_name="游资合力 (题材与连板战法)",
            status=hm_status,
            score=hm_score,
            summary=hm_summary,
            key_metrics={
                "matched_personas": matched_personas,
                "is_leader": is_leader,
                "board_level": board_level,
            },
        ))

        # ─── 维度 3: 量化动量 (Quant Momentum) ───
        if is_bullish and vol_ratio >= 1.5 and turnover >= 5.0:
            quant_status = "BULL"
            quant_score = 88.0
            quant_summary = f"均线多头金叉，量比 {vol_ratio:.1f} 异常放大，换手 {turnover:.1f}%，触发量化多头高频扫单"
        elif is_bullish:
            quant_status = "NEUTRAL"
            quant_score = 65.0
            quant_summary = f"趋势向好但量能温和 (量比 {vol_ratio:.1f})，量化资金小幅顺势跟随，未达激进进攻阈值"
        elif not is_bullish and vol_ratio >= 2.0:
            quant_status = "BEAR"
            quant_score = 25.0
            quant_summary = f"破位放量杀跌 (量比 {vol_ratio:.1f})，量化 CTA 与融券策略触发止损甚至融券做空"
        else:
            quant_status = "BEAR"
            quant_score = 40.0
            quant_summary = f"均线空头排列，流动性收缩 (换手 {turnover:.1f}%)，量化信号处于观望或空头区间"

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

        # ─── 维度 4: 散户与筹码沉淀 (Retail & Trap Risk) ───
        if len(trap_warnings) >= 2 or any("高比例质押" in f.title for f in fatal_flags):
            retail_status = "VETO"
            retail_score = 15.0
            retail_summary = f"检测到高危杀猪盘/庄股诱多信号: {trap_warnings[0] if trap_warnings else '高位抛压'}，筹码面临断崖式踩踏"
        elif trap_warnings:
            retail_status = "BEAR"
            retail_score = 40.0
            retail_summary = f"警惕微观筹码异象: {trap_warnings[0]}，散户跟风盘偏重，洗盘分歧加剧"
        elif turnover > 25.0:
            retail_status = "NEUTRAL"
            retail_score = 50.0
            retail_summary = f"单日换手率高达 {turnover:.1f}%，高位筹码剧烈松动，新老资金对倒换手，获利盘有兑现需求"
        else:
            retail_status = "BULL"
            retail_score = 80.0
            retail_summary = "未见异常黑嘴诱多与杀猪盘信号，筹码结构相对稳定，获利浮筹锁定良好"

        dimensions.append(CapitalDimension(
            dimension_id="retail_chip",
            dimension_name="散户与筹码 (结构与雷达排查)",
            status=retail_status,
            score=retail_score,
            summary=retail_summary,
            key_metrics={"trap_warnings": trap_warnings, "turnover": turnover},
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
