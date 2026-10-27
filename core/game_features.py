"""Short-term momentum, volume dynamics, and game-theoretic feature extraction."""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


class GameFeatureExtractor:
    """短线博弈特征提取器。"""

    def __init__(self) -> None:
        pass

    def extract_momentum(self, daily_df: pd.DataFrame) -> dict[str, Any]:
        """从日 K 线中提取量价动能指标（输入 daily_df 必须按日期降序排列）。"""
        if daily_df.empty or len(daily_df) < 5:
            return {
                "ma5": None, "ma10": None, "ma20": None, "is_bullish_ma": False,
                "volume_ratio": 1.0, "consecutive_up_days": 0, "ma5_bias": 0.0
            }

        # 转为升序计算移动平均
        asc = daily_df.sort_values("trade_date").reset_index(drop=True)
        close = asc["close"]
        vol = asc["vol"]

        asc["ma5"] = close.rolling(5).mean()
        asc["ma10"] = close.rolling(10).mean()
        asc["ma20"] = close.rolling(20).mean()

        # 量比: 今日量 / 过去 5 日均量
        vr = float(vol.iloc[-1] / max(vol.iloc[-6:-1].mean(), 1.0)) if len(vol) >= 6 else 1.0

        latest_close = float(close.iloc[-1])
        ma5_val = float(asc["ma5"].iloc[-1]) if not pd.isna(asc["ma5"].iloc[-1]) else latest_close
        ma10_val = float(asc["ma10"].iloc[-1]) if not pd.isna(asc["ma10"].iloc[-1]) else latest_close
        ma20_val = float(asc["ma20"].iloc[-1]) if not pd.isna(asc["ma20"].iloc[-1]) else latest_close

        # 均线多头
        is_bullish = ma5_val >= ma10_val >= ma20_val
        bias_ma5 = round((latest_close - ma5_val) / ma5_val * 100.0, 2)

        # 连阳天数
        pct_series = asc["pct_chg"].to_numpy()
        consec_up = 0
        for p in reversed(pct_series):
            if p and p > 0:
                consec_up += 1
            else:
                break

        # ─── 路径韧性与承压指标 (扛得住吗) ───
        # 1. 过去 60 日最大回撤与距阶段高点回撤
        rolling_max = close.cummax()
        drawdown_series = (close - rolling_max) / rolling_max * 100.0
        max_dd_60d = round(float(drawdown_series.min()), 2)
        peak_close = float(close.max())
        current_dd = round((latest_close - peak_close) / peak_close * 100.0, 2)

        # 2. 上方套牢筹码占比 (成交量高于当前价格的累计成交占比)
        total_vol = float(vol.sum())
        if total_vol > 0:
            overhead_vol = float(vol[close > latest_close].sum())
            overhead_chip_pct = round(overhead_vol / total_vol * 100.0, 1)
        else:
            overhead_chip_pct = 0.0

        # 3. 近 20 日年化波动率
        if len(asc) >= 20 and "pct_chg" in asc.columns:
            ret_20d = asc["pct_chg"].iloc[-20:] / 100.0
            volatility_20d = round(float(ret_20d.std() * np.sqrt(250) * 100.0), 1)
        else:
            volatility_20d = 30.0

        # 4. 支撑与阻力位
        support_level = round(float(close.iloc[-20:].min()), 2) if len(close) >= 20 else round(latest_close * 0.95, 2)
        resistance_level = round(peak_close, 2)

        return {
            "ma5": round(ma5_val, 2),
            "ma10": round(ma10_val, 2),
            "ma20": round(ma20_val, 2),
            "is_bullish_ma": is_bullish,
            "volume_ratio": round(vr, 2),
            "consecutive_up_days": consec_up,
            "ma5_bias": bias_ma5,
            "max_drawdown_60d": max_dd_60d,
            "current_drawdown": current_dd,
            "overhead_chip_pct": overhead_chip_pct,
            "volatility_20d": volatility_20d,
            "support_level": support_level,
            "resistance_level": resistance_level,
        }

    def evaluate_concept_purity(self, concept_name: str, main_business: list[dict[str, Any]]) -> dict[str, Any]:
        """概念纯度透视：计算炒作概念在主营业务中的收入占比与实际成色。"""
        if not main_business:
            return {"purity_ratio": 0.0, "is_pure": False, "comment": "主营构成未披露或暂无相关收入"}

        matched_ratio = 0.0
        matched_items = []
        for item in main_business:
            name = item.get("name", "")
            ratio = float(item.get("ratio", 0.0))
            # 模糊比对
            if any(k in name for k in concept_name if len(k) > 1) or concept_name in name:
                matched_ratio += ratio
                matched_items.append(f"{name}({ratio:.1f}%)")

        if matched_ratio >= 30.0:
            comment = f"核心主营深度契合概念: {', '.join(matched_items)}"
            is_pure = True
        elif matched_ratio > 0:
            comment = f"部分业务涉及概念: {', '.join(matched_items)}，但占比较低"
            is_pure = False
        else:
            comment = "未在主营构成中发现该概念相关实质业务，存在明显蹭概念炒作嫌疑"
            is_pure = False

        return {
            "purity_ratio": round(matched_ratio, 1),
            "is_pure": is_pure,
            "comment": comment,
        }
