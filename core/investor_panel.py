"""六大投资流派陪审团与多空激辩盲盒机制 (严格对齐 UZI-Skill Investor Panel)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from core.red_flags import RedFlagItem


@dataclass
class JurorVote:
    juror_id: str
    juror_name: str
    school: str              # 价值(A), 成长(B), 宏观(C), 量化(D), 空头(E), 游资(F)
    vote: str                # BUY (看多), HOLD (观望/中立), VETO (一票否决/回避)
    comment: str             # 原生签名金句与实操点评
    hard_score: float        # 硬性指标契合度 (0~100)


@dataclass
class PanelReviewResult:
    total_votes: int
    buy_votes: int
    hold_votes: int
    veto_votes: int
    consensus_pct: float     # 赞成率 / 共识度
    panel_verdict: str       # 评审团总评 (强烈共识做多, 分歧博弈, 铁律否决规避)
    bull_argument: str       # 核心多方代表论据
    bear_argument: str       # 核心空方代表论据
    votes: list[JurorVote]


class InvestorPanelJury:
    """模拟全球顶级投资大师与 A 股一线游资构成的多流派评审团。"""

    def evaluate(
        self,
        quote: dict[str, Any],
        momentum: dict[str, Any],
        flags: list[RedFlagItem],
        trap_warnings: list[str],
        matched_personas: list[str],
        concepts: list[str],
    ) -> PanelReviewResult:
        close = quote.get("close", 0.0)
        pe = quote.get("pe", 0.0)
        pb = quote.get("pb", 0.0)
        turnover = quote.get("turnover_ratio", 0.0)
        is_bullish = momentum.get("is_bullish_ma", False)
        volume_ratio = momentum.get("volume_ratio", 1.0)
        fatal_flags = [f for f in flags if f.level == "🔴"]

        votes: list[JurorVote] = []

        # ─── School A · 价值派 ───
        # 巴菲特
        if fatal_flags:
            votes.append(JurorVote(
                juror_id="buffett",
                juror_name="沃伦·巴菲特 (Warren Buffett)",
                school="A·价值派",
                vote="VETO",
                comment=f"存在根本性财务红旗 ({fatal_flags[0].title})，不在我们的能力圈内。永远不要亏损！",
                hard_score=0.0,
            ))
        elif pe > 0 and pe <= 30 and pb > 0 and pb <= 4:
            votes.append(JurorVote(
                juror_id="buffett",
                juror_name="沃伦·巴菲特 (Warren Buffett)",
                school="A·价值派",
                vote="BUY",
                comment=f"PE {pe}x、PB {pb}x 在合理范围内，财务底色稳健，是经得起时间考验的商业标的。",
                hard_score=85.0,
            ))
        else:
            votes.append(JurorVote(
                juror_id="buffett",
                juror_name="沃伦·巴菲特 (Warren Buffett)",
                school="A·价值派",
                vote="HOLD",
                comment=f"PE {pe}x 偏贵或缺乏足够的安全边际，等别人恐惧时再看。",
                hard_score=40.0,
            ))

        # 查理·芒格
        if fatal_flags or trap_warnings:
            votes.append(JurorVote(
                juror_id="munger",
                juror_name="查理·芒格 (Charlie Munger)",
                school="A·价值派",
                vote="VETO",
                comment="反过来想——这家企业最可能怎么死？雷点已经暴露，我决不去自取灭亡的地方！",
                hard_score=0.0,
            ))
        else:
            votes.append(JurorVote(
                juror_id="munger",
                juror_name="查理·芒格 (Charlie Munger)",
                school="A·价值派",
                vote="HOLD" if pe > 35 else "BUY",
                comment="未发现操纵与造假迹象。只要管理层诚实、数学逻辑算得清，就值得跟踪。",
                hard_score=75.0 if pe <= 35 else 50.0,
            ))

        # ─── School B · 成长派 ───
        # 彼得·林奇
        if is_bullish and volume_ratio >= 1.2:
            votes.append(JurorVote(
                juror_id="lynch",
                juror_name="彼得·林奇 (Peter Lynch)",
                school="B·成长派",
                vote="BUY",
                comment="放量右侧突破，赛道具备现实业务场景支撑，兼具成长势头与市场认知扩张。",
                hard_score=88.0,
            ))
        else:
            votes.append(JurorVote(
                juror_id="lynch",
                juror_name="彼得·林奇 (Peter Lynch)",
                school="B·成长派",
                vote="HOLD",
                comment="动能未完全舒展，需要做更多产业链调研以确认成长拐点。",
                hard_score=50.0,
            ))

        # ─── School C · 宏观派 ───
        # 达利欧
        if len(concepts) > 0 and is_bullish:
            votes.append(JurorVote(
                juror_id="dalio",
                juror_name="瑞·达利欧 (Ray Dalio)",
                school="C·宏观派",
                vote="BUY",
                comment="顺应全市场主流叙事与增量流动性扩散方向，符合周期上行阶段的资产特征。",
                hard_score=80.0,
            ))
        else:
            votes.append(JurorVote(
                juror_id="dalio",
                juror_name="瑞·达利欧 (Ray Dalio)",
                school="C·宏观派",
                vote="HOLD",
                comment="流动性分散且无鲜明主线顺周期加持，维持中性配置权重。",
                hard_score=45.0,
            ))

        # ─── School D · 量化派 ───
        # 西蒙斯
        if turnover >= 5.0 and is_bullish and volume_ratio >= 1.5:
            votes.append(JurorVote(
                juror_id="simons",
                juror_name="吉姆·西蒙斯 (Jim Simons)",
                school="D·量化派",
                vote="BUY",
                comment=f"动量指标金叉，换手率 {turnover}% 呈现高流动性厚度，统计套利胜率处于优势区间。",
                hard_score=90.0,
            ))
        else:
            votes.append(JurorVote(
                juror_id="simons",
                juror_name="吉姆·西蒙斯 (Jim Simons)",
                school="D·量化派",
                vote="HOLD",
                comment=f"流动性截面不足或波动率未收敛，量化信号未达显著开仓阈值。",
                hard_score=45.0,
            ))

        # ─── School E · 激进做空派 ───
        # 迈克尔·伯里 / 空头
        if fatal_flags or len(trap_warnings) >= 2:
            reasons = [f.title for f in fatal_flags] + trap_warnings
            votes.append(JurorVote(
                juror_id="burry",
                juror_name="迈克尔·伯里 (Michael Burry)",
                school="E·空头派",
                vote="VETO",
                comment=f"极其醒目的结构性泡沫与暴雷隐患: {reasons[0]}。所有人都在狂欢，但崩塌近在咫尺！",
                hard_score=0.0,
            ))
        else:
            votes.append(JurorVote(
                juror_id="burry",
                juror_name="迈克尔·伯里 (Michael Burry)",
                school="E·空头派",
                vote="HOLD",
                comment="未检测到足以致死的高危财务应计爆点或做空做局信号，空头暂不建仓。",
                hard_score=60.0,
            ))

        # ─── School F · A股超短游资派 ───
        # 游资战队
        if matched_personas and not fatal_flags:
            p_str = "、".join(matched_personas[:2])
            votes.append(JurorVote(
                juror_id="youzi",
                juror_name="A股一线游资战队",
                school="F·游资派",
                vote="BUY",
                comment=f"高度契合【{p_str}】操盘手战法体系！题材聚焦、筹码结构具备接力攻击条件。",
                hard_score=92.0,
            ))
        elif fatal_flags:
            votes.append(JurorVote(
                juror_id="youzi",
                juror_name="A股一线游资战队",
                school="F·游资派",
                vote="VETO",
                comment="游资最忌踩雷停牌，存在致命审计红旗，游资资金坚决回避不封板！",
                hard_score=0.0,
            ))
        else:
            votes.append(JurorVote(
                juror_id="youzi",
                juror_name="A股一线游资战队",
                school="F·游资派",
                vote="HOLD",
                comment="缺乏顶级一线合力席位共振，盘口平淡，暂不属于短线焦点战场。",
                hard_score=40.0,
            ))

        # 汇总统计
        total = len(votes)
        n_buy = sum(1 for v in votes if v.vote == "BUY")
        n_hold = sum(1 for v in votes if v.vote == "HOLD")
        n_veto = sum(1 for v in votes if v.vote == "VETO")
        consensus = round(n_buy / total * 100.0, 1)

        # 辩论双方论点提炼
        buy_comments = [v.comment for v in votes if v.vote == "BUY"]
        veto_or_bear = [v.comment for v in votes if v.vote in ("VETO", "HOLD")]

        bull_arg = "；".join(buy_comments[:2]) if buy_comments else "多头缺乏强劲支撑证据，资金大多处于观望试探状态。"
        bear_arg = "；".join(veto_or_bear[:2]) if veto_or_bear else "空方未见显著反驳依据，下行抛压较轻。"

        if n_veto > 0:
            verdict = "🚫 陪审团一票否决 (存在致命红旗或暴雷风险，严禁开仓)"
        elif consensus >= 65.0:
            verdict = f"🔥 强烈多头共识 (赞成率 {consensus}%，多流派合力主升)"
        elif consensus >= 35.0:
            verdict = f"⚖️ 多空分歧震荡 (赞成率 {consensus}%，多空激烈博弈，建议按战术低吸)"
        else:
            verdict = f"❄️ 观望情绪占优 (赞成率 {consensus}%，未达共识进攻门槛)"

        return PanelReviewResult(
            total_votes=total,
            buy_votes=n_buy,
            hold_votes=n_hold,
            veto_votes=n_veto,
            consensus_pct=consensus,
            panel_verdict=verdict,
            bull_argument=bull_arg,
            bear_argument=bear_arg,
            votes=votes,
        )
