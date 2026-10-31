"""8-Signal Pump-and-Dump Trap Detector ported from UZI-Skill (skills/trap-detector).
Strictly implements the 8 signals and scoring thresholds.
"""
from __future__ import annotations

from typing import Any

# 用户输入/新闻关键词加权 (来自 eight-signals.md §用户输入关键词加权)
USER_KEYWORDS: dict[str, int] = {
    "朋友推荐": 1, "群里": 1, "老师": 1, "带我": 1,
    "内幕": 2, "稳赚": 2, "必涨": 1, "翻倍": 1,
    "稳赚不赔": 2, "包赚": 2, "重大利好": 1, "主力建仓完毕": 1,
    "最后上车机会": 1, "知情人爆料": 2,
}

# 8 大杀猪盘检测信号定义 (来自 eight-signals.md)
TRAP_SIGNALS_DEF = [
    {
        "id": 1,
        "name": "大量低质量账号同时推荐",
        "description": "社交媒体/社区集中出现短时间内相似口径的强烈荐股内容",
        "keywords": ["强烈推荐", "必涨", "内部消息", "暴涨", "重大利好"],
    },
    {
        "id": 2,
        "name": "推荐话术模板化",
        "description": "使用'即将爆发'、'目标翻倍'、'最后上车机会'等高度套路化话术",
        "keywords": ["即将爆发", "目标翻倍", "最后上车机会", "主力建仓完毕", "错过等十年"],
    },
    {
        "id": 3,
        "name": "付费社群/VIP直播间引流",
        "description": "内容附带加微信、进交流群、VIP 直播间、跟单老师",
        "keywords": ["微信群", "进群", "VIP直播", "老师带单", "内部通道", "直播间"],
    },
    {
        "id": 4,
        "name": "基本面与热度脱节",
        "description": "公司亏损或 ROE < 5% 或严重瑕疵，但讨论热度急剧飙升",
        "keywords": ["亏损", "ST", "绩差", "问询函", "立案调查"],
    },
    {
        "id": 5,
        "name": "K线异常配合",
        "description": "推荐密集期前已暴涨超 50% 或高位放量横盘对倒拉升出货",
        "keywords": ["高位放量", "直线拉升", "异动", "出货", "大宗折价"],
    },
    {
        "id": 6,
        "name": "老师/股神人设推广",
        "description": "以操盘手、打板高手、涨停战法名义背书，晒盈利图引流",
        "keywords": ["名师", "操盘手", "股神", "带盘老师", "交割单"],
    },
    {
        "id": 7,
        "name": "跨平台联动推广",
        "description": "抖音、快手、小红书、微信公众号、知乎多平台协同轰炸",
        "keywords": ["小红书推荐", "抖音荐股", "快手直播", "B站UP主推荐"],
    },
    {
        "id": 8,
        "name": "虚假研报/伪造消息",
        "description": "假借知名券商研报、伪造重组重磅传闻，甚至引发上市公司辟谣",
        "keywords": ["小作文", "重磅传闻", "借壳", "公司辟谣", "澄清公告"],
    },
]


def detect_trap_signals(
    news_text: str = "",
    quote_info: dict[str, Any] | None = None,
    financial_flaws: bool = False,
    recent_surge_pct: float = 0.0,
) -> dict[str, Any]:
    """检测杀猪盘 8 信号，计算 trap_score 与风险评级。
    
    评级映射 (来自 eight-signals.md §评级映射):
    - 0-1 命中: 🟢 安全 (trap_score 9-10)
    - 2-3 命中: 🟡 注意 (trap_score 6-8)
    - 4-5 命中: 🟠 警惕 (trap_score 3-5)
    - 6+  命中: 🔴 高度可疑 (trap_score 1-2)
    """
    hits = []
    text_lower = news_text.lower() if news_text else ""

    for sig in TRAP_SIGNALS_DEF:
        matched_kws = [kw for kw in sig["keywords"] if kw.lower() in text_lower]
        if len(matched_kws) >= 1:
            hits.append({
                "id": sig["id"],
                "name": sig["name"],
                "evidence": f"命中了特征词: {', '.join(matched_kws)}",
            })

    if financial_flaws and (len(text_lower) > 20 or len(hits) > 0):
        if not any(h["id"] == 4 for h in hits):
            hits.append({
                "id": 4,
                "name": "基本面与热度脱节",
                "evidence": "标的存在严重财务瑕疵或基本面亏损，但市场充斥强烈炒作推介",
            })

    if recent_surge_pct >= 40.0:
        if not any(h["id"] == 5 for h in hits):
            hits.append({
                "id": 5,
                "name": "K线异常配合",
                "evidence": f"推介密集期前标的已急涨 {recent_surge_pct:.1f}%，警惕高位分发接盘",
            })

    extra_penalty = 0
    triggered_user_kws = []
    for kw, weight in USER_KEYWORDS.items():
        if kw in news_text:
            extra_penalty += weight
            triggered_user_kws.append(kw)

    total_hits = len(hits) + (1 if extra_penalty >= 2 else 0)

    if total_hits <= 1:
        level = "🟢 安全"
        score = 10 if total_hits == 0 else 9
        recommendation = "未发现杀猪盘推广痕迹，盘口较为干净。"
    elif total_hits <= 3:
        level = "🟡 注意"
        score = 8 if total_hits == 2 else 7
        recommendation = f"发现 {len(hits)} 个推广特征，建议核实信息来源，切勿轻信跟单。"
    elif total_hits <= 5:
        level = "🟠 警惕"
        score = 5 if total_hits == 4 else 3
        recommendation = "出现多项高危引流或杀猪盘特征，严禁高位接飞刀！"
    else:
        level = "🔴 高度可疑"
        score = 1
        recommendation = "高度疑似杀猪盘、黑嘴荐股收割陷阱，坚决一票否决回避！"

    return {
        "trap_score": score,
        "level": level,
        "hits_count": len(hits),
        "hit_signals": hits,
        "triggered_user_keywords": triggered_user_kws,
        "recommendation": recommendation,
    }


class TrapDetector:
    """杀猪盘与场外诱多检测器。"""

    def evaluate(self, ticker: str, concepts: list[str] | None = None, **_: Any) -> tuple[int, list[str]]:
        """评估杀猪盘风险，返回 (trap_score, warnings)。

        ★ 20261029 审计 P2：`detect_trap_signals` 的设计输入是**舆情正文**
          （新闻 / 股吧 / 推介话术），而这里喂给它的是**概念题材标签**
          （如 "华为概念 锂电池"）。概念名里恰好含"暴涨""龙头"等词就会命中
          关键词规则 → 把"标签里有'龙头'二字"当成"黑嘴荐股"在评分。
          保留能力（宁可多一个弱信号），但**必须如实标注口径**，并说明
          这不是真实舆情核验 —— 严禁让读者以为系统真的读过舆情。
        """
        concept_str = " ".join(concepts or [])
        res = detect_trap_signals(news_text=concept_str)
        warnings = [f"{h['name']}: {h['evidence']}" for h in res["hit_signals"]]
        if concept_str:
            warnings.append(
                "⚠️ 口径说明：本项输入为**概念题材标签**而非真实舆情正文，"
                "命中仅表示标签用词与杀猪盘话术词典重合，不等于已完成舆情核验"
                "（当前未接入新闻/股吧文本源）。"
            )
        return res["trap_score"], warnings
