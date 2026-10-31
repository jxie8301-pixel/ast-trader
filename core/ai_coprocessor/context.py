"""context —— AI 上下文组装（**跨模块共用**，只此一份）。

## 为什么单独抽出来

`moat` / `catalyst` 在 `judgment_chain` 里组装上下文，
`governance` / `theme_purity` 在 `cli` 里组装。若各写一份，
就会出现**两套不一致的证据口径** —— 同一只票，两个模块的 AI 看到
的不是同一批公告，结论互相打脸却无从排查。

## 纪律

· 取不到语料就给空证据，让 AI 依「无证据即弃权」自行弃权，**绝不伪造语料**。
· 所有 prompt 槽位都给默认值，缺失字段不会让调用崩掉（见 `prompts._Defaults`）。
· 量化指标**只引用不重算** —— 这些值来自 `derived_calc`，AI 无权修正。
"""
from __future__ import annotations

import logging
from typing import Any, Sequence

import config

__all__ = ["build_evidence", "build_context", "build_node_context"]


# ═════════════════════════════════════════════════════════════════════
# 判断链五节点专用上下文：**给原始数据，不给半成品结论**
# ═════════════════════════════════════════════════════════════════════
#
# ★ 为什么再单独做一份
#
# `build_context` 只给 4 个加工后标量（毛利率/净利率/ROE/主营构成）。
# 数据少到这种程度，模型**没有可分析的东西**，只能被要求"从几个枚举里
# 选一个" —— 那不是分析，是**填表**。
#
# 要让模型真正分析，必须给：
#   · **时间序列**（趋势比单点值有信息量得多：毛利率连降 4 年 vs 本期 28%）
#   · **结构数据**（分部、现金流 vs 利润、估值 vs 市值）
#   · **对照系**（同业、自身历史分位）
# 本函数把这些**原始面板**铺开，模型自己做拆解与推断。
# ═════════════════════════════════════════════════════════════════════

def _fmt_trend(series: Any, unit: str = "") -> str:
    """[{label, value}] → `2021 32.1% → 2022 30.5% → …`（趋势一眼可见）。"""
    if not isinstance(series, list) or not series:
        return "（无）"
    pts: list[str] = []
    for p in series[-8:]:
        if not isinstance(p, dict):
            continue
        v = p.get("value")
        if v is None:
            continue
        pts.append(f"{p.get('label', '?')} {v}{unit}")
    return " → ".join(pts) if pts else "（无）"


def _is_blank(v: Any) -> bool:
    """判空 —— ★ 不能用 `v not in (None, "", [], {})`。

    真实 `microstructure` 里含 numpy/pandas 容器（ndarray / Series / DataFrame），
    用 `in` 比较会触发**元素级**比较并抛出
    ``ValueError: The truth value of an empty array is ambiguous``
    （实测在 `analyze 002850` 端到端跑到 `_fmt_block` 时必崩）。
    """
    if v is None:
        return True
    if isinstance(v, str):
        return v == ""
    if isinstance(v, (list, tuple, dict, set)):
        return len(v) == 0
    # numpy / pandas 容器用 size 判空，绝不做元素级比较
    size = getattr(v, "size", None)
    if isinstance(size, int):
        return size == 0
    return False


def _fmt_block(obj: Any, *, keys: Sequence[str] | None = None, unit: str = "") -> str:
    """通用块格式化。dict → 逐行；趋势序列 → 箭头串；其他 → str。

    不假设具体键名（各标的字段齐备度不同），避免缺字段就崩。
    """
    if obj is None:
        return "（未提供）"
    if isinstance(obj, dict):
        items = [(k, v) for k, v in obj.items() if not _is_blank(v)]
        if keys:
            items = [(k, v) for k, v in items if k in keys]
        if not items:
            return "（未提供）"
        lines = []
        for k, v in items[:14]:
            if isinstance(v, list) and v and isinstance(v[0], dict) and "value" in v[0]:
                lines.append(f"  {k}: {_fmt_trend(v, unit)}")
            else:
                lines.append(f"  {k}: {v}")
        return "\n".join(lines)
    if isinstance(obj, list):
        return _fmt_trend(obj, unit)
    return str(obj)


