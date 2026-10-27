"""8-signal short-term trap & pump-and-dump detector for AST-Trader."""
from __future__ import annotations

import re
from typing import Any

TRAP_KEYWORD_PATTERNS = [
    (1, "诱导话术模板化", [r"主力建仓完毕", r"即将爆发", r"内部消息", r"目标翻倍", r"稳赚不赔"]),
    (2, "社群直播间引流", [r"加微信", r"进群", r"老师带单", r"VIP直播", r"免费领牛股"]),
    (3, "名师股神人设", [r"游资操盘手", r"知名游资带领", r"顶级游资坐庄", r"股神指导"]),
    (4, "短视频平台推广", [r"小红书推荐", r"抖音牛股", r"快手老铁跟上"]),
    (5, "造谣与假研报", [r"突发重磅借壳", r"绝密重组", r"辟谣澄清", r"小作文预警"]),
]


class TrapDetector:
    """杀猪盘与短线欺诈雷达。"""

    def __init__(self) -> None:
        pass

    def evaluate(self, stock_name: str, news_snippets: list[str]) -> tuple[int, list[str]]:
        """评估股票舆情是否存在杀猪盘/高位出货特征。
        
        返回: (trap_risk_score, triggered_warnings)
        """
        score = 0
        warnings = []
        combined_text = " ".join(news_snippets)

        for sig_id, name, patterns in TRAP_KEYWORD_PATTERNS:
            for pat in patterns:
                if re.search(pat, combined_text, re.IGNORECASE):
                    score += 20
                    warnings.append(f"命中特征 [{sig_id}]: {name} (匹配关键词: {pat})")
                    break

        score = min(100, score)
        return score, warnings
