"""Pillar 3 Builder: 贵不贵？(P=F+N 叙事溢价拆解 + 反向DCF + [SOTP, DCF]双锚). 严格断流未核验/为负净利润."""
from __future__ import annotations

from typing import Any
import core.derivation as derivation
from core.derivation import generate_standard_derivation
from core.types import OddsVerdict, SingleStockContext


def build_valuation_assumption_note(deriv: dict[str, Any], anchor: dict[str, Any]) -> str:
    """把估值区间的假设前提、口径差异、排除项显式写出来。"""
    sotp = (deriv or {}).get("sotp") or {}
    dcf = (deriv or {}).get("dcf") or {}
    pfn = (deriv or {}).get("p_f_n") or {}

    parts: list[str] = []
    fact_basis = pfn.get("fact_basis")
    if fact_basis:
        parts.append(fact_basis)
    dr_total = (dcf.get("discount_rate") or {}).get("total")
    if dr_total is not None:
        parts.append(f"折现率 {dr_total:.1f}%")
    net_debt = sotp.get("net_debt")
    if net_debt is not None:
        parts.append(f"净负债按 {net_debt:.1f} 亿计")
    segments = sotp.get("segments") or []
    for seg in segments[:1]:
        mult = seg.get("multiple")
        basis = seg.get("basis")
        if mult is not None:
            parts.append(f"分部估值倍数 {mult:.0f}x（{basis or '对标同业'}）")
    scenarios = dcf.get("scenarios") or []
    for sc in scenarios[:1]:
        cagr = sc.get("cagr")
        if cagr is not None:
            parts.append(f"基准情景 5 年收入增速 {cagr:.0f}%")

    lines = [
        "  • 估值假设前提: " + ("；".join(parts) if parts else "未核验(估值元数据缺失)")
    ]

    div_note = (anchor or {}).get("divergence_note")
    if div_note:
        lines.append(f"  • 两端口径差异: {div_note}")

    lines.append(
        "  • ⚠️ 本估值不含: 未并表/未盈利新业务的期权价值（第二增长曲线）。"
        "市场价高于本区间时，差额即为市场对该部分的定价，属另一套假设，"
        "并不代表市场错误"
    )
    return "\n".join(lines)