def build_node_context(
    ticker: str,
    name: str = "",
    *,
    derived_data: dict[str, Any] | None = None,
    quote: dict[str, Any] | None = None,
    microstructure: dict[str, Any] | None = None,
    mainbz_list: Sequence[dict[str, Any]] | None = None,
    peers: Sequence[dict[str, Any]] | None = None,
    kline_summary: str = "",
    script_flags: Sequence[Any] | None = None,
    evidence_limit: int | None = None,
    **extra: Any,
) -> dict[str, Any]:
    """给判断链五节点的**完整数据面板**。

    返回的 dict 可直接 `prompts.render(module, **ctx)`。
    槽位覆盖：盈利趋势 / 成长 / 现金流 / 估值 / 分部 / 微观 / 行情 / 同业 / 公告。
    """
    d = derived_data or {}
    q = quote or {}
    micro = microstructure or {}
    prof = d.get("profitability") or {}

    evidence, announcements = build_evidence(ticker, limit=evidence_limit)

    flags_txt = "（脚本机算：无）"
    if script_flags:
        flags_txt = "\n".join(
            f"  - [{getattr(f, 'level', '?')}] {getattr(f, 'title', f)}"
            for f in list(script_flags)[:12]
        )

    peers_txt = "（未提供）"
    if peers:
        peers_txt = "\n".join(
            f"  - {p.get('name', '?')}: PE {p.get('pe', '?')} / 毛利率 {p.get('gross_margin', '?')} / 营收增速 {p.get('rev_growth', '?')}"
            for p in list(peers)[:6]
        )

    ctx: dict[str, Any] = {
        "name": name or "（未提供）",
        "ticker": ticker,
        # ── 盈利：给**趋势**而不是单点值 ──
        "profitability": _fmt_block(
            prof, keys=("gross_margin", "net_margin", "roe_latest", "roe", "rev", "ni"), unit="%"
        ),
        "margin_trend": _fmt_trend(prof.get("gross_margin_trend"), "%"),
        "net_margin_trend": _fmt_trend(prof.get("net_margin_trend"), "%"),
        "roe_trend": _fmt_trend(prof.get("roe_trend"), "%"),
        "cash_content_trend": _fmt_trend(prof.get("cash_content_trend"), "x"),
        # ── 报告期与口径 ──
        #   ★ 模型写「若 2026Q2 毛利率跌破 25% 则退出」这类门槛时必须知道当前
        #     已披露到哪一期、是什么口径，否则门槛会锚定到已过期的报告期
        #     （实测：2026 三季报已披露，报告仍在等「2026 一季报/2025 年报」）。
        "period_basis": _fmt_block(d.get("period_basis")) or "（未提供报告期）",
        # ── 成长 / 现金流 / 估值 ──
        "growth": _fmt_block(d.get("growth")),
        "cashflow": _fmt_block(d.get("cashflow")),
        "latest_vitals": _fmt_block(d.get("latest_vitals")),
        "valuation": _fmt_block(
            d.get("valuation") or {
                k: q.get(k) for k in ("pe", "pb", "close", "total_mv", "circ_mv", "turnover_ratio")
                if q.get(k) is not None
            }
        ),
        # ── 结构与对照 ──
        "segments": _fmt_business(mainbz_list) or "（未提供）",
        "peers": peers_txt,
        # ── 微观与行情（原始量，供模型自行权衡）──
        "microstructure": _fmt_block(
            micro,
            keys=(
                "main_force_stage", "main_force_confidence", "smart_vwap",
                "smart_buy_ratio", "smart_sell_ratio", "vol_ratio_20d",
                "avg_amplitude_5d", "price_position_60d", "cum_turnover_20d",
            ),
        ),
        "kline_summary": kline_summary or "（未提供）",
        # ── 脚本机算红旗（不得推翻，只能引用）──
        "script_flags": flags_txt,
        # ── 一手证据 ──
        "evidence": evidence or "（无公告证据；证据不足请弃权）",
        "announcements": announcements or "（无）",
    }
    ctx.update({k: v for k, v in extra.items() if not _is_blank(v)})
    return ctx

