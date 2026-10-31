"""真正的沪深全市场筛选漏斗编排器。

★ 本次重构的核心
----------------
改造前本类的 ``run_screener`` 第一步就是 ``ladder_analyzer.analyze()`` ——
候选池**唯一来源**是 ``f10.limit_board_ladder()`` 的当日封板行。也就是说
「谁能参选」是由第三方涨停事件流决定的：沪深 5225 只 A 股里当天没涨停的
约 98.6%，连被任何一条规则评估的资格都没有。那不是全市场筛选。

现在漏斗改为：

    L0 母池界定（codes 代码表，沪深全量）
      ↓  覆盖率闸门：扫描数 / 预期数 < 98% → 拒绝出结果
    L1 行情画像批量吞吐（stock_profile_table，一次拿全换手率/市值/上市日期）
      ↓
    天梯增强（board_level / limit_reason / seal_amount / 题材龙头位）★ 降级为增强源
      ↓
    T1 流动性初筛 → T2 排雷 → T3 排序 → 账本落盘

``limit_board_ladder`` 不再是 universe 来源，而是**轨道 A 的连板身位与题材上下文
增强器** —— 它提供的连板层级、涨停原因、题材聚合目前没有其他通道可替代。
"""
from __future__ import annotations

import logging
import time
from typing import Any

import config
from data.eltdx_collector import EltdxCollector
from .filter_audit import filter_audit
from .filter_liquidity import RULES as LIQUIDITY_RULES, filter_liquidity
from .funnel_audit import (
    STAGE_AUDIT,
    STAGE_LIQUIDITY,
    STAGE_PROFILE,
    STAGE_RANK,
    STAGE_TRACK_B,
    STAGE_TRACK_C,
    STAGE_TRACK_D,
    STAGE_UNIVERSE,
    FunnelAudit,
)
from .kline_batch import fetch_daily_bars
from .ladder_analyzer import LadderAnalyzer
from .market_gate import apply_macro_gate
from .finance_batch import fetch_finance
from .profile_batch import ProfileSnapshot, fetch_profiles
from .rank_composite import rank_composite
from .tracker import record_screen_picks
from .tracks import (
    B_PREFILTER_OUT,
    C_PREFILTER_OUT,
    C_PREFILTER_TRUNCATED,
    TRACK_A,
    TRACK_B,
    TRACK_C,
    TRACK_D,
    TRACK_NAMES,
    TRACK_RULES,
    prefilter_track_b,
    prefilter_track_c,
    apply_track_c_institutional,
    apply_track_d_trend,
    screen_track_b,
    screen_track_c,
    screen_track_d,
)
from .f10_deep import fetch_institutional_holdings, fetch_profit_trends
from .universe import (
    ALL_REASON_CODES,
    REASON_NEW_LISTING,
    REASON_PROFILE_MISSING,
    UniverseRow,
    board_class,
    build_universe,
    filter_by_listing_age,
)

logger = logging.getLogger("ast_trader.screener")

#: Tier 2 排雷队列被显式限流时的归因码（与旧版无声截断 15 只的本质区别）
REASON_AUDIT_QUEUE_TRUNCATED = "AUDIT_QUEUE_TRUNCATED"
REASON_AUDIT_VETO = "AUDIT_VETO"
REASON_RANK_TRUNCATED = "RANK_TRUNCATED"


