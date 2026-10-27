"""Five-node judgment chain synthesizer for AST-Trader."""
from __future__ import annotations

from typing import Any

import config
from lint.validator import LintValidator
from .red_flags import LEVEL_FATAL, RedFlagItem, get_top3_risks, has_fatal_red_flags


class JudgmentChainRunner:
    """五节点因果判断链执行器。"""

    def __init__(self) -> None:
        self.validator = LintValidator()

    def run(
        self,
        ticker: str,
        name: str,
        trade_date: str,
        quote: dict[str, Any],
        momentum: dict[str, Any],
        flags: list[RedFlagItem],
        matched_youzi: list[dict[str, Any]],
        trap_warnings: list[str],
    ) -> dict[str, Any]:
        """按因果判断链合成决断卡。"""
        price = quote.get("close", 0.0)
        ma5 = momentum.get("ma5", price)
        ma20 = momentum.get("ma20", price)

        # ─── 节点 ① 质地（成色与造假概率）───
        fatal_quality = [f for f in flags if f.level == LEVEL_FATAL and f.node == "quality"]
        high_quality = [f for f in flags if f.level == LEVEL_FATAL or (f.level == "🟠" and f.node == "quality")]
        if fatal_quality:
            quality_verdict = f"✗ 严重暴雷风险: {fatal_quality[0].title}"
        elif high_quality:
            quality_verdict = f"⚠️ 存在财务瑕疵: {high_quality[0].title}"
        else:
            quality_verdict = "✓ 财务底子稳健，未见显著造假与异常应计异象"

        # ─── 节点 ② 状态（动能突破与催化）───
        vr = momentum.get("volume_ratio", 1.0)
        is_bull = momentum.get("is_bullish_ma", False)
        bias = momentum.get("ma5_bias", 0.0)

        if is_bull and vr >= 1.5:
            state_verdict = f"放量主升中 (量比 {vr:.1f}，均线多头排列，乖离率 {bias:+.1f}%)"
        elif is_bull:
            state_verdict = f"多头趋势但缩量整理 (均线多头，量比 {vr:.1f})"
        else:
            state_verdict = f"均线空头排列/破位形态 (MA5={ma5:.2f} < MA20={ma20:.2f})"

        # ─── 节点 ③ 赔率（空间与估值溢价）───
        tail_price = round(ma20 * 0.95, 2)  # 下方强均线防线作为第一安全底
        downside_pct = round((price - tail_price) / max(price, 1e-4) * 100.0, 1)
        if downside_pct > 20.0:
            odds_verdict = f"赔率偏低/情绪透支严重 (距离下方均线支撑 {tail_price:.2f} 元有 -{downside_pct}% 空间)"
        else:
            odds_verdict = f"赔率尚可 (下方强支撑位 {tail_price:.2f} 元，下行潜在空间约 -{downside_pct}%)"

        # ─── 节点 ④ 路径（左尾回撤与席位属性）───
        fatal_path = [f for f in flags if f.level == LEVEL_FATAL and f.node == "path"]
        youzi_desc = ", ".join(y["youzi_name"] for y in matched_youzi[:2]) if matched_youzi else "无知名游资上榜"
        if fatal_path:
            path_verdict = f"🔴 存在致命治理左尾风险: {fatal_path[0].title} (知名席位: {youzi_desc})"
        elif trap_warnings:
            path_verdict = f"⚠️ 警惕杀猪盘舆情诱多: {trap_warnings[0]} (知名席位: {youzi_desc})"
        else:
            path_verdict = f"筹码路径相对健康，重点关注日内承接 (知名席位: {youzi_desc})"

        # ─── 节点 ⑤ 决策（档位与退出线）───
        is_fatal = has_fatal_red_flags(flags)
        if is_fatal:
            decision_gear = "回避"
            position_cap = 0.0
            invalidation_line = "由于命中致命红旗，禁止建仓！"
        elif not is_bull or downside_pct > 25.0 or trap_warnings:
            decision_gear = "观察"
            position_cap = 0.0
            invalidation_line = f"跌破 5 日线 {ma5:.2f} 元未收回即放弃"
        else:
            decision_gear = "买入"
            position_cap = config.MAX_SINGLE_POSITION
            invalidation_line = f"开盘跌破 MA5 ({ma5:.2f} 元) 或日内跌破分时均线 -3% 无条件止损平仓"

        card = {
            "ticker": ticker,
            "name": name,
            "trade_date": trade_date,
            "price": price,
            "pct_chg": quote.get("pct_chg", 0.0),
            "quality_verdict": quality_verdict,
            "state_verdict": state_verdict,
            "odds_verdict": odds_verdict,
            "path_verdict": path_verdict,
            "decision_gear": decision_gear,
            "position_cap": position_cap,
            "invalidation_line": invalidation_line,
            "top3_risks": [f.to_dict() for f in get_top3_risks(flags)],
            "all_flags": [f.to_dict() for f in flags],
            "matched_youzi": matched_youzi,
            "trap_warnings": trap_warnings,
        }

        # 门控校验 (若违规自动修正)
        ok, findings = self.validator.validate(card, flags)
        if not ok:
            # 严格强制修正
            if has_fatal_red_flags(flags):
                card["decision_gear"] = "回避"
                card["position_cap"] = 0.0

        return card