logger = logging.getLogger("ast_trader.ai.context")


def build_evidence(ticker: str, *, limit: int | None = None) -> tuple[str, str]:
    """从公告语料池组装 AI 证据。返回 `(证据文本, 公告标题序列)`。

    失败返回空串 —— 由 AI 依「无证据即弃权」规则自行弃权。
    """
    n_docs = limit if limit is not None else config.AI_CONTEXT_MAX_DOCS
    per_doc = config.AI_CONTEXT_CITATIONS_PER_DOC
    evidence_lines: list[str] = []
    ann_lines: list[str] = []
    try:
        from data.announcement_corpus import build_corpus

        corpus = build_corpus(ticker, limit=n_docs)
        for d in corpus.docs:
            ann_lines.append(f"- {d.ann.issue_date[:10]} {d.ann.title}")
            # ★ 修复：`citations()` 是 **Corpus** 的方法，CorpusDoc 只有单数
            #   `citation(i)`。此处原写成 `d.citations(per_doc)`，每次都抛
            #   AttributeError 被下面的 except 吞掉 ⇒ **evidence 恒为空**
            #   ⇒ 所有 AI 模块因「无证据即弃权」长期静默失效。
            for i in range(min(per_doc, len(d.hits))):
                c = d.citation(i)
                if c:
                    evidence_lines.append(f"[P{c['page']}] {c['title']}：{c['quote']}")
    except Exception as exc:                                # noqa: BLE001
        logger.warning("公告语料构建失败，AI 将因无证据而弃权: %s", exc)
    return "\n".join(evidence_lines), "\n".join(ann_lines)


def _fmt_business(mainbz_list: Sequence[dict[str, Any]]) -> str:
    """主营构成 → 一行文本。`revenue_ratio` 缺失时留空，不编造占比。"""
    parts: list[str] = []
    for b in (mainbz_list or [])[:6]:
        name = b.get("name") or b.get("mainbz") or "分部"
        ratio = b.get("revenue_ratio")
        parts.append(f"{name} {ratio}".strip())
    return "；".join(parts)


def build_context(
    ticker: str,
    name: str = "",
    *,
    concepts: Sequence[str] | None = None,
    mainbz_list: Sequence[dict[str, Any]] | None = None,
    derived_data: dict[str, Any] | None = None,
    evidence_limit: int | None = None,
    **extra: Any,
) -> dict[str, Any]:
    """组装 AI 上下文。返回的 dict 可直接 `prompts.render(module, **ctx)`。

    `extra` 用于补充模块专属槽位（如 `gear` / `seats` / `market_regime`），
    同名键会覆盖默认值。
    """
    prof = (derived_data or {}).get("profitability", {}) or {}
    evidence, announcements = build_evidence(ticker, limit=evidence_limit)

    ctx: dict[str, Any] = {
        "name": name or "（未提供）",
        "ticker": ticker,
        "concepts": "、".join(concepts or []) or "（未提供）",
        "business_composition": _fmt_business(mainbz_list) or "（未提供）",
        "gross_margin": prof.get("gross_margin") or "（未提供）",
        "net_margin": prof.get("net_margin") or "（未提供）",
        "roe": prof.get("roe") or "（未提供）",
        "evidence": evidence or "（无公告证据；证据不足请弃权）",
        "announcements": announcements or "（无）",
        # 以下槽位由调用方按需覆盖
        "state_verdict": "（未提供）",
        "gear": "（未提供）",
        "seats": "（未提供）",
        "market_regime": "（未提供）",
    }
    ctx.update({k: v for k, v in extra.items() if not _is_blank(v)})
    return ctx
