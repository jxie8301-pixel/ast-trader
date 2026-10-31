"""财务基础数据批量吞吐与估值/盈利质量派生。

★ 为什么用 ``corporate.finance_batch`` 而不是 F10
-------------------------------------------------
20261028 实测：

* ``f10.valuation`` → 只返回分页计数 ``{'num': '20', 'total_num': '1211'}``，**没有 PE/PB**；
* ``f10.finance_diagnosis`` → **0 行**；
* ``corporate.finance_batch`` → 一次给出 eps / 每股净资产 / 净利润 / 净资产 /
  经营现金流 / 营收 / 应收账款 / 存货 / 总资产 / 负债 / 股本，**且 100 只仅 0.03s**。

⇒ 轨道 D 的「估值双锚（PE+PB）」「ROE」「经营现金流造血」全部由本模块自算。

★ 两个必须记住的坑
-------------------
1. **静默截断**：请求 300 只**只返回 100 只**。批大小必须 ≤ ``config.FINANCE_BATCH_SIZE``
   (=100)，且必须以**返回记录的 code 建索引**，绝不能假设"请求 N 只回来 N 只"。
2. **单位是千元 / 万股**（非元 / 股）。已用贵州茅台交叉验证：
   ``净资产 251253600(千元) / 总股本 125008.15625(万股) = 200.99 元/股``，
   与该接口自带的 ``mei_gu_jing_zi_chan = 200.99`` 完全一致。
   ``eps`` 字段本身已是元/股，无需换算。

★ 不可核验项
-------------
``finance_batch`` 只给**最新报告期单期快照**。因此：
* ROE **绝对水平**可得；
* ROE **边际拐点（环比斜率）不可得** —— 严禁编造"上期值"来算斜率。
  相关结论一律标记 ``UNVERIFIED``。
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import Any, ClassVar, Iterable, Sequence

import config

logger = logging.getLogger("ast_trader.screener.finance")

#: 金额字段单位（千元）→ 元
_MONEY_SCALE = 1000.0
#: 股本字段单位（万股）→ 股
_SHARE_SCALE = 10000.0


@dataclass(frozen=True)
class FinanceSnapshot:
    """一只标的的财务基础快照（已换算为「元」与「股」）。"""

    full_code: str
    code: str
    #: 数据更新日期（**不是**报告期！）。见下方 report_period 的 ★ 说明。
    report_date: str | None = None
    #: ★ 20261029 审计 P1-3：真实报告期（YYYYMMDD，如 20250331）。
    #   ``finance_batch`` 的 FinanceRecord **没有报告期字段**，只有 ``updated_date``
    #   （数据更新日期）—— 旧代码直接把更新日期当成报告期展示给用户，等于把
    #   "数据哪天更新的"说成"这是哪一期的财报"。真实报告期由本地财报 zip 的
    #   最新可用期反查得到（见 :func:`_latest_report_period`）。
    report_period: str | None = None
    #: 报告期的来源（"archive_latest" / None=未核验）。用于向用户交代可信度。
    report_period_source: str | None = None

    eps: float | None = None                    # 每股收益（元/股）
    bvps: float | None = None                   # 每股净资产（元/股）
    net_profit: float | None = None             # 净利润（元）
    equity: float | None = None                 # 净资产（元）
    operating_cash_flow: float | None = None    # 经营活动现金流（元）
    revenue: float | None = None                # 营业收入（元）
    receivables: float | None = None            # 应收账款（元）
    inventory: float | None = None              # 存货（元）
    total_assets: float | None = None           # 总资产（元）
    total_liabilities: float | None = None      # 总负债（元）
    total_shares: float | None = None           # 总股本（股）
    float_shares: float | None = None           # 流通股本（股）

    # ─────────────────────────────────────────────── 派生指标
    #: 单期 → 全年的年化系数（按报告期月份）。
    #: ★ 20261029 审计 P1-2：``finance_batch`` 给的是**单期** EPS 与净利润
    #:   （如一季度只赚了 1/4 年的钱）。旧代码直接用它算 PE/ROE：
    #:     · 一季度 EPS 算 PE → PE 被高估约 4 倍（"看起来很贵"）；
    #:     · 一季度净利算 ROE → ROE 被低估约 4 倍（"看起来不赚钱"）。
    #:   两者方向相反却同源，会让轨道 D 的"便宜且优质"双判据彻底失真。
    ANNUALIZE_FACTOR: ClassVar[dict[str, float]] = {
        "0331": 4.0,        # 一季报 ×4
        "0630": 2.0,        # 半年报 ×2
        "0930": 4.0 / 3.0,  # 三季报 ×4/3
        "1231": 1.0,        # 年报 ×1
    }

    def annualization_factor(self) -> float | None:
        """单期 → 全年的年化系数；**报告期未知返回 None**（不可核验，严禁猜）。"""
        rp = str(self.report_period or "").strip()
        if len(rp) != 8:
            return None
        return FinanceSnapshot.ANNUALIZE_FACTOR.get(rp[4:])

    def eps_annualized(self) -> float | None:
        """年化 EPS。报告期未知 → ``None``（宁可 PE 不可核验，也不拿单期冒充全年）。"""
        if not self.eps or self.eps <= 0:
            return None
        k = self.annualization_factor()
        return None if k is None else self.eps * k

    def pe(self, price: float | None) -> float | None:
        """市盈率（用**年化** EPS）。eps ≤ 0（亏损）时返回 ``None`` —— PE 无意义，不是 0。

        ★ 报告期不可核验时不给 PE（None），由调用方按"估值未核验"单列，
          绝不用单期 EPS 硬算出一个虚高的 PE 去否决标的。
        """
        eps_a = self.eps_annualized()
        if price is None or eps_a is None or eps_a <= 0:
            return None
        return price / eps_a

    def pe_basis(self) -> str:
        """PE 的口径标签（年化/未核验），供报告与账本如实标注。"""
        rp = str(self.report_period or "")
        k = self.annualization_factor()
        return f"annualized_{rp}" if (k is not None and rp) else "single_period_unverified"

    def pb(self, price: float | None) -> float | None:
        """市净率。净资产为负（资不抵债）时返回 ``None``。"""
        if price is None or not self.bvps or self.bvps <= 0:
            return None
        return price / self.bvps

    def roe_pct(self) -> float | None:
        """ROE(%)，用**年化**净利润。净资产 ≤ 0 时返回 ``None``。

        ★ 报告期不可核验时返回 ``None``（弃权）—— 旧实现用单期净利算出的 ROE
          与"年度 ROE"不是一个量纲，却和 ``TRACK_D_MIN_ROE=8`` 这种**年度**阈值
          直接比较，等于拿季度分去及格线比年度分。
        """
        if not self.net_profit or not self.equity or self.equity <= 0:
            return None
        k = self.annualization_factor()
        if k is None:
            return None
        return self.net_profit * k / self.equity * 100.0

    def roe_basis(self) -> str:
        """ROE 的口径标签（年化/未核验）。"""
        rp = str(self.report_period or "")
        k = self.annualization_factor()
        return f"annualized_{rp}" if (k is not None and rp) else "single_period_unverified"

    def ocf_to_profit(self) -> float | None:
        """经营现金流 / 净利润 —— 利润的"含金量"。

        ★ 净利润 ≤ 0 时分母无意义，返回 ``None``（不能拿负数算出"含金量为正"）。
        """
        if self.operating_cash_flow is None or not self.net_profit or self.net_profit <= 0:
            return None
        return self.operating_cash_flow / self.net_profit

    def debt_ratio_pct(self) -> float | None:
        """资产负债率(%)。"""
        if not self.total_assets or self.total_assets <= 0:
            return None
        if self.total_liabilities is None:
            return None
        return self.total_liabilities / self.total_assets * 100.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "full_code": self.full_code,
            "report_date": self.report_date,              # 数据更新日期（不是报告期）
            "report_period": self.report_period,          # ★ P1-3：真实报告期
            "report_period_source": self.report_period_source,
            "eps": self.eps,
            "bvps": self.bvps,
            "roe_pct": self.roe_pct(),
            "roe_basis": self.roe_basis(),
            "pe_basis": self.pe_basis(),
            "ocf_to_profit": self.ocf_to_profit(),
            "debt_ratio_pct": self.debt_ratio_pct(),
        }


def _opt_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(f) or math.isinf(f) else f


def _money(value: Any) -> float | None:
    """千元 → 元。"""
    v = _opt_float(value)
    return None if v is None else v * _MONEY_SCALE


def _shares(value: Any) -> float | None:
    """万股 → 股。"""
    v = _opt_float(value)
    return None if v is None else v * _SHARE_SCALE


def _latest_report_period() -> str | None:
    """反查**真实报告期**：取本地财报 zip 里最新一个可用报告期（YYYYMMDD）。

    ★ 20261029 审计 P1-3：``finance_batch`` 的 FinanceRecord 只有 ``updated_date``
      （数据更新日期），没有报告期字段 —— 旧代码把它当报告期展示，等于把
      "数据哪天更新"说成"这是哪一期财报"。这里改从财报档案（`data/eltdx_financial`）
      取最新可得报告期；取不到就返回 None（未核验），绝不猜。
    """
    try:
        from data.eltdx_financial import available_periods

        periods = available_periods()
        return str(periods[0]) if periods else None
    except Exception as exc:                                # noqa: BLE001
        logger.debug(f"反查最新报告期失败（按未核验处理）: {exc}")
        return None


def _to_snapshot(raw: Any, report_period: str | None = None) -> FinanceSnapshot | None:
    code = str(getattr(raw, "code", "") or "").strip()
    exchange = str(getattr(raw, "exchange", "") or "").strip().lower()
    if not code or not exchange:
        return None

    d = getattr(raw, "updated_date", None)
    report_date = d.isoformat() if hasattr(d, "isoformat") else (str(d) if d else None)

    return FinanceSnapshot(
        full_code=f"{exchange}{code}",
        code=code,
        report_date=report_date,
        report_period=report_period,
        report_period_source="archive_latest" if report_period else None,
        eps=_opt_float(getattr(raw, "eps_raw", None)),
        bvps=_opt_float(getattr(raw, "mei_gu_jing_zi_chan_raw_float", None)),
        net_profit=_money(getattr(raw, "jing_li_run_raw_float", None)),
        equity=_money(getattr(raw, "jing_zi_chan_raw_float", None)),
        operating_cash_flow=_money(getattr(raw, "jing_ying_xian_jin_liu_raw_float", None)),
        revenue=_money(getattr(raw, "zhu_ying_shou_ru_raw_float", None)),
        receivables=_money(getattr(raw, "ying_shou_zhang_kuan_raw_float", None)),
        inventory=_money(getattr(raw, "cun_huo_raw_float", None)),
        total_assets=_money(getattr(raw, "zong_zi_chan_raw_float", None)),
        # 接口没有"总负债"字段，需自行加总 流动负债 + 长期负债
        total_liabilities=_sum_liabilities(raw),
        total_shares=_shares(getattr(raw, "zong_gu_ben_raw_float", None)),
        float_shares=_shares(getattr(raw, "liu_tong_gu_ben_raw_float", None)),
    )


def _sum_liabilities(raw: Any) -> float | None:
    """总负债 = 流动负债 + 长期负债（千元 → 元）。"""
    cur = _opt_float(getattr(raw, "liu_dong_fu_zhai_raw_float", None))
    long_ = _opt_float(getattr(raw, "chang_qi_fu_zhai_raw_float", None))
    if cur is None and long_ is None:
        return None
    return ((cur or 0.0) + (long_ or 0.0)) * _MONEY_SCALE


def chunk_codes(codes: Sequence[str], batch_size: int) -> list[list[str]]:
    size = max(1, int(batch_size))
    return [list(codes[i:i + size]) for i in range(0, len(codes), size)]


def fetch_finance(
    full_codes: Iterable[str],
    *,
    batch_size: int | None = None,
    health: Any | None = None,
) -> tuple[dict[str, FinanceSnapshot], dict[str, Any]]:
    """批量拉取财务基础数据。

    ★ 批大小硬上限 100：实测 ``finance_batch`` 请求 300 只**静默只返回 100 只**。
      若此处不强制切批，轨道 D 会在完全无告警的情况下丢掉 2/3 的标的 ——
      那将是又一个"静默缩小母池"事故。
    """
    from data.eltdx_client import open_client, with_retry

    codes = [str(c).strip().lower() for c in full_codes if c]
    size = min(int(batch_size or getattr(config, "FINANCE_BATCH_SIZE", 100)), 100)
    batches = chunk_codes(codes, size)

    stats: dict[str, Any] = {
        "requested": len(codes),
        "returned": 0,
        "missing": 0,
        "missing_codes": [],
        "failed_batches": 0,
        "batches": len(batches),
        "batch_size": size,
    }
    result: dict[str, FinanceSnapshot] = {}
    if not codes:
        return result, stats

    # ★ 20261030 修复 N-2 (P1-2回归缺陷)：逐股反查真实报告期，不再全局盲目统一套用。
    #   避免未发三季报的公司被误用三季报年化系数导致 ROE 被低估 33%、PE 高估 50%。
    period_map: dict[str, str] = {}
    try:
        from data.eltdx_financial import report_period_map
        period_map = report_period_map(codes)
        logger.info(f"逐股反查财报报告期完成: {len(period_map)}/{len(codes)} 只匹配到真实披露期次")
    except Exception as exc:
        logger.warning(f"逐股反查财报报告期失败（未匹配公司将按未核验处理）: {exc}")

    try:
        with open_client() as client:
            for idx, batch in enumerate(batches, start=1):
                try:
                    fb = with_retry(
                        lambda b=batch: client.corporate.finance_batch(b),
                        what=f"corporate.finance_batch(batch {idx}/{len(batches)}, n={len(batch)})",
                    )
                except Exception as exc:  # noqa: BLE001
                    stats["failed_batches"] += 1
                    stats["missing_codes"].extend(batch)
                    logger.warning(
                        f"财务批次 {idx}/{len(batches)} 拉取失败（{len(batch)} 只记为 "
                        f"{config.FINANCE_MISSING_REASON}）: {type(exc).__name__}: {exc}"
                    )
                    continue

                for raw in getattr(fb, "records", None) or []:
                    raw_code = str(getattr(raw, "code", "") or "").strip()
                    stock_period = period_map.get(raw_code)
                    snap = _to_snapshot(raw, report_period=stock_period)
                    if snap is not None:
                        result[snap.full_code] = snap
    except Exception as exc:  # noqa: BLE001
        logger.error(f"财务吞吐整体失败: {type(exc).__name__}: {exc}", exc_info=True)
        stats["missing_codes"] = list(codes)

    seen = set(result)
    stats["missing_codes"] = [c for c in codes if c not in seen]
    stats["returned"] = len(result)
    stats["missing"] = len(stats["missing_codes"])

    if health is not None and stats["returned"]:
        try:
            if stats["failed_batches"]:
                health.record_degraded(
                    "全市场财务", "eltdx.corporate.finance_batch",
                    f"{stats['failed_batches']}/{stats['batches']} 批次失败",
                )
            else:
                health.record_success("全市场财务", "eltdx.corporate.finance_batch", stats["returned"])
        except Exception:  # noqa: BLE001
            logger.debug("财务健康度记账失败（已忽略）")

    logger.info(
        f"财务吞吐完成: 请求 {stats['requested']} 只 / 取到 {stats['returned']} 只 / "
        f"缺失 {stats['missing']} 只 (失败批次 {stats['failed_batches']}/{stats['batches']})"
    )
    return result, stats