class ScreenerPipeline:
    """沪深全市场多轨筛选控制器（第一批：全量母池 + 轨道 A）。"""

    def __init__(self) -> None:
        self.collector = EltdxCollector()
        self.ladder_analyzer = LadderAnalyzer(collector=self.collector)

    # ───────────────────────────────────────────────────────── 主流程
    def run_screener(self, mode: str = "close", top_n: int = 10) -> dict[str, Any]:
        """执行沪深全市场漏斗筛选。

        模式:
          'close': 盘后全天复盘
          'noon': 午盘 11:30 突击选股

        返回 ``{"picks", "overview", "universe", "funnel", "blocked", "block_reason"}``。
        ``blocked=True`` 时 ``picks`` 恒为空 —— 残缺的"全市场"比没有更危险。
        """
        logger.info(f"启动沪深全市场筛选 (模式: {mode})...")
        audit = FunnelAudit()
        audit.register_expected_rules(STAGE_UNIVERSE, ALL_REASON_CODES)
        audit.register_expected_rules(STAGE_PROFILE, (REASON_PROFILE_MISSING, REASON_NEW_LISTING))
        audit.register_expected_rules(STAGE_LIQUIDITY, LIQUIDITY_RULES)
        audit.register_expected_rules(STAGE_AUDIT, (REASON_AUDIT_QUEUE_TRUNCATED, REASON_AUDIT_VETO))
        audit.register_expected_rules(STAGE_RANK, (REASON_RANK_TRUNCATED,))
        audit.register_expected_rules(STAGE_TRACK_B, TRACK_RULES[TRACK_B])
        audit.register_expected_rules(STAGE_TRACK_C, TRACK_RULES[TRACK_C])
        audit.register_expected_rules(STAGE_TRACK_D, TRACK_RULES[TRACK_D])

        # ─── L0: 构建沪深全量母池 ───────────────────────────────────
        universe = build_universe(health=getattr(self.collector, "health", None))
        audit.record_input(STAGE_UNIVERSE, universe.scanned_total)
        for reason, n in universe.excluded.items():
            audit.record_drop(STAGE_UNIVERSE, reason, n)
        audit.record_output(STAGE_UNIVERSE, len(universe.rows))

        if not universe.coverage_ok:
            reason_txt = "; ".join(universe.warnings) or "覆盖率闸门未通过"
            logger.error(f"筛选中止: {reason_txt}")
            return self._blocked(universe, audit, reason_txt)

        if not universe.rows:
            return self._blocked(universe, audit, "母池为空（代码表返回 0 行）")

        logger.info(
            f"L0 母池完成: 扫描 {universe.scanned_total} / 预期 {universe.expected_total} "
            f"(覆盖率 {universe.coverage_ratio*100:.1f}%) -> 活跃 {len(universe.rows)} 只"
        )

        # ─── L1: 行情画像批量吞吐 ───────────────────────────────────
        full_codes = [r.full_code for r in universe.rows]
        audit.record_input(STAGE_PROFILE, len(full_codes))
        profiles, pstats = fetch_profiles(
            full_codes, health=getattr(self.collector, "health", None)
        )

        rows_after_age, dropped_age = self._apply_profile_stage(universe.rows, profiles)
        audit.record_drop(STAGE_PROFILE, REASON_NEW_LISTING, dropped_age)
        audit.record_drop(STAGE_PROFILE, REASON_PROFILE_MISSING, int(pstats.get("missing", 0)))
        audit.record_output(STAGE_PROFILE, len(rows_after_age))

        logger.info(
            f"L1 画像完成: 取到 {pstats.get('returned', 0)} 只 / 缺失 {pstats.get('missing', 0)} 只 "
            f"(失败批次 {pstats.get('failed_batches', 0)}/{pstats.get('batches', 0)})"
        )

        # ─── 天梯增强（降级为轨道 A 的连板与题材上下文，不再是 universe 来源）──
        sentiment_overview, stock_theme_map, ladder_rows, broken_rows = self.ladder_analyzer.analyze()
        ladder_idx = {str(r.get("code", "")): r for r in ladder_rows if r.get("code")}
        broken_codes = {str(r.get("code", "")) for r in broken_rows if r.get("code")}
        if not ladder_rows:
            logger.warning("未获取到当日连板天梯 —— 母池不受影响，但轨道 A 缺少连板身位与题材上下文")
        logger.info(
            f"天梯增强: 封板 {len(ladder_rows)} 只 / 炸板 {len(broken_rows)} 只"
            f"（炸板行此前被丢弃，现作为轨道 B 的『弱』之来源）"
        )

        candidates, quotes_map = self._build_candidates(rows_after_age, profiles, ladder_idx, stock_theme_map)

        # ─── T1: 流动性与动量初筛 ───────────────────────────────────
        audit.record_input(STAGE_LIQUIDITY, len(candidates))
        t1_passed = filter_liquidity(candidates, quotes_map, mode=mode, audit=audit)
        audit.record_output(STAGE_LIQUIDITY, len(t1_passed))

        # ─── T2: 排雷（显式限流 + 归因，杜绝旧版"无声截断 15 只"）───
        # ★ input 记的是 **Tier 1 存活数**（不是截断后的数），这样
        #   input = 队列截断 + 排雷否决 + output 才能守恒。
        audit.record_input(STAGE_AUDIT, len(t1_passed))
        t2_input, audit_tail = self._cap_audit_queue(t1_passed, audit)
        t2_passed = filter_audit(t2_input, self.collector, max_workers=5)
        audit.record_drop(STAGE_AUDIT, REASON_AUDIT_VETO, max(0, len(t2_input) - len(t2_passed)))

        # ─── T3: 资金流 + 游资画像排序 ──────────────────────────────
        audit.record_input(STAGE_RANK, len(t2_passed))
        final_top = rank_composite(t2_passed, self.collector, top_n=top_n, max_workers=5)

        # ★ 20261029 审计 P1-9：队列被限流截断后，若精选池**没填满**，必须从截断尾部
        #   补排雷再补位 —— 旧实现"截断即丢弃"：池子被人为做薄，而被截掉的标的
        #   从未排过雷就消失在漏斗里（归因只显示"被截断"，看不到它们本可入选）。
        extra_in: list[dict[str, Any]] = []
        extra_passed: list[dict[str, Any]] = []
        if audit_tail and len(final_top) < top_n:
            need = top_n - len(final_top)
            extra_in = audit_tail[: max(need * 3, need)]
            extra_passed = filter_audit(extra_in, self.collector, max_workers=5)
            # 回冲：这批标的当初已计入"队列截断"，现在重新纳入，不得重复计数
            audit.rebate_drop(STAGE_AUDIT, REASON_AUDIT_QUEUE_TRUNCATED, len(extra_in))
            audit.record_drop(STAGE_AUDIT, REASON_AUDIT_VETO, max(0, len(extra_in) - len(extra_passed)))
            if extra_passed:
                extra_top = rank_composite(extra_passed, self.collector, top_n=need, max_workers=5)
                have = {p.get("code") for p in final_top}
                final_top = final_top + [p for p in extra_top if p.get("code") not in have]
            logger.info(
                f"Tier 2 补排雷: 尾部补入 {len(extra_in)} 只 → 通过 {len(extra_passed)} 只，"
                f"精选池 {len(final_top)}/{top_n}"
            )

        t2_passed = t2_passed + extra_passed
        audit.record_output(STAGE_AUDIT, len(t2_passed))
        audit.record_input(STAGE_RANK, len(t2_passed))
        audit.record_drop(STAGE_RANK, REASON_RANK_TRUNCATED, max(0, len(t2_passed) - len(final_top)))
        audit.record_output(STAGE_RANK, len(final_top))

        # ─── 轨道 A 出池（向后兼容：``picks`` 即轨道 A 精选池）──────
        for p in final_top:
            p["track"] = TRACK_A
            p["track_name"] = TRACK_NAMES[TRACK_A]

        # ─── 轨道 B / C / D 分流（与轨道 A 共用同一份全量候选）──────
        tracks: dict[str, list[dict[str, Any]]] = {TRACK_A: final_top}
        tracks[TRACK_B] = self._run_track_b(candidates, broken_codes, audit)
        tracks[TRACK_C] = self._run_track_c(candidates, audit)
        tracks[TRACK_D] = self._run_track_d(candidates, audit)

        # ─── 宏观闸门：把大盘 regime 变成"今日是否交易 / 单票上限"约束 ───
        # ★ 20261029 审计 P0-1：此前 sentiment_overview 只是被塞进返回体的
        #   ``overview`` 字段，从未约束输出 —— 大盘冰点时照样输出一屏 buyable。
        #   现在四轨统一过闸门（与单股链路的 is_market_ice 口径一致）。
        macro_result = getattr(sentiment_overview, "macro_regime_result", None)
        macro_gate = apply_macro_gate(
            [p for ps in tracks.values() for p in ps], macro_result
        )

        # ─── 落盘账本（四轨统一打时间戳，供 T+1 闭环对账）─────────────
        # ★ 20261029 审计 P0-4：旧实现只落轨道 A，轨道 B/C/D 的选股**永远无法复盘**
        #   —— 分轨胜率无从谈起。现四轨全部入账并各自带 track 标签。
        _pick_date = getattr(sentiment_overview, "trade_date", None) or None
        for _tr, _ps in tracks.items():
            record_screen_picks(_ps, mode=mode, track=_tr, trade_date=_pick_date)

        violations = audit.violations()
        if violations:
            logger.warning(f"漏斗归因不守恒（有标的被无声丢弃）: {violations}")
        dead = audit.dead_rules()
        if dead:
            logger.warning(f"发现疑似死规则: {dead}")

        logger.info(
            f"沪深全市场筛选完毕: L0 {universe.scanned_total} → 活跃 {len(universe.rows)} | "
            f"轨道A(连板接力) T1 {len(t1_passed)} → T2 {len(t2_passed)} → Top {len(final_top)} | "
            f"轨道B(弱转强) {len(tracks[TRACK_B])} | 轨道C(产业中军) {len(tracks[TRACK_C])} | "
            f"轨道D(价值成长) {len(tracks[TRACK_D])}"
        )
        return {
            "picks": final_top, "overview": sentiment_overview, "universe": universe,
            "funnel": audit, "blocked": False, "block_reason": None,
            "tracks": tracks, "broken_codes": broken_codes,
            "macro_gate": macro_gate,      # ★ P0-1：市场级"今日是否交易"约束
            "mode": mode,                  # ★ P1-14：mode 不再只是账本标签，进入结果体
        }

    # ───────────────────────────────────────────────────────── 步骤实现
    def _blocked(self, universe: Any, audit: FunnelAudit, reason: str) -> dict[str, Any]:
        """闸门未通过时的统一返回 —— picks 恒为空，绝不输出残缺精选池。"""
        return {
            "picks": [],
            "overview": None,
            "universe": universe,
            "funnel": audit,
            "blocked": True,
            "block_reason": reason,
            "tracks": {},
            "macro_gate": {"status": "UNVERIFIED", "market_note": f"漏斗未通过闸门: {reason}"},
            "mode": None,
        }

    def _apply_profile_stage(
        self,
        rows: list[UniverseRow],
        profiles: dict[str, ProfileSnapshot],
    ) -> tuple[list[UniverseRow], int]:
        """用画像补齐 ``ipo_date`` 后执行次新剔除。

        ★ 只有拿到上市日期才能判次新，所以这条规则必须在 L1 而不是 L0 执行。
        """
        import dataclasses

        enriched: list[UniverseRow] = []
        for r in rows:
            snap = profiles.get(r.full_code)
            ipo = snap.ipo_date if snap is not None else None
            if ipo and not r.ipo_date:
                enriched.append(dataclasses.replace(r, ipo_date=ipo))
            else:
                enriched.append(r)

        kept, dropped = filter_by_listing_age(enriched)
        return kept, dropped

    def _build_candidates(
        self,
        rows: list[UniverseRow],
        profiles: dict[str, ProfileSnapshot],
        ladder_idx: dict[str, dict[str, Any]],
        stock_theme_map: dict[str, dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], dict[str, dict[str, float]]]:
        """把母池行 + 画像 + 天梯增强合成 Tier 1 候选与行情字典。"""
        candidates: list[dict[str, Any]] = []
        quotes_map: dict[str, dict[str, float | None]] = {}

        for r in rows:
            snap = profiles.get(r.full_code)
            lad = ladder_idx.get(r.code, {})

            if snap is None:
                # 画像缺失 → 行情不可核验；交由 Tier 1 的 NO_QUOTE 分支显式剔除，
                # 严禁在这里静默跳过（那样会让归因链断裂）。
                quotes_map[r.full_code] = {}
            else:
                quotes_map[r.full_code] = {
                    "close": snap.last_price,
                    "pre_close": snap.pre_close,
                    "pct_chg": snap.change_pct,
                    "amount": snap.amount,
                    # ★ 修死代码的关键：真实换手率终于进到了 Tier 1 的输入里
                    "turnover_ratio": snap.turnover_rate,
                }

            cand: dict[str, Any] = {
                "code": r.code,
                "full_code": r.full_code,
                "name": r.name,
                "exchange": r.exchange,
                "board": r.board or (snap.board if snap else None),
                "board_level": int(lad.get("board_level") or 1),
                "limit_reason": lad.get("limit_reason") or "热门题材",
                "seal_amount": float(lad.get("seal_amount") or 0.0),
                "industry": lad.get("industry"),
                # 供 Tier 3 打分与账本使用
                "total_mv": snap.total_market_value if snap else None,
                "circulating_mv": snap.circulating_market_value if snap else None,
                "ipo_date": r.ipo_date,
                # ── 轨道 B/C/D 需要直接消费画像行情字段（免费，无需额外取数）──
                "close": snap.last_price if snap else None,
                "change_pct": snap.change_pct if snap else None,
                "amount": snap.amount if snap else None,
                "turnover_rate": snap.turnover_rate if snap else None,
                "board_kind": board_class(r.board or (snap.board if snap else None), r.code, r.exchange),
            }
            theme = stock_theme_map.get(r.code)
            if theme:
                cand["theme_info"] = theme
                cand["is_leader"] = theme.get("is_leader")
                cand["leader_rank"] = theme.get("leader_rank")
            candidates.append(cand)

        return candidates, quotes_map

    # ───────────────────────────────────────────────────── 轨道 B / C / D
    def _run_track_b(
        self,
        candidates: list[dict[str, Any]],
        broken_codes: set[str],
        audit: FunnelAudit,
    ) -> list[dict[str, Any]]:
        """轨道 B：弱转强 / 首阴反包。

        ★ 「弱」的来源有两处：当日**炸板行**（天梯 ``broken_rows``，此前被丢弃）
          与**今日收阴但成交活跃**的标的。二者都先由免费字段预筛，再懒加载日 K。
        """
        if not config.TRACK_B_ENABLED:
            return []

        _t0 = time.time()
        audit.record_input(STAGE_TRACK_B, len(candidates))
        pre, pre_dropped = prefilter_track_b(candidates, broken_codes)
        for reason, n in pre_dropped.items():
            audit.record_drop(STAGE_TRACK_B, reason, n)

        if not pre:
            audit.record_output(STAGE_TRACK_B, 0)
            return []

        kline_map, kstats = fetch_daily_bars(
            [c["full_code"] for c in pre],
            count=config.TRACK_B_BARS_COUNT,
            health=getattr(self.collector, "health", None),
        )
        res = screen_track_b(pre, kline_map, broken_codes)
        for reason, n in res.dropped.items():
            audit.record_drop(STAGE_TRACK_B, reason, n)
        audit.record_output(STAGE_TRACK_B, len(res.passed))

        logger.info(
            f"轨道B [{time.time()-_t0:.1f}s]: 全量 {len(candidates)} → 预筛 {len(pre)} → "
            f"存活 {len(res.passed)} (日K缺失 {kstats.get('missing', 0)}) | 剔除 {res.dropped}"
        )
        return res.passed

    def _run_track_c(self, candidates: list[dict[str, Any]], audit: FunnelAudit) -> list[dict[str, Any]]:
        """轨道 C：产业中军与趋势白马。

        ★ 「机构持股占比 ≥15%」因 eltdx 无数据通道已降级为 ``UNVERIFIED``，
          不参与准入；市值分位由本项目对全池**自算**（比第三方分位更准）。
        """
        if not config.TRACK_C_ENABLED:
            return []

        _t0 = time.time()
        audit.record_input(STAGE_TRACK_C, len(candidates))
        pre, passed_before_cap, pre_dropped = prefilter_track_c(candidates)
        for reason, n in pre_dropped.items():
            audit.record_drop(STAGE_TRACK_C, reason, n)
        # ★ 限流截断单独记账 —— 合并进淘汰会让"被截断"伪装成"不合格"
        audit.record_drop(STAGE_TRACK_C, C_PREFILTER_TRUNCATED, passed_before_cap - len(pre))

        if not pre:
            audit.record_output(STAGE_TRACK_C, 0)
            return []

        # 截断量：预筛函数内部已按市值降序截断，这里反推被截掉的数量
        kline_map, _ = fetch_daily_bars(
            [c["full_code"] for c in pre],
            count=config.TRACK_C_BARS_COUNT,
            health=getattr(self.collector, "health", None),
        )
        res = screen_track_c(pre, kline_map)
        for reason, n in res.dropped.items():
            audit.record_drop(STAGE_TRACK_C, reason, n)

        # ── 机构持股：加权排序，不淘汰（用户裁决：无数据通道时降权，不否决）──
        passed = res.passed
        if passed and getattr(config, "TRACK_C_INSTITUTION_MIN_RATIO", 0) > 0:
            holdings, hstats = fetch_institutional_holdings(
                [c.get("code", "") for c in passed],
                health=getattr(self.collector, "health", None),
            )
            passed, tiers = apply_track_c_institutional(passed, holdings)
            logger.info(
                f"轨道C 机构持股: 取到 {hstats.get('ok', 0)}/{hstats.get('requested', 0)} 只 | "
                f"档位分布 {tiers} (1=达标加权 2=未达标 3=UNVERIFIED降权)"
            )

        audit.record_output(STAGE_TRACK_C, len(passed))

        logger.info(
            f"轨道C [{time.time()-_t0:.1f}s]: 全量 {len(candidates)} → 预筛 {len(pre)} → "
            f"存活 {len(passed)} | 剔除 {res.dropped}"
        )
        return passed

    def _run_track_d(self, candidates: list[dict[str, Any]], audit: FunnelAudit) -> list[dict[str, Any]]:
        """轨道 D：困境反转与价值成长。

        ★ 这是**唯一能近乎免费地全市场扫描**的轨道：
          ``corporate.finance_batch`` 100 只仅 0.03s ⇒ 5225 只 ≈ 2s。
        """
        if not config.TRACK_D_ENABLED:
            return []

        _t0 = time.time()
        audit.record_input(STAGE_TRACK_D, len(candidates))
        finance_map, fstats = fetch_finance(
            [c["full_code"] for c in candidates],
            health=getattr(self.collector, "health", None),
        )
        res = screen_track_d(candidates, finance_map)
        for reason, n in res.dropped.items():
            audit.record_drop(STAGE_TRACK_D, reason, n)

        # ── 边际拐点：多期财报（CWServ.tdxf10_gg_cwfx 一次给 32~114 期）──
        passed = res.passed
        if passed and getattr(config, "TRACK_D_TREND_ENABLED", True):
            trends, tstats = fetch_profit_trends(
                [c.get("code", "") for c in passed],
                health=getattr(self.collector, "health", None),
            )
            # ★ 只有第三个返回值（不可核验数）**不进**归因矩阵 —— 那些标的仍在输出里
            passed, trend_dropped, trend_unverified = apply_track_d_trend(passed, trends)
            for reason, n in trend_dropped.items():
                audit.record_drop(STAGE_TRACK_D, reason, n)
            self._track_d_unverified = trend_unverified
            logger.info(
                f"轨道D 拐点: 取到 {tstats.get('ok', 0)}/{tstats.get('requested', 0)} 只 | "
                f"剔除 {trend_dropped} | 不可核验 {trend_unverified} 只（放行并标注）"
            )

        audit.record_output(STAGE_TRACK_D, len(passed))

        logger.info(
            f"轨道D [{time.time()-_t0:.1f}s]: 全量 {len(candidates)} → 存活 {len(passed)} "
            f"(财务缺失 {fstats.get('missing', 0)}) | 剔除 {res.dropped}"
        )
        return passed

    def _cap_audit_queue(
        self, t1_passed: list[dict[str, Any]], audit: FunnelAudit
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Tier 2 排雷队列显式限流。

        ★ 与旧版 ``candidates[:15]`` 的本质区别：
          1. 阈值来自 ``config.UNIVERSE_MAX_AUDIT_QUEUE``，可调；
          2. 截断**写入归因矩阵**（``AUDIT_QUEUE_TRUNCATED``），面板可见、测试可断言；
          3. 截断前先按「连板身位 → 成交额」降序，保证留下的是最该排雷的那批，
             而不是天梯的原始顺序；
          4. ★ P1-9：返回 ``(队列, 被截尾部)`` —— 尾部不再直接丢弃，精选池没填满时
             用它**补排雷补位**（旧实现截断即丢，池子被人为做薄，且被截标的从未排雷）。

        调用方补位时必须用 ``FunnelAudit.rebate_drop`` 回冲截断计数，否则漏斗不守恒。
        """
        limit = int(getattr(config, "UNIVERSE_MAX_AUDIT_QUEUE", 0) or 0)
        if limit <= 0 or len(t1_passed) <= limit:
            return t1_passed, []

        ordered = sorted(
            t1_passed,
            key=lambda c: (
                int(c.get("board_level") or 1),
                float(c.get("amount") or 0.0),
            ),
            reverse=True,
        )
        dropped = len(ordered) - limit
        audit.record_drop(STAGE_AUDIT, REASON_AUDIT_QUEUE_TRUNCATED, dropped)
        logger.warning(
            f"Tier 2 排雷队列显式限流: Tier 1 存活 {len(ordered)} 只 -> 仅前 {limit} 只进入排雷，"
            f"第 {limit+1}~{len(ordered)} 名按 (连板身位, 成交额) 降序被截（已计入归因矩阵）"
        )
        # ★ P1-9：尾部**不再直接丢弃**，随队列一并返回 —— 精选池没填满时用它补排雷补位。
        return ordered[:limit], ordered[limit:]
