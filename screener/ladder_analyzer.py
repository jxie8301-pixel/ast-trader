"""涨停连板天梯与短线题材情绪周期分析器 (对齐 UZI-Skill themes.py & universe.py)."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from data.eltdx_client import open_client


@dataclass
class LadderRow:
    code: str
    full_code: str
    name: str
    board_level: int
    broken_count: int
    seal_amount: float
    limit_time: str
    limit_reason: str
    industry: str
    highest_board_level: int


@dataclass
class ThemeAggregate:
    name: str
    count: int
    total_seal_amount: float
    earliest_time: str
    leader_code: str
    leader_name: str
    leader_board: int
    members: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class MarketSentimentOverview:
    trade_date: str
    space_board_level: int
    space_board_tickers: list[str]
    ladder_counts: dict[int, int]
    promotion_rates: dict[int, float]
    total_limit_up_count: int
    sentiment_phase: str  # 启动, 发酵, 高潮, 分歧, 修复, 退潮
    strongest_themes: list[ThemeAggregate]
    total_limit_down_count: int = 0
    total_broken_count: int = 0
    broken_rate_pct: float = 0.0


class LadderAnalyzer:
    """提取通达信当日全市场涨停天梯、计算晋级率、识别题材主线与龙头结构。"""

    def analyze(self) -> tuple[MarketSentimentOverview, dict[str, dict[str, Any]], list[dict[str, Any]]]:
        """执行天梯分析。
        
        返回:
            (sentiment_overview, stock_theme_map, raw_ladder_rows)
        """
        with open_client() as c:
            lad = c.f10.limit_board_ladder()
            if not lad or not hasattr(lad, "rows") or not lad.rows:
                # 默认空结构
                return MarketSentimentOverview(
                    trade_date="",
                    space_board_level=0,
                    space_board_tickers=[],
                    ladder_counts={},
                    promotion_rates={},
                    total_limit_up_count=0,
                    sentiment_phase="未知",
                    strongest_themes=[],
                    total_limit_down_count=0,
                    total_broken_count=0,
                    broken_rate_pct=0.0,
                ), {}, []

        raw_rows = []
        ladder_counts: dict[int, int] = defaultdict(int)
        for k, v in (lad.ladder_counts or {}).items():
            if k is not None:
                ladder_counts[int(k)] = v

        promotion_rates: dict[int, float] = {}
        for k, v in (lad.promotion_rates or {}).items():
            if k is not None and v is not None:
                promotion_rates[int(k)] = round(float(v), 3)

        parsed_rows: list[LadderRow] = []
        space_board_level = 0
        space_board_tickers = []
        theme_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)

        # ── 区分封板涨停 (limit_up)、日内炸板 (broken) 与跌停 (limit_down) ──
        limit_up_rows = []
        broken_rows = []
        limit_down_rows = []

        for r in lad.rows:
            st = getattr(r, "status", None)
            if st == "limit_up":
                limit_up_rows.append(r)
            elif st == "broken":
                broken_rows.append(r)
            elif st == "limit_down":
                limit_down_rows.append(r)
            else:
                bl = getattr(r, "board_level", None)
                if bl is not None and bl > 0:
                    limit_up_rows.append(r)
                elif getattr(r, "broken_count", 0) and r.broken_count > 0:
                    broken_rows.append(r)
                else:
                    limit_down_rows.append(r)

        total_zt = len(limit_up_rows)
        total_dt = len(limit_down_rows)
        total_broken = len(broken_rows)
        total_attempt = total_zt + total_broken
        broken_rate_pct = round((total_broken / total_attempt * 100.0), 1) if total_attempt > 0 else 0.0

        for r in limit_up_rows:
            bl = getattr(r, "board_level", None) or getattr(r, "consecutive_limit_days", None) or 1
            hbl = getattr(r, "highest_board_level", None) or bl
            if hbl > space_board_level:
                space_board_level = hbl

            row_dict = {
                "code": r.code,
                "full_code": r.full_code,
                "name": r.name,
                "board_level": int(bl),
                "broken_count": int(getattr(r, "broken_count", 0) or 0),
                "seal_amount": float(getattr(r, "seal_amount", 0.0) or 0.0),
                "limit_time": getattr(r, "limit_time", None) or "09:30:00",
                "limit_reason": (getattr(r, "limit_reason", None) or getattr(r, "industry", None) or "未知题材").strip(),
                "industry": (getattr(r, "industry", None) or "其他").strip(),
                "highest_board_level": int(hbl),
            }
            raw_rows.append(row_dict)
            parsed_rows.append(LadderRow(**row_dict))

            # 聚合题材 (仅聚合真实封板涨停)
            theme_key = row_dict["limit_reason"]
            theme_groups[theme_key].append(row_dict)

        # 查找空间板标的
        for r in raw_rows:
            if r["board_level"] == space_board_level and space_board_level > 1:
                space_board_tickers.append(f"{r['name']}({r['code']})")

        # 题材聚合与龙头排序
        theme_aggs: list[ThemeAggregate] = []
        for tname, members in theme_groups.items():
            # 按连板数、封板时间排序（连板高者优先，同板者首封时间早者为龙一）
            sorted_m = sorted(members, key=lambda x: (-x["board_level"], x["limit_time"]))
            leader = sorted_m[0]
            total_seal = sum(x["seal_amount"] for x in members)
            earliest_t = min(x["limit_time"] for x in members)
            theme_aggs.append(ThemeAggregate(
                name=tname,
                count=len(members),
                total_seal_amount=total_seal,
                earliest_time=earliest_t,
                leader_code=leader["code"],
                leader_name=leader["name"],
                leader_board=leader["board_level"],
                members=sorted_m,
            ))

        # 题材按涨停家数、总封单资金排序
        theme_aggs.sort(key=lambda t: (-t.count, -t.total_seal_amount))

        # 综合情绪水温研判 (融入跌停与炸板率压制)
        if total_dt >= 15 or (total_dt >= 10 and broken_rate_pct >= 35.0):
            if space_board_level >= 4:
                phase = "高位分歧期"  # 妖股锁仓博傻，后排大面积跌停踩踏
            else:
                phase = "退潮分歧期"  # 情绪全线退潮
        elif total_zt <= 25 or (space_board_level <= 2 and total_dt >= 8):
            phase = "混沌冰点期"
        elif space_board_level >= 5 and total_zt >= 40 and total_dt <= 8 and broken_rate_pct < 30.0:
            phase = "主升发酵期"
        elif space_board_level >= 3 and total_zt >= 35 and total_dt <= 10:
            phase = "中位加速期"
        else:
            phase = "震荡轮动期"

        overview = MarketSentimentOverview(
            trade_date=lad.trade_date or "",
            space_board_level=space_board_level,
            space_board_tickers=space_board_tickers,
            ladder_counts=dict(ladder_counts),
            promotion_rates=promotion_rates,
            total_limit_up_count=total_zt,
            sentiment_phase=phase,
            strongest_themes=theme_aggs[:5],
            total_limit_down_count=total_dt,
            total_broken_count=total_broken,
            broken_rate_pct=broken_rate_pct,
        )

        # 构建个股题材上下文映射 (code -> context)
        stock_context_map: dict[str, dict[str, Any]] = {}
        for theme_rank, tagg in enumerate(theme_aggs, start=1):
            for leader_rank, m in enumerate(tagg.members, start=1):
                stock_context_map[m["code"]] = {
                    "theme_name": tagg.name,
                    "theme_rank": theme_rank,
                    "leader_rank": leader_rank,
                    "is_leader": leader_rank == 1,
                    "theme_zt_count": tagg.count,
                    "board_level": m["board_level"],
                    "seal_amount": m["seal_amount"],
                    "broken_count": m["broken_count"],
                    "limit_time": m["limit_time"],
                }

        return overview, stock_context_map, raw_rows
