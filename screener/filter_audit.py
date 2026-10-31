"""Tier 2: Governance and audit red flags one-vote veto screener."""
from __future__ import annotations

import concurrent.futures
import logging
from typing import Any

import config
from data.eltdx_collector import EltdxCollector

logger = logging.getLogger("ast_trader.screener.audit")


def filter_audit(
    candidates: list[dict[str, Any]],
    collector: EltdxCollector,
    max_workers: int = 5,
    top_audit_count: int | None = None,
) -> list[dict[str, Any]]:
    """Tier 2 排雷: 针对候选标的执行一票否决硬核排雷 (严格 Fail-Closed 防御原则)。

    P0-3 修复要点
    -------------
    旧实现**唯一的**一票否决判据是 ``pledge_ratio > PLEDGE_FATAL_RATIO``，
    而采集层把 ``pledge_ratio`` 硬编码为 ``0.0`` —— 判据恒假，本层事实上
    永不剔除任何标的，三层漏斗退化为两层。

    现改为**多因子排雷**：

    1. 质押率：仅在 ``pledge_verified`` 为真时参与否决；不可核验时标记为
       ``UNVERIFIED_PLEDGE`` 并降权（不再当作"确认无质押"放行）。
    2. 监管违规处罚：近期记录达阈值即一票否决 —— 这是当前数据通道下
       可真实取得的治理风险维度。

    P1-1 修复要点（Tier 2 隐性截断）
    --------------------------------
    旧实现无条件执行 ``targets = candidates[:15]``，Tier 1 若留下 40 只合格
    标的，第 16~40 名**物理丢弃**、永不进入 Tier 3 排序 —— 而此时候选尚
    未经游资/资金流综合打分，被截掉的极可能是真正的核心题材票。

    现改为 ``top_audit_count=None`` 即**全量排雷**（默认）；仍保留 int 入参
    以便调用方在需要时限流。★ 同时把结果收集从 ``as_completed`` 改为
    **按输入序回填**：并发只用于提速，输出顺序必须严格等于 Tier 1 输出序，
    否则下游 ``rank_composite(top_n=...)`` 的截取结果不可复现。
    """
    if top_audit_count is None:
        targets = list(candidates)
    else:
        targets = candidates[:top_audit_count]

    def _audit_item(item: dict[str, Any]) -> dict[str, Any] | None:
        code_num = item["code"]
        name = item.get("name", code_num)
        try:
            gov = collector.get_f10_governance_and_concept(code_num)

            # ── 因子 1a: 股权质押**占总股本**比例 ──
            # None 表示通道不可得，严禁 float(None or 0.0) 兜底成 0
            pledge_ratio = gov.get("pledge_ratio")
            pledge_verified = pledge_ratio is not None
            pledge_source = gov.get("pledge_source")
            # ★ ``detail`` 来源 = 由 table0 质押流水回溯累加得出（该股没有
            #   table1/table2 汇总表）。实测 800 只采样：这类占 20%，
            #   且因**部分解押会留下多条记录**，累加会虚高 ——
            #   002269 美邦服饰累加出 **109.86%**（物理上不可能）。
            #   精度不足以支撑「一票否决」这种不可逆决定 ⇒ 只警示，不否决。
            pledge_low_confidence = pledge_source in ("detail", "detail_inconsistent")
            if pledge_verified:
                pledge_ratio = float(pledge_ratio)
                if pledge_ratio > config.PLEDGE_FATAL_RATIO and not pledge_low_confidence:
                    logger.warning(
                        f"一票否决: 剔除高质押高危标的 {code_num} {name} "
                        f"(质押占总股本 {pledge_ratio*100:.1f}% > 阈值 {config.PLEDGE_FATAL_RATIO*100:.0f}%)"
                    )
                    return None
                if pledge_low_confidence and pledge_ratio > config.PLEDGE_FATAL_RATIO:
                    logger.info(
                        f"降权提示: {code_num} {name} 质押占总股本 {pledge_ratio*100:.1f}% 超阈值，"
                        f"但该值由质押流水明细回溯（无汇总表，可能重复计）⇒ 仅警示不否决"
                    )

            # ── 因子 1b: 控股股东**占其持股**质押比例（爆仓踩踏）──
            # ★ t021 是"大股东把自己持股质押掉多少"，与"占总股本"是两个数量级不同的口径。
            #   旧实现把 t021 当作 pledge_ratio 去比 PLEDGE_FATAL_RATIO(占总股本口径)，
            #   会把"控股股东满仓质押但占总股本很小"的白马误杀（实测格力 000651 触发）。
            #   现在两个口径各用各的阈值。
            own_ratio = gov.get("pledge_ratio_of_own_max")
            own_high = False
            if own_ratio is not None:
                own_ratio = float(own_ratio)
                min_total = getattr(config, "PLEDGE_OWN_FATAL_MIN_TOTAL", 0.20)
                # ★ 必须叠加绝对规模才否决：强度高但盘子小 ⇒ 强平冲击有限，不足以一票否决
                if (own_ratio > config.PLEDGE_OWN_FATAL_RATIO
                        and pledge_verified and pledge_ratio > min_total):
                    logger.warning(
                        f"一票否决: 剔除爆仓踩踏高危标的 {code_num} {name} "
                        f"(控股股东占其持股质押 {own_ratio*100:.1f}% 且质押占总股本 "
                        f"{pledge_ratio*100:.1f}% > {min_total*100:.0f}%)"
                    )
                    return None
                own_high = own_ratio > config.PLEDGE_OWN_HIGH_RATIO

            # ── 因子 2: 监管违规处罚 (立案调查 / 行政处罚 / 监管函) ──
            violation_count = int(gov.get("violation_count") or 0)
            recent_violations = int(gov.get("recent_violation_count") or 0)
            if recent_violations >= config.GOVERNANCE_VIOLATION_FATAL_COUNT:
                logger.warning(
                    f"一票否决: 剔除近期监管违规密集标的 {code_num} {name} "
                    f"(近 {config.GOVERNANCE_VIOLATION_RECENT_YEARS} 年 {recent_violations} 条 "
                    f">= 阈值 {config.GOVERNANCE_VIOLATION_FATAL_COUNT} 条)"
                )
                return None

            item["concepts"] = gov.get("concepts", [item.get("limit_reason")])
            item["pledge_ratio"] = float(pledge_ratio) if pledge_verified else None
            item["pledge_verified"] = pledge_verified
            item["pledge_ratio_of_own_max"] = float(own_ratio) if own_ratio is not None else None
            item["pledge_own_high_risk"] = own_high
            # 数据来自哪一级（company/holder/detail/none）—— 排查时能立刻区分
            # "质押真为零" 与 "靠明细兜底算出的小比例"
            item["pledge_source"] = gov.get("pledge_source")
            item["pledge_live_records"] = gov.get("pledge_live_records")
            # 明细回溯值精度低 ⇒ 下游展示/加权需知道它不可用于硬否决
            item["pledge_low_confidence"] = pledge_low_confidence
            item["top_pledgor"] = gov.get("top_pledgor", "")
            item["violation_count"] = violation_count
            item["recent_violation_count"] = recent_violations
            item["audit_status"] = "VERIFIED_SAFE" if pledge_verified else "UNVERIFIED_PLEDGE"
            if not pledge_verified:
                logger.info(
                    f"降权提示: {code_num} {name} 质押率未核验，标记为 UNVERIFIED_PLEDGE "
                    f"(未按无质押放行)"
                )
            return item
        except Exception as e:
            # 严格贯彻 Fail-Closed 买方风控: 无法核验排雷数据的标的绝不放行进入推荐池
            logger.warning(
                f"一票否决 (Fail-Closed 安全剔除): 标的 {code_num} {name} 治理排雷接口异常，"
                f"在途质押与减持风险未获证实，执行保守剔除: {type(e).__name__}: {e}"
            )
            return None

    # ★ 并发只用于提速，**输出顺序必须严格等于输入顺序**：
    #   as_completed 是线程完成序，直接用它会让 rank_composite 的 top_n 截取不可复现。
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_idx = {executor.submit(_audit_item, c): idx for idx, c in enumerate(targets)}
        results: list[dict[str, Any] | None] = [None] * len(targets)
        for fut in concurrent.futures.as_completed(future_to_idx):
            results[future_to_idx[fut]] = fut.result()

    passed = [r for r in results if r is not None]

    unverified = sum(1 for p in passed if p.get("audit_status") == "UNVERIFIED_PLEDGE")
    logger.info(
        f"Tier 2 机械排雷完成: 检查 {len(targets)} 只 -> 安全通过 {len(passed)} 只标的 "
        f"(其中质押未核验需降权 {unverified} 只)"
    )
    if top_audit_count is not None and len(candidates) > len(targets):
        logger.warning(
            f"Tier 2 排雷被显式限流: 候选 {len(candidates)} 只只排雷前 {len(targets)} 只，"
            f"第 {len(targets)+1}~{len(candidates)} 名将不进入 Tier 3！"
        )
    return passed
