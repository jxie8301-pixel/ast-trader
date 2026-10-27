"""Three-tier market screener pipeline orchestrator for AST-Trader."""
from __future__ import annotations

import logging
from typing import Any

from data.eltdx_client import open_client
from data.eltdx_collector import EltdxCollector
from .filter_audit import filter_audit
from .filter_liquidity import filter_liquidity
from .ladder_analyzer import LadderAnalyzer, MarketSentimentOverview
from .rank_composite import rank_composite
from .tracker import record_screen_picks

logger = logging.getLogger("ast_trader.screener")


class ScreenerPipeline:
    """全市场三层漏斗短线筛选控制器 (集成涨停天梯、情绪周期与实盘追踪账本)."""

    def __init__(self) -> None:
        self.collector = EltdxCollector()
        self.ladder_analyzer = LadderAnalyzer()

    def run_screener(self, mode: str = "close", top_n: int = 10) -> dict[str, Any]:
        """执行全市场短线漏斗筛选。
        
        模式:
          'close': 盘后全天复盘
          'noon': 午盘 11:30 突击选股
        """
        logger.info(f"启动全市场短线漏斗筛选 (模式: {mode})...")

        # ─── Step 1: 从通达信连板天梯拉取当日全市场强势与涨停标的并解构题材情绪 ───
        sentiment_overview, stock_theme_map, ladder_rows = self.ladder_analyzer.analyze()
        if not ladder_rows:
            logger.warning("未获取到当日连板天梯数据")
            return {"picks": [], "overview": sentiment_overview}

        logger.info(f"Tier 0 连板天梯分析完成: 共 {len(ladder_rows)} 只涨停/强势标的，空间板 {sentiment_overview.space_board_level} 板")

        # 关联题材上下文
        for r in ladder_rows:
            code = r["code"]
            if code in stock_theme_map:
                r["theme_info"] = stock_theme_map[code]
                r["is_leader"] = stock_theme_map[code]["is_leader"]
                r["leader_rank"] = stock_theme_map[code]["leader_rank"]

        # ─── Step 2: 批量拉取实时行情快照并执行 Tier 1 流动性与涨幅初筛 ───
        full_codes = [r.get("full_code") for r in ladder_rows if r.get("full_code")]
        quotes_map = self._fetch_quotes_map(full_codes)

        t1_passed = filter_liquidity(ladder_rows, quotes_map)

        # ─── Step 3: Tier 2 机械排雷一票否决 (针对初筛前 15 只优质标的并发排雷) ───
        t2_passed = filter_audit(t1_passed, self.collector, max_workers=5, top_audit_count=15)

        # ─── Step 4: Tier 3 资金流与连板合力排序 (并发获取主力资金流与 24 游资战法匹配) ───
        final_top = rank_composite(t2_passed, self.collector, top_n=top_n, max_workers=5)

        # ─── Step 5: 自动写入实盘 Paper-Trading 追踪账本 ───
        record_screen_picks(final_top, mode=mode)

        logger.info(f"全市场短线漏斗筛选完毕: 最终筛选输出 Top {len(final_top)} 标的并已记账")
        return {"picks": final_top, "overview": sentiment_overview}

    def _fetch_ladder_rows(self) -> list[dict[str, Any]]:
        """从通达信 F10 limit_board_ladder 接口提取当日全市场涨停天梯。"""
        with open_client() as c:
            try:
                lad = c.f10.limit_board_ladder()
                if not lad or not hasattr(lad, "rows") or not lad.rows:
                    return []
                out = []
                for r in lad.rows:
                    out.append({
                        "code": r.code,
                        "full_code": r.full_code,
                        "name": r.name,
                        "board_level": r.board_level,
                        "limit_reason": r.limit_reason,
                        "seal_amount": r.seal_amount,
                        "industry": r.industry,
                    })
                return out
            except Exception as e:
                logger.warning(f"获取连板天梯异常: {e}")
                return []

    def _fetch_quotes_map(self, full_codes: list[str]) -> dict[str, dict[str, float]]:
        """批量获取快照行情。"""
        if not full_codes:
            return {}
        quotes_map = {}
        with open_client() as c:
            try:
                # 分批每次 50 只
                for i in range(0, len(full_codes), 50):
                    batch = full_codes[i:i+50]
                    sn_list = c.quotes.get_snapshots(batch)
                    for sn in sn_list:
                        close = float(sn.last_price)
                        pre = float(sn.pre_close_price)
                        pct = round((close - pre) / pre * 100.0, 2) if pre else 0.0
                        amt = float(sn.amount) if sn.amount else 0.0
                        pref = sn.exchange.lower()
                        quotes_map[f"{pref}{sn.code}"] = {
                            "close": close,
                            "pre_close": pre,
                            "pct_chg": pct,
                            "amount": amt,
                        }
            except Exception as e:
                logger.warning(f"批量快照行情异常: {e}")
        return quotes_map
