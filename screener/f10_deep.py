"""F10 深度取数：多期财报（ROE/净利润边际拐点）与十大流通股东机构持股。

★ 为什么需要这个模块（20261028 复盘 —— 两条既有结论**被推翻**）
------------------------------------------------------------------
此前在 :mod:`screener.finance_batch` 与 :mod:`screener.tracks` 的注释里写过：

    「ROE 边际拐点不可得：`finance_batch` 只给单期快照」
    「机构持股无数据通道：eltdx 不给前十大流通股东」

**这两条都是错的** —— 错在用错了通道，而不是通道不存在。实测：

* ``corporate.finance_batch`` 确实只给**最新单期**，但
  ``CWServ.tdxf10_gg_cwfx``（``client.f10.finance_report``）一次返回
  **纵向 32~114 个报告期**（美的 57 期、茅台 103 期、格力 114 期），每行带
  ``rq`` 报告期。⇒ 多期 ROE / 净利润同比完全可得，**拐点可核验**。
* 机构持股在 ``CWServ.tdxf10_gg_gdyj`` + ``section="ltgd"``：``tables[1]``
  返回 **10 名股东 × 18 个报告期**，每行带 ``lb`` 股东类别标签（实测取值：
  ``基金/保险/QFII/券商/社保/北上资金/资管计划/私募证券投资基金/特殊法人/
  一般法人/自然人``）与 ``cgs`` 持股数。⇒ 机构持股占比**可直接算出**。

教训：判定"无数据通道"之前，必须穷举该业务的**全部** Entry，而不只是高级
封装方法。``finance_batch`` / ``f10.valuation`` / ``f10.finance_diagnosis``
这三个都不是财报历史序列的入口。

★ 成本
------
F10 走 HTTP 7615 且无状态。单线程 268~293ms/只；用每线程独立 ``F10Client``
+ 8 并发可压到 **~74ms/只**（152 只 ≈ 11s）。

★ 数据纪律 (NFR-02)
-------------------
取数失败 / 期数不足 → 一律返回 ``None`` 或 ``"UNVERIFIED"``，
**绝不返回 0.0 / 0% 伪装的"零机构持股"或"业绩零增长"** —— 那会把通道故障
伪装成"这只票没有机构看好 / 业绩零增长"。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

import config

logger = logging.getLogger("ast_trader.screener.f10_deep")

#: 利润表（``lyb``）中「归属于母公司所有者的净利润」。
#: ★ 已交叉验证：美的 2026-06-30 的 T030 = 264.46 亿，
#:   与 ``corporate.finance_batch`` 的 jing_li_run = 264 亿 完全一致。
LYB_PARENT_NET_PROFIT = "T030"
#: 利润表「净利润」（含少数股东损益），仅作参考
LYB_NET_PROFIT = "T029"

#: 资产负债表「资产总计」与「负债合计」。
#: ★ 用恒等式 ``所有者权益 = T039 - T053`` 推算净资产，而不是去猜
#:   "归属母公司所有者权益"是哪一个 T 字段 —— 恒等式不会猜错。
ZCFZB_TOTAL_ASSETS = "T039"
ZCFZB_TOTAL_LIABILITIES = "T053"

SHAREHOLDER_ENTRY = "CWServ.tdxf10_gg_gdyj"
SHAREHOLDER_SECTION = "ltgd"


def _num(value: Any) -> float | None:
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return None if f != f else f


# ══════════════════════════════════════════════════ 机构持股
@dataclass(frozen=True)
class InstitutionalHolding:
    """前十大流通股东中的机构持股结构。

    口径（A 股惯例，且刻意与"产业资本/控股股东"区分）：
      * ``institutional_ratio``：**严格机构** = 基金/保险/QFII/券商/社保/
        信托/财务公司/资管计划/私募/北上资金 —— 度量"专业机构认可度"。
      * ``state_ratio``：国家队/特殊法人（证金、汇金等），单独统计。
      * ``corporate_ratio``：一般法人 —— 控股股东与产业资本（如美的控股
        占十大流通股东 48.6%），**不计入**机构；否则大股东持股会把机构
        占比整体顶高，指标失效。
      * ``retail_ratio``：自然人。
    """

    code: str
    report_date: str | None = None
    institutional_ratio: float | None = None   # 0~1
    state_ratio: float | None = None
    corporate_ratio: float | None = None
    retail_ratio: float | None = None
    top10_total_shares: float | None = None
    breakdown: dict[str, float] = field(default_factory=dict)
    periods: int = 0

    @property
    def verified(self) -> bool:
        return self.institutional_ratio is not None

    def combined_ratio(self) -> float | None:
        """机构 + 国家队合计占比。"""
        if self.institutional_ratio is None:
            return None
        return self.institutional_ratio + (self.state_ratio or 0.0)


def _label_bucket(label: str | None) -> str:
    """把 F10 的 ``lb`` 标签归入 机构 / 国家队 / 产业资本 / 散户 / 其他。"""
    if not label:
        return "other"
    if label in config.TRACK_C_INSTITUTION_LABELS:
        return "institution"
    if label in config.TRACK_C_INSTITUTION_STATE_LABELS:
        return "state"
    if label == "自然人":
        return "retail"
    if label == "一般法人":
        return "corporate"
    return "other"


def parse_institutional_holding(code: str, response: Any) -> InstitutionalHolding | None:
    """解析 ``CWServ.tdxf10_gg_gdyj`` + ``ltgd`` 响应。

    ``tables[1]`` 是十大流通股东明细（股东名 ``gd`` / 类别 ``lb`` /
    持股数 ``cgs`` / 报告期 ``rq``）。取**最新报告期**计算占比。
    """
    tables = getattr(response, "tables", None) or ()
    if len(tables) < 2:
        return None
    rows = list(tables[1].rows or ())
    if not rows:
        return None

    periods = sorted({str(r.get("rq") or "") for r in rows if r.get("rq")}, reverse=True)
    if not periods:
        return None
    latest = periods[0]
    snap = [r for r in rows if str(r.get("rq") or "") == latest]

    total = 0.0
    buckets: dict[str, float] = {"institution": 0.0, "state": 0.0, "retail": 0.0,
                                 "corporate": 0.0, "other": 0.0}
    breakdown: dict[str, float] = {}
    for r in snap:
        shares = _num(r.get("cgs"))
        if shares is None or shares <= 0:
            continue
        total += shares
        bucket = _label_bucket(r.get("lb"))
        buckets[bucket] = buckets.get(bucket, 0.0) + shares
        key = str(r.get("lb") or "其他")
        breakdown[key] = breakdown.get(key, 0.0) + shares

    if total <= 0:
        return None

    return InstitutionalHolding(
        code=code,
        report_date=latest,
        institutional_ratio=buckets["institution"] / total,
        state_ratio=buckets["state"] / total,
        corporate_ratio=buckets["corporate"] / total,
        retail_ratio=buckets["retail"] / total,
        top10_total_shares=total,
        breakdown={k: v / total for k, v in sorted(breakdown.items(), key=lambda kv: -kv[1])},
        periods=len(periods),
    )


# ══════════════════════════════════════════════════ 多期财报 / 拐点
@dataclass(frozen=True)
class ProfitTrend:
    """归母净利润与 ROE 的**边际拐点**判定结果。

    ★ 为什么用「同比」而不是「环比」：A 股财报是**累计口径**
      （Q1=1 季度、H1=2 季度累计、Q3=3 季度累计、年报=全年）。
      直接环比会把"Q2 单季 vs Q1 单季"与季节性混在一起，得出伪信号。
      同比同季（H1 2026 vs H1 2025）才是可比口径。
    """

    code: str
    report_date: str | None = None
    #: 最新期归母净利润同比增速 (%)
    yoy_pct: float | None = None
    #: 上一期归母净利润同比增速 (%)
    yoy_prev_pct: float | None = None
    #: 同比增速的**边际变化**（百分点）—— 正 = 改善在加速
    yoy_delta_pp: float | None = None
    roe_pct: float | None = None
    roe_prev_year_pct: float | None = None
    roe_delta_pp: float | None = None
    periods: int = 0
    #: 'turning_positive' | 'accelerating' | 'stable' | 'decelerating' | 'UNVERIFIED'
    trend: str = "UNVERIFIED"

    @property
    def verified(self) -> bool:
        return self.trend != "UNVERIFIED"

    @property
    def is_positive(self) -> bool:
        """是否命中「困境反转」想要的正向拐点。"""
        return self.trend in ("turning_positive", "accelerating")


def _series(table: Any, field_name: str) -> list[tuple[str, float]]:
    """抽取 ``(报告期, 字段值)`` 序列，按报告期**倒序**（最新在前）。"""
    out: list[tuple[str, float]] = []
    for row in getattr(table, "rows", None) or ():
        rq = str(row.get("rq") or "").strip()
        v = _num(row.get(field_name))
        if rq and v is not None:
            out.append((rq, v))
    out.sort(key=lambda kv: kv[0], reverse=True)
    return out


def _same_quarter_last_year(rq: str) -> str:
    """'2026-06-30' -> '2025-06-30'。"""
    try:
        y, rest = rq.split("-", 1)
        return f"{int(y) - 1}-{rest}"
    except (ValueError, IndexError):
        return ""


def parse_profit_trend(
    code: str,
    income_table: Any,
    balance_table: Any | None = None,
) -> ProfitTrend:
    """从利润表（+ 可选资产负债表）解析边际拐点。

    判据（按优先级）：
      1. ``turning_positive``：上期同比为负、本期同比转正 —— **困境反转的核心形态**
      2. ``accelerating``：同比增速边际提升 ≥ ``TRACK_D_TREND_MIN_YOY_DELTA_PCT`` 个百分点
      3. ``stable``：|边际变化| < 阈值
      4. ``decelerating``：同比增速边际下滑 ≥ 阈值
      5. ``UNVERIFIED``：期数不足或取数失败 —— 不可核验，**不是零增长**
    """
    profits = _series(income_table, LYB_PARENT_NET_PROFIT)
    if len(profits) < 6:
        # 不足 6 期 ⇒ 算不出「本期同比」与「上期同比」两个点
        return ProfitTrend(code=code, periods=len(profits), trend="UNVERIFIED")

    index = {rq: v for rq, v in profits}

    def yoy_at(i: int) -> float | None:
        """第 i 期（0=最新）的归母净利润同比增速(%)。分母 ≤ 0 时无定义。"""
        rq, v = profits[i]
        base = index.get(_same_quarter_last_year(rq))
        if base is None or base <= 0:
            return None
        return (v / base - 1.0) * 100.0

    yoy = yoy_at(0)
    yoy_prev = yoy_at(1)
    if yoy is None or yoy_prev is None:
        return ProfitTrend(code=code, report_date=profits[0][0], periods=len(profits),
                           trend="UNVERIFIED")

    delta = yoy - yoy_prev
    min_delta = float(getattr(config, "TRACK_D_TREND_MIN_YOY_DELTA_PCT", 10.0))

    if yoy_prev < 0 <= yoy:
        trend = "turning_positive"
    elif delta >= min_delta:
        trend = "accelerating"
    elif delta <= -min_delta:
        trend = "decelerating"
    else:
        trend = "stable"

    roe = roe_prev = None
    if balance_table is not None:
        assets = dict(_series(balance_table, ZCFZB_TOTAL_ASSETS))
        liabs = dict(_series(balance_table, ZCFZB_TOTAL_LIABILITIES))

        def equity_at(rq: str) -> float | None:
            a, l = assets.get(rq), liabs.get(rq)
            if a is None or l is None:
                return None
            return (a - l) if (a - l) > 0 else None

        rq0 = profits[0][0]
        eq = equity_at(rq0)
        roe = (index[rq0] / eq * 100.0) if eq else None
        rq_ly = _same_quarter_last_year(rq0)
        eq_ly = equity_at(rq_ly)
        if rq_ly in index and eq_ly:
            roe_prev = index[rq_ly] / eq_ly * 100.0

    return ProfitTrend(
        code=code,
        report_date=profits[0][0],
        yoy_pct=yoy,
        yoy_prev_pct=yoy_prev,
        yoy_delta_pp=delta,
        roe_pct=roe,
        roe_prev_year_pct=roe_prev,
        roe_delta_pp=None if (roe is None or roe_prev is None) else roe - roe_prev,
        periods=len(profits),
        trend=trend,
    )


# ══════════════════════════════════════════════════ 并发批量入口
def _new_f10() -> Any:
    """每线程独立 F10Client。

    ★ F10 走 HTTP 7615 且无状态，**不需要** 7709 行情长连接。
      每线程独立实例可避免共享 session 的线程安全问题，开销可忽略。
    """
    from eltdx import F10Client

    return F10Client(timeout=float(config.F10_DEEP_TIMEOUT))


def _fanout(codes: Sequence[str], job: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    """并发执行 ``job(client, code)``，返回 ``(结果映射, 统计)``。

    ★ 结果**只收录成功项**。失败项计入 ``stats["failed_codes"]``，
      由调用方归入 ``*_UNVERIFIED`` —— 不可核验绝不等于不合格。
    """
    from concurrent.futures import ThreadPoolExecutor

    codes = [str(c).strip() for c in codes if c]
    stats: dict[str, Any] = {
        "requested": len(codes), "ok": 0, "failed": 0, "failed_codes": [],
        "workers": int(getattr(config, "F10_DEEP_MAX_WORKERS", 8)),
    }
    result: dict[str, Any] = {}
    if not codes:
        return result, stats

    def run(code: str) -> tuple[str, Any]:
        try:
            return code, job(_new_f10(), code)
        except Exception as exc:      # noqa: BLE001  单只失败不影响整批
            logger.debug(f"F10 深度取数失败 {code}: {type(exc).__name__}: {exc}")
            return code, None

    with ThreadPoolExecutor(max_workers=stats["workers"]) as ex:
        for code, value in ex.map(run, codes):
            if value is None:
                stats["failed"] += 1
                stats["failed_codes"].append(code)
            else:
                result[code] = value
                stats["ok"] += 1
    return result, stats


def fetch_institutional_holdings(
    codes6: Iterable[str],
    *,
    health: Any | None = None,
) -> tuple[dict[str, InstitutionalHolding], dict[str, Any]]:
    """批量取前十大流通股东机构持股结构。入参为**六位裸码**。"""
    def job(f10: Any, code: str) -> Any:
        resp = f10.params(SHAREHOLDER_ENTRY, code, SHAREHOLDER_SECTION, "", "", "1", "1", "20")
        if not getattr(resp, "ok", False):
            return None
        return parse_institutional_holding(code, resp)

    result, stats = _fanout(list(codes6), job)
    if health is not None and stats["ok"]:
        try:
            if stats["failed"]:
                health.record_degraded(
                    "F10十大流通股东", SHAREHOLDER_ENTRY,
                    f"{stats['failed']}/{stats['requested']} 只取数失败",
                )
            else:
                health.record_success("F10十大流通股东", SHAREHOLDER_ENTRY, stats["ok"])
        except Exception:      # noqa: BLE001
            logger.debug("十大流通股东健康度记账失败（已忽略）")
    logger.info(
        f"十大流通股东吞吐: 请求 {stats['requested']} / 成功 {stats['ok']} / 失败 {stats['failed']}"
    )
    return result, stats


def fetch_profit_trends(
    codes6: Iterable[str],
    *,
    with_balance: bool | None = None,
    health: Any | None = None,
) -> tuple[dict[str, ProfitTrend], dict[str, Any]]:
    """批量取多期财报并解析边际拐点。入参为**六位裸码**。"""
    flag = getattr(config, "TRACK_D_TREND_WITH_BALANCE", True) if with_balance is None else with_balance

    def job(f10: Any, code: str) -> Any:
        income = f10.finance_report(code, report_type="lyb")
        if not getattr(income, "ok", False) or not income.tables:
            return None
        balance = None
        if flag:
            try:
                b = f10.finance_report(code, report_type="zcfzb")
                if getattr(b, "ok", False) and b.tables:
                    balance = b.tables[0]
            except Exception:      # noqa: BLE001
                balance = None     # 资产负债表不可得不影响核心的净利润拐点
        return parse_profit_trend(code, income.tables[0], balance)

    result, stats = _fanout(list(codes6), job)
    if health is not None and stats["ok"]:
        try:
            if stats["failed"]:
                health.record_degraded(
                    "F10多期财报", "CWServ.tdxf10_gg_cwfx",
                    f"{stats['failed']}/{stats['requested']} 只取数失败",
                )
            else:
                health.record_success("F10多期财报", "CWServ.tdxf10_gg_cwfx", stats["ok"])
        except Exception:      # noqa: BLE001
            logger.debug("多期财报健康度记账失败（已忽略）")
    logger.info(
        f"多期财报吞吐: 请求 {stats['requested']} / 成功 {stats['ok']} / 失败 {stats['failed']}"
    )
    return result, stats
