"""Famous A-share Youzi (游资) seat encyclopedia and capacity matcher."""
from __future__ import annotations

from typing import Any

# 核心知名游资及其关联常用营业部
YOUZI_SEATS_DB: dict[str, dict[str, Any]] = {
    "章盟主": {
        "style": "趋势大票、龙头连板、波段加仓",
        "min_market_cap_yi": 50.0,
        "max_market_cap_yi": 2000.0,
        "seats": [
            "中信证券股份有限公司杭州延安路证券营业部",
            "国泰君安证券股份有限公司上海江苏路证券营业部",
            "海通证券股份有限公司绍兴劳动路证券营业部",
            "中信证券股份有限公司上海溧阳路证券营业部",
        ],
    },
    "赵老哥": {
        "style": "主升浪打板、八年一万倍、接力二板三板",
        "min_market_cap_yi": 20.0,
        "max_market_cap_yi": 300.0,
        "seats": [
            "中国银河证券股份有限公司绍兴证券营业部",
            "华泰证券股份有限公司浙江分公司",
            "浙商证券股份有限公司绍兴分公司",
        ],
    },
    "方新侠": {
        "style": "大格局、主升浪锁仓、重仓硬推",
        "min_market_cap_yi": 80.0,
        "max_market_cap_yi": 1500.0,
        "seats": [
            "中信证券股份有限公司西安朱雀大街证券营业部",
            "兴业证券股份有限公司陕西分公司",
        ],
    },
    "炒股养家": {
        "style": "情绪博弈、分歧转一致、排一字通道",
        "min_market_cap_yi": 25.0,
        "max_market_cap_yi": 400.0,
        "seats": [
            "华鑫证券有限责任公司上海宛平南路证券营业部",
            "华鑫证券有限责任公司上海茅台路证券营业部",
            "华鑫证券有限责任公司宁波大庆南路证券营业部",
        ],
    },
    "余哥 / 宁波桑田路": {
        "style": "高位纯接力、超短暴力做 T",
        "min_market_cap_yi": 15.0,
        "max_market_cap_yi": 250.0,
        "seats": [
            "国盛证券有限责任公司宁波桑田路证券营业部",
            "中信证券股份有限公司诸暨西施大街证券营业部",
        ],
    },
    "机构专用": {
        "style": "基本面抱团、趋势中军、左侧建仓",
        "min_market_cap_yi": 100.0,
        "max_market_cap_yi": 10000.0,
        "seats": ["机构专用"],
    },
    "量化知名席位 (量化打板/做T)": {
        "style": "融券对冲、日内高频做T、隔夜砸盘",
        "min_market_cap_yi": 30.0,
        "max_market_cap_yi": 1000.0,
        "seats": [
            "中国国际金融股份有限公司上海分公司",
            "华泰证券股份有限公司总部",
            "中信证券股份有限公司总部",
        ],
    },
}


class SeatMatcher:
    """游资席位穿透与容量匹配器。"""

    def __init__(self) -> None:
        pass

    def match_seats(self, lhb_records: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """将龙虎榜营业部名称与知名游资库匹配。"""
        matched = []
        for rec in lhb_records:
            seat_name = rec.get("seat_name", "")
            if not seat_name:
                continue
            for youzi_name, info in YOUZI_SEATS_DB.items():
                for s in info["seats"]:
                    if s in seat_name or seat_name in s:
                        matched.append({
                            "youzi_name": youzi_name,
                            "style": info["style"],
                            "seat_name": seat_name,
                            "net_amt": rec.get("net_amt", 0.0),
                            "buy_amt": rec.get("buy_amt", 0.0),
                            "trade_date": rec.get("trade_date", ""),
                        })
                        break
        return matched

    def check_capacity(self, youzi_name: str, market_cap_yi: float) -> bool:
        """检查市值是否在游资的常规运作射程内。"""
        info = YOUZI_SEATS_DB.get(youzi_name)
        if not info:
            return True
        return info["min_market_cap_yi"] <= market_cap_yi <= info["max_market_cap_yi"]


def evaluate_lhb_dump_risk(matched_or_records: list[dict[str, Any]] | None) -> tuple[bool, str]:
    """评估龙虎榜席位中的量化高频打板砸盘风险 (提示性预警)."""
    if not matched_or_records:
        return False, ""

    quant_count = 0
    has_institution = False

    for item in matched_or_records:
        y_name = item.get("youzi_name", "")
        s_name = item.get("seat_name", "")
        if "量化" in y_name or any(qs in s_name for qs in ("中金上海分公司", "华泰证券总部", "中信证券总部")):
            quant_count += 1
        if "机构专用" in y_name or "机构专用" in s_name:
            has_institution = True

    if quant_count >= 1 and not has_institution:
        warning = (
            f"游资博弈警示: 龙虎榜检测到知名量化打板高频席位(命中 {quant_count} 家)，"
            "缺乏机构中长线锁仓，次日 9:35 前防范抢跑核按钮砸盘风险，切忌盲目追高，建议观察分时承接后再行动 (提示性预警，未阻断)"
        )
        return True, warning

    return False, ""