def build_pillar_3_odds(
    ctx: SingleStockContext,
    price: float,
    total_shares_yi: float,
    pe_val: float,
    total_mv: float,
    derived_data: dict[str, Any],
    is_tech: bool,
    mainbz_list: list[dict[str, Any]],
    nodes: dict[str, Any] | None = None,
    industry_pe_median: float | None = None,
    is_fatal: bool = False,
) -> OddsVerdict:
    """支柱 ❸: 贵不贵？(P=F+N 叙事溢价拆解 + 反向DCF + [SOTP, DCF]双锚). 严格断流未核验/为负净利润.

    ★ `is_fatal` 来自支柱 ❶：存在一票否决致命红旗时，AI 节点无权改动赔率判定
      （20261029 审计 P0-2 —— 支柱 ❶/❹/❺ 都有这道保护，❸ 原本独缺）。
    """
    vit_m = derived_data.get("latest_vitals", {})
    raw_ni = vit_m.get("latest_net_income_ttm")
    if raw_ni is None:
        raw_ni = vit_m.get("latest_net_income")
    ni_is_verified = False
    ni_is_negative = False
    net_income_latest = None

    if raw_ni is not None and raw_ni > 0:
        net_income_latest = raw_ni / 1e8
        ni_is_verified = True
    elif raw_ni is not None:
        ni_is_negative = True
    elif pe_val > 0 and total_mv > 0:
        net_income_latest = (total_mv / pe_val) / 1e8
        ni_is_verified = True

    # 优先取入参或 ctx 中的行业中位数 PE
    if industry_pe_median is None and ctx.industry_valuation:
        industry_pe_median = ctx.industry_valuation.get("pe_median")

    if not ni_is_verified or net_income_latest is None:
        odds_verdict = "未核验(净利润为负)" if ni_is_negative else "未核验(财务缺失)"
        sotp_ps = 0.0
        dcf_ps = 0.0
        deriv = None
        anchor = None
        rdcf = None
        if ni_is_negative:
            pillar_odds_summary = (
                "判定: 【未核验(净利润为负)】 (估值不可计算)\n"
                f"  • 事实: 最新归母净利润为 {raw_ni / 1e8:.2f} 亿元（≤ 0），标的处于亏损或零利润状态。\n"
                "  • 警告: 盈利为负时，市盈率与 DCF / SOTP 现金流折现模型均失去估值基准，"
                "严禁以负利润基数反推隐含增速或价格锚点！\n"
                "  • 买方风控: 缺乏确定性估值底座支持，严禁进行高仓位左侧或右侧重击，单票仓位锁定为 0。"
            )
        else:
            pillar_odds_summary = (
                "判定: 【未核验(财务缺失)】 (估值不可计算)\n"
                "  • 警告: 最新净利润与 PE 估值基准缺失或未核验，严禁根据编造数值生成 DCF / SOTP 价格锚点！\n"
                "  • 买方风控: 缺乏确定性估值底座支持，严禁进行高仓位左侧或右侧重击，单票仓位锁定为 0。"
            )
    else:
        # 支持从 core.judgment_chain 动态查找（兼容既有单测 monkeypatch jc.generate_standard_derivation）
        import sys
        jc_mod = sys.modules.get("core.judgment_chain")
        gen_fn = getattr(jc_mod, "generate_standard_derivation", generate_standard_derivation)

        derivation_result = gen_fn(
            current_price=price,
            total_shares_yi=total_shares_yi,
            net_income_latest_yi=net_income_latest,
            main_business=mainbz_list,
            is_growth=is_tech,
            net_income_basis=(
                "TTM 归母净利" if vit_m.get("latest_net_income_ttm") is not None else "年化净利"
            ),
            industry_pe=industry_pe_median,
        )
        deriv = derivation_result["derivation"]
        anchor = derivation_result["anchor_range"]
        rdcf = derivation_result["reverse_dcf"]
        pfn = deriv["p_f_n"]
        sotp_ps = anchor["low"]["value"]
        dcf_ps = anchor["high"]["value"]

        if price <= sotp_ps:
            odds_verdict = "便宜(有余地)"
        elif price <= dcf_ps:
            odds_verdict = "合理"
        elif rdcf["sanity"] == "买完完美未来":
            odds_verdict = "买完完美未来"
        else:
            odds_verdict = "已被价格计入"

        if nodes:
            _node = nodes.get("node_odds")
            _nv = getattr(_node, "verdict", None) if _node else None
            if _nv and not is_fatal:
                # ★ 20261029 审计 P0-2：原为裸覆写 —— AI 可把「买完完美未来」抬成
                #   「便宜(有余地)」，等于让模型给高估值标的开绿灯。现走降级单向阀：
                #   只能把赔率判得更贵，不能判得更便宜；越界/弃权一律回退规则判定。
                from core.ai_coprocessor import apply_verdict_downgrade_only as _apply_verdict
                odds_verdict = _apply_verdict(odds_verdict, _node, "node_odds")

        ind_note = f" (细分行业成分股动态中位数 {industry_pe_median:.1f}x 对标)" if industry_pe_median else ""
        p_f_n_str = (
            f"市值 {pfn['market_cap']:.1f} 亿 = 基本面底座 F({pfn['fact']:.1f}亿, 占比 {100-pfn['narrative_share']*100:.0f}%){ind_note} "
            f"+ 叙事溢价 N({pfn['narrative']:.1f}亿, 占比 {pfn['narrative_share']*100:.0f}%) "
            f"[{'⚠️ 市场强制交付的硬性义务 (Obligation)' if pfn['kind']=='embedded_obligation' else '✓ 白送的可选彩票 (Free Option)'}]"
        )
        sotp_mult = f"{price / sotp_ps:.2f}x" if sotp_ps > 0 else "N/A(锚点非正)"
        dcf_mult = f"{price / dcf_ps:.2f}x" if dcf_ps > 0 else "N/A(锚点非正)"
        anchor_str = (
            f"区间低端 SOTP={sotp_ps:.2f}元 (只认已兑现利润) | 区间高端 DCF={dcf_ps:.2f}元 (三情景加权) | "
            f"现价({price:.2f}元) = 低端 {sotp_mult} / 高端 {dcf_mult}"
        )
        if rdcf.get("implied_cagr") is None:
            implied_text = "现价隐含增速：未核验(SOTP 锚点非正，无法反推)"
        else:
            implied_text = f"现价隐含 5年收入 CAGR 需达 {rdcf['implied_cagr']:.1f}%"
        rdcf_str = (
            f"{implied_text} (市场预期评估: 【{rdcf['sanity']}】)；"
            f"证伪条件: {rdcf['falsification_condition']}"
        )

        assumption_note = build_valuation_assumption_note(deriv, anchor)
        pillar_odds_summary = (
            f"判定: 【{odds_verdict}】 (双锚同向标记: {'✓ 同向共振' if anchor['same_direction'] else '⚠️ 取决于口径'})\n"
            f"  • P=F+N 叙事拆解: {p_f_n_str}\n"
            f"  • 反向 DCF (市场到底在赌什么): {rdcf_str}\n"
            f"  • 条件锚点 [SOTP, DCF]（基于以下假设，非唯一真理）: {anchor_str}\n"
            f"{assumption_note}"
        )

    return OddsVerdict(
        verdict=odds_verdict,
        pillar_text=pillar_odds_summary,
        sotp_ps=sotp_ps,
        dcf_ps=dcf_ps,
        derivation=deriv,
        anchor_range=anchor,
        reverse_dcf=rdcf,
        ni_is_verified=ni_is_verified,
        industry_pe_median=industry_pe_median,
    )
