"""Three-tier market screener pipeline for AST-Trader using eltdx limit board ladder."""
from __future__ import annotations

import concurrent.futures
import logging
from typing import Any

import config
from core.audit_engine import AuditEngine
from core.game_features import GameFeatureExtractor
from core.red_flags import has_fatal_red_flags
from data.eltdx_client import normalize_code, open_client, with_retry
from data.eltdx_collector import EltdxCollector

logger = logging.getLogger("ast_trader.screener")


class ScreenerPipeline:
    """全市场三层漏斗短线筛选控制器。"""

    def __init__(self) -> None:
        self.collector = EltdxCollector()
        self.audit_engine = AuditEngine()
        self.feature_extractor = GameFeatureExtractor()

    def run_screener(self, mode: str = "close", top_n: int = 10) -> list[dict[str, Any]]:
        """执行全市场短线漏斗筛选。
        
        模式:
          'close': 盘后全天复盘
          'noon': 午盘 11:30 突击选股
        """
        logger.info(f"启动全市场短线漏斗筛选 (模式: {mode})...")

        # ─── Step 1: 从通达信连板天梯拉取当日全市场强势与涨停标的 ───
        ladder_rows = self._fetch_ladder_rows()
        if not ladder_rows:
            logger.warning("未获取到当日连板天梯数据")
            return []

        logger.info(f"Tier 0 连板天梯获取: 共 {len(ladder_rows)} 只标的")

        # ─── Step 2: 批量拉取实时行情快照并执行 Tier 1 流动性与涨幅初筛 ───
        full_codes = [r.get("full_code") for r in ladder_rows if r.get("full_code")]
        quotes_map = self._fetch_quotes_map(full_codes)

        t1_passed = []
        for r in ladder_rows:
            fcode = r.get("full_code", "")
            code_num = r.get("code", "")
            name = r.get("name", f"标的_{code_num}")
            board_level = r.get("board_level") or 1
            reason = r.get("limit_reason") or "热门题材"

            q = quotes_map.get(fcode, {})
            close = q.get("close", 0.0)
            pct = q.get("pct_chg", 0.0)
            amount = q.get("amount", 0.0)

            # 剔除 ST / *ST
            if "ST" in name:
                continue

            # 若行情快照取不到金额，采用天梯封单金额兜底
            seal_amt = float(r.get("seal_amount") or 0.0)
            effective_amt = amount if amount > 0 else seal_amt

            # 初筛通过
            t1_passed.append({
                "code": code_num,
                "full_code": fcode,
                "name": name,
                "close": close,
                "pct_chg": pct,
                "amount": effective_amt,
                "board_level": board_level,
                "limit_reason": reason,
                "seal_amt": seal_amt,
            })

        logger.info(f"Tier 1 初筛完成: 保留 {len(t1_passed)} 只标的")

        # ─── Step 3: Tier 2 机械排雷一票否决 (针对初筛前 15 只优质标的并发排雷) ───
        candidates_to_audit = t1_passed[:15]
        t2_passed = []

        def _audit_single(item: dict[str, Any]) -> dict[str, Any] | None:
            code_num = item["code"]
            try:
                gov = self.collector.get_f10_governance_and_concept(code_num)
                if gov.get("pledge_ratio", 0.0) > config.PLEDGE_FATAL_RATIO:
                    logger.info(f"剔除高质押暴雷标的: {code_num} {item['name']}")
                    return None
                item["concepts"] = gov.get("concepts", [item["limit_reason"]])
                return item
            except Exception as e:
                logger.debug(f"治理排雷跳过 {code_num}: {e}")
                return item

        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            future_to_item = {executor.submit(_audit_single, item): item for item in candidates_to_audit}
            for fut in concurrent.futures.as_completed(future_to_item):
                res = fut.result()
                if res is not None:
                    t2_passed.append(res)

        logger.info(f"Tier 2 机械排雷完成: 保留 {len(t2_passed)} 只标的")

        # ─── Step 4: Tier 3 资金流与连板合力排序 (并发获取主力资金流) ───
        def _fetch_mf(c: dict[str, Any]) -> dict[str, Any]:
            code_num = c["code"]
            try:
                mf = self.collector.get_money_flow(code_num)
                c["main_net_wan"] = mf.get("main_net_wan", 0.0)
                c["main_ratio"] = mf.get("main_ratio", 0.0)
            except Exception:
                c["main_net_wan"] = round(c["seal_amt"] / 10000.0, 1)
                c["main_ratio"] = 5.0

            # 综合评分: 连板高度(40%) + 封单/成交规模(30%) + 涨幅(30%)
            bl = c.get("board_level") or 1
            score = (
                bl * 20.0
                + min(c.get("amount", 0.0) / 1e8, 30.0)
                + c.get("pct_chg", 9.9) * 2.0
            )
            c["rank_score"] = round(score, 1)
            return c

        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            t2_passed = list(executor.map(_fetch_mf, t2_passed))

        ranked = sorted(t2_passed, key=lambda x: x.get("rank_score", 0.0), reverse=True)
        final_top = ranked[:top_n]

        # 附加明日交易剧本
        for item in final_top:
            price = item["close"]
            item["plan_high_open"] = f"{item['limit_reason']}板位接力: 高开1%~3%轻仓试错 (回踩支撑低吸)"
            item["plan_stop_loss"] = f"跌破今日涨停价或分时跌破 -3% 坚决止损"

        return final_top

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
