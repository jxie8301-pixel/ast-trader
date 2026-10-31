"""行业分类解析 —— 为审计模型提供**适用性准入开关**。

为什么需要这个模块
------------------
Beneish M-Score 与 Altman Z-Score 都是基于**制造业 / 一般工商业**样本校准的
经验判别模型，其变量依赖应收账款、存货、折旧、留存收益等科目。直接套用到
银行业会产生系统性误报：

* 银行没有传统意义的"应收账款/存货"，资产负债结构是"吸收存款 — 发放贷款"，
  代入原模型必然得到畸变的 M 值；
* 实测 601398 工商银行、000001 平安银行均被判出 🔴「财务操纵高风险」
  致命红旗 —— 这对受严格监管的国有大行在先验上就不成立。

本模块把"这家公司属于哪个行业"显式化，让审计模型可以在**自己的校准域之外
主动弃权**，而不是硬算出一个看似精确、实则无意义的分数。

行业来源（按可靠性降序）
------------------------
1. 调用方显式传入的 ``industry``；
2. 证券简称关键词（A 股金融机构的简称里几乎必然带"银行/证券/保险/信托"等，
   这是当前数据通道下最稳定的信号）；
3. 概念题材标签；
4. 主营构成科目名。

无法判定时返回 ``未分类``，此时**保持原有模型行为**并标注适用性未核验。
"""

from __future__ import annotations

from typing import Any

#: 未获取到行业信息时的取值
INDUSTRY_UNKNOWN = "未分类"

#: 金融业
INDUSTRY_FINANCIAL = "金融"

#: 金融业识别关键词（命中任一即归入金融业）
FINANCIAL_KEYWORDS: tuple[str, ...] = (
    "银行",
    "证券",
    "保险",
    "信托",
    "期货",
    "金控",
    "金融租赁",
    "农商行",
    "城商行",
    "信用社",
    # ★ 20261029 审计 P1-10：原词表漏了这两类高频简称 —— "中国人寿""新华保险"
    #   这类公司简称里**只有「人寿 / 财险 / 再保」而没有「保险」二字**（如"中国财险"），
    #   导致它们被判成"未分类"，进而套用制造业校准的审计模型 → 系统性误报。
    "人寿",
    "财险",
    "再保",
    "保险经纪",
)

#: 银行专属结构词（用于从主营构成科目名中识别银行）
BANK_STRUCTURE_KEYWORDS: tuple[str, ...] = (
    "总行",
    "分行",
    "支行",
    "不良贷款",
    "净息差",
    "存贷款",
)


def classify_industry(
    *,
    industry: str | None = None,
    name: str | None = None,
    concepts: list[str] | None = None,
    main_business: list[dict[str, Any]] | None = None,
) -> str:
    """解析标的行业归属（当前仅区分「金融」与「未分类」）。

    Args:
        industry: 调用方已判定的行业，优先采用。
        name: 证券简称，如 "工商银行"。
        concepts: 概念题材标签列表。
        main_business: 主营构成，形如 ``[{"name": ..., "ratio": ...}]``。
    """
    if industry:
        return industry

    blob_parts: list[str] = [name or ""]
    blob_parts.extend(str(c) for c in (concepts or []))
    blob_parts.extend(str((m or {}).get("name", "")) for m in (main_business or []))
    blob = " ".join(blob_parts)

    for kw in FINANCIAL_KEYWORDS:
        if kw in blob:
            return INDUSTRY_FINANCIAL
    for kw in BANK_STRUCTURE_KEYWORDS:
        if kw in blob:
            return INDUSTRY_FINANCIAL

    return INDUSTRY_UNKNOWN


def is_financial(industry: str | None) -> bool:
    """行业是否属于金融业。"""
    if not industry:
        return False
    if industry == INDUSTRY_FINANCIAL:
        return True
    if industry in ("金融", "银行", "非银金融", "证券", "保险"):
        return True
    return any(kw in industry for kw in FINANCIAL_KEYWORDS)
