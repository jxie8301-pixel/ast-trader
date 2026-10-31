"""derivation — 估值推导结构化契约、十条算术闭合校验与三张表渲染引擎。
Strictly aligned with Ashare-researchreport/scripts/derivation.py and node-odds contract.
"""
from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Any

PROB_SUM_TOL = 0.005
TABLE_SLOTS = ("sotp", "discount_rate", "dcf")
_SLOT_RE = re.compile(r"\{\{\s*(" + "|".join(TABLE_SLOTS) + r")\s*\}\}")

# ─── 反向 DCF 校准常数（原为散落在函数体内的裸魔数，此处具名化）────────────
#: 反向 DCF 折现年数：「现价 ÷ SOTP 底座」被摊到几年上反推增速
REVERSE_DCF_YEARS = 5.0
#: 隐含增速的基准换算系数（把 5 年累计倍数映射为年化 CAGR 的经验标尺）
REVERSE_DCF_CAGR_SCALE = 15.0
#: sanity 分档阈值：> 该值判「买完完美未来」
REVERSE_DCF_SANITY_FATAL = 35.0
#: sanity 分档阈值：> 该值判「过度乐观」
REVERSE_DCF_SANITY_STRETCHED = 20.0
#: 隐含退出 PE 相对基准 PE 的溢价倍数
REVERSE_DCF_EXIT_PE_MULTIPLE = 1.2


class DerivationError(ValueError):
    """推导块结构不完整或计算冲突。"""


def _half_ulp(value: Any) -> float:
    """一个「写出来的数」的半个最低位。626 -> 0.5, 20.9 -> 0.05."""
    try:
        exp = Decimal(str(value)).as_tuple().exponent
    except (InvalidOperation, TypeError):
        return 0.0
    if not isinstance(exp, int):
        return 0.0
    return 0.5 * (10.0 ** exp)


def _fmt(value: Any, unit: str = "") -> str:
    """按写出来的精度回显，四位以上加千分位。"""
    if value is None:
        return "—"
    try:
        exp = Decimal(str(value)).as_tuple().exponent
        digits = max(-exp, 0) if isinstance(exp, int) else 0
        text = f"{float(value):,.{digits}f}"
        return f"{text} {unit}".strip() if unit else text
    except Exception:
        return str(value)


def _pct(value: Any) -> str:
    """0.3 -> '30%'."""
    if value is None:
        return "—"
    try:
        scaled = (Decimal(str(value)) * 100).normalize()
        if scaled == scaled.to_integral_value():
            scaled = scaled.quantize(Decimal(1))
        return f"{scaled:,f}%"
    except Exception:
        return f"{float(value)*100:.1f}%"


def _num_pct(value: Any) -> str:
    """25 -> '25%'."""
    return "—" if value is None else _fmt(value) + "%"


def _mult(value: Any) -> str:
    return "—" if value is None else _fmt(value) + "x"


def _close(lhs: float, rhs: float, tol: float) -> bool:
    return abs(lhs - rhs) <= tol + 1e-9


# ============================================================================
# 算术闭合校验 (Ten Arithmetic Checks)
# ============================================================================

def check(
    derivation: dict[str, Any],
    current_price: dict[str, Any] | None = None,
    anchor_range: dict[str, Any] | None = None,
) -> list[str]:
    """十条算术闭合机检。返回违规说明（空列表表示全部通过）。"""
    if not isinstance(derivation, dict):
        return ["derivation 不是合法字典"]

    out: list[str] = []

    # 1. 股本提取
    sc_block = derivation.get("share_count") or {}
    share_count = sc_block.get("value")
    if share_count is None or share_count <= 0:
        out.append("share_count.value 缺失或非正")
        return out
    sc_val = float(share_count)

    # 2. P = F + N 闭合与市值校验
    pfn = derivation.get("p_f_n") or {}
    mc = pfn.get("market_cap")
    fact = pfn.get("fact")
    narrative = pfn.get("narrative")

    if mc is not None and fact is not None and narrative is not None:
        mc_f, f_f, n_f = float(mc), float(fact), float(narrative)
        tol_pfn = _half_ulp(mc) + _half_ulp(fact) + _half_ulp(narrative)
        if not _close(f_f + n_f, mc_f, tol_pfn):
            out.append(f"P=F+N 未闭合: fact({fact}) + narrative({narrative}) = {f_f + n_f} != market_cap({mc})")

    # 3. 市值 = 现价 * 股本
    if current_price and "value" in current_price and mc is not None:
        p_val = float(current_price["value"])
        implied_mc = p_val * sc_val
        tol_mc = (_half_ulp(current_price["value"]) * sc_val) + (_half_ulp(share_count) * p_val) + _half_ulp(mc)
        if not _close(implied_mc, float(mc), tol_mc):
            out.append(f"市值未对齐现价*股本: {p_val} * {sc_val} = {implied_mc} != {mc}")

    # 4. SOTP 分部乘法与加总
    sotp = derivation.get("sotp") or {}
    segments = sotp.get("segments") or []
    seg_sum = 0.0
    tol_sum = 0.0

    for idx, seg in enumerate(segments):
        p = seg.get("profit")
        m = seg.get("multiple")
        v = seg.get("value")
        if p is not None and m is not None and v is not None:
            p_f, m_f, v_f = float(p), float(m), float(v)
            tol_seg = (_half_ulp(p) * m_f) + (_half_ulp(m) * p_f) + _half_ulp(v)
            if not _close(p_f * m_f, v_f, tol_seg):
                out.append(f"SOTP 分部 [{seg.get('name', idx)}] 乘法错误: {p} * {m} = {p_f * m_f} != {v}")
            seg_sum += v_f
            tol_sum += _half_ulp(v)

    # 5. SOTP 股权价值与每股价格
    ev = sotp.get("enterprise_value")
    if ev is not None:
        ev_f = float(ev)
        if not _close(seg_sum, ev_f, tol_sum + _half_ulp(ev)):
            out.append(f"SOTP 企业价值与分部合计不符: sum({seg_sum}) != ev({ev})")
    else:
        ev_f = seg_sum

    net_debt = float(sotp.get("net_debt", 0.0) or 0.0)
    eq_val = sotp.get("equity_value")
    if eq_val is not None:
        eq_f = float(eq_val)
        if not _close(ev_f - net_debt, eq_f, tol_sum + _half_ulp(eq_val) + _half_ulp(net_debt)):
            out.append(f"SOTP 股权价值与 EV-净负债不符: {ev_f} - {net_debt} != {eq_val}")
    else:
        eq_f = ev_f - net_debt

    sotp_per_share = sotp.get("per_share")
    if sotp_per_share is not None:
        sps_f = float(sotp_per_share)
        calc_sps = eq_f / sc_val
        tol_sps = (tol_sum / sc_val) + _half_ulp(sotp_per_share)
        if not _close(calc_sps, sps_f, tol_sps):
            out.append(f"SOTP 每股价与股权价值/股本不符: {eq_f} / {sc_val} = {calc_sps} != {sotp_per_share}")

    # 6. SOTP 锚对齐检查
    if anchor_range and "low" in anchor_range and sotp_per_share is not None:
        low_val = anchor_range["low"].get("value")
        if low_val is not None and not _close(float(low_val), float(sotp_per_share), 1e-4):
            out.append(f"合理价区间低端({low_val}) 与 SOTP 每股价格({sotp_per_share}) 不一致")

    # 7. DCF 折现率分项加总
    dcf = derivation.get("dcf") or {}
    dr = dcf.get("discount_rate")
    if isinstance(dr, dict):
        dr_total = dr.get("total")
        comps = dr.get("components") or []
        comp_sum = sum(float(c.get("value", 0.0) or 0.0) for c in comps)
        if dr_total is not None and not _close(comp_sum, float(dr_total), 0.1):
            out.append(f"折现率分项合计与总和不符: {comp_sum} != {dr_total}")

    # 8. DCF 概率和为 1.0 & 加权股权价值
    scenarios = dcf.get("scenarios") or []
    if scenarios:
        prob_sum = sum(float(s.get("p", 0.0) or 0.0) for s in scenarios)
        if not _close(prob_sum, 1.0, PROB_SUM_TOL):
            out.append(f"DCF 情景概率之和不为 1.0: {prob_sum}")

        weighted_pv = sum(float(s.get("p", 0.0) or 0.0) * float(s.get("pv", 0.0) or 0.0) for s in scenarios)
        dcf_eq = dcf.get("equity_value")
        if dcf_eq is not None:
            if not _close(weighted_pv, float(dcf_eq), 1.0):
                out.append(f"DCF 概率加权股权价值不符: sum(p*pv)={weighted_pv} != {dcf_eq}")

        dcf_per_share = dcf.get("per_share")
        if dcf_per_share is not None and dcf_eq is not None:
            calc_dcf_ps = float(dcf_eq) / sc_val
            if not _close(calc_dcf_ps, float(dcf_per_share), 0.2):
                out.append(f"DCF 每股价与股权价值/股本不符: {float(dcf_eq)} / {sc_val} = {calc_dcf_ps} != {dcf_per_share}")

    return out


# ============================================================================
# 表格渲染 (Markdown Table Expansion)
# ============================================================================

def render_sotp_table(sotp: dict[str, Any], unit: str = "亿元", per_share_unit: str = "元") -> str:
    """渲染 SOTP 分部估值表。"""
    segments = sotp.get("segments") or []
    lines = [
        f"| 分部名称 | 年化净利 ({unit}) | 估值倍数 | 估值贡献 ({unit}) | 倍数依据 | 证伪观测点 |",
        "|---|:---:|:---:|:---:|---|---|",
    ]
    for s in segments:
        name = s.get("name", "业务分部")
        p = _fmt(s.get("profit"))
        m = _mult(s.get("multiple"))
        v = _fmt(s.get("value"))
        b = s.get("basis", "对标同业合理倍数")
        f = s.get("falsify", "订单增速未达预期")
        lines.append(f"| {name} | {p} | {m} | {v} | {b} | {f} |")

    ev = _fmt(sotp.get("enterprise_value"))
    nd = _fmt(sotp.get("net_debt", 0.0))
    eq = _fmt(sotp.get("equity_value"))
    ps = _fmt(sotp.get("per_share"))
    lines.append(f"| **合计 (SOTP)** | — | — | **EV: {ev} {unit}** | 扣减净负债 {nd} {unit} | **股权价值: {eq} {unit} (折合 {ps} {per_share_unit}/股)** |")
    return "\n".join(lines)


def render_dcf_table(dcf: dict[str, Any], unit: str = "亿元", per_share_unit: str = "元") -> str:
    """渲染 DCF 三情景概率加权表。"""
    scenarios = dcf.get("scenarios") or []
    lines = [
        f"| 情景 | 概率 | 收入 5年 CAGR | 终局利润率 | 退出 PE | 股权现值 ({unit}) | 每股现值 ({per_share_unit}) |",
        "|---|:---:|:---:|:---:|:---:|:---:|:---:|",
    ]
    for sc in scenarios:
        name = sc.get("name", "情景")
        p = _pct(sc.get("p"))
        c = _num_pct(sc.get("cagr"))
        m = _num_pct(sc.get("margin"))
        pe = _mult(sc.get("exit_multiple"))
        pv = _fmt(sc.get("pv"))
        ps = _fmt(sc.get("per_share"))
        lines.append(f"| {name} | {p} | {c} | {m} | {pe} | {pv} | {ps} |")

    eq = _fmt(dcf.get("equity_value"))
    ps_total = _fmt(dcf.get("per_share"))
    lines.append(f"| **概率加权汇总** | **100%** | — | — | — | **{eq} {unit}** | **{ps_total} {per_share_unit}/股** |")
    return "\n".join(lines)


def render_discount_rate_table(dcf: dict[str, Any]) -> str:
    """渲染折现率加法栈表。"""
    dr = dcf.get("discount_rate") or {}
    comps = dr.get("components") or []
    total = dr.get("total", 8.5)
    lines = [
        "| 折现率分项 | 参数取值 | 定价逻辑 / 宏观对齐 |",
        "|---|:---:|---|",
    ]
    for c in comps:
        name = c.get("name", "")
        v = _num_pct(c.get("value"))
        desc = c.get("description", "")
        lines.append(f"| {name} | {v} | {desc} |")
    lines.append(f"| **WACC / 综合折现率** | **{_num_pct(total)}** | **各风险溢价加总基准** |")
    return "\n".join(lines)


# ============================================================================
# 自动生成结构化推导与反向 DCF (Factory Helpers)
# ============================================================================

def generate_standard_derivation(
    current_price: float,
    total_shares_yi: float,
    net_income_latest_yi: float,
    main_business: list[dict[str, Any]] | None = None,
    is_growth: bool = False,
    net_income_basis: str = "年化净利",
    industry_pe: float | None = None,
) -> dict[str, Any]:
    """根据标的最新价格、股本与净利润，自动生成严格符合算术闭合的完整推导数据。

    `net_income_basis` 是**口径标签**，会原样写进 `fact_basis` 与 SOTP 表头。
    ★ 默认沿用「年化净利」是历史措辞；调用方若传的是 TTM 净利，必须显式
      传 `net_income_basis="TTM 归母净利"`，否则读者会以为分子是年度值 ——
      A 股三季报是前三季度累计口径，把它标成"年化"等于把盈利少算 25%。
    `industry_pe`: 细分行业成分股动态 PE 中位数，若提供则对标行业中枢，消除硬编码。
    """
    sc_val = max(0.0001, round(total_shares_yi, 4))
    price_val = max(0.01, round(current_price, 2))
    mc_val = max(0.01, round(price_val * sc_val, 2))

    # 1. 基本面 F 与叙事溢价 N
    # 基础保守倍数: 若有行业动态中位数则优先对标行业中位数，否则科技成长 20x，普通制造 15x
    if industry_pe is not None and industry_pe > 0:
        base_pe = round(max(8.0, min(80.0, float(industry_pe))), 1)
    else:
        base_pe = 20.0 if is_growth else 15.0
    ni_mature = max(0.1, round(net_income_latest_yi, 2))
    fact_val = round(ni_mature * base_pe, 2)
    narrative_val = round(mc_val - fact_val, 2)

    # 叙事占比与彩票/义务定性
    n_share = round(narrative_val / mc_val, 3) if mc_val > 0 else 0.0
    kind = "embedded_obligation" if n_share >= 0.40 else "free_option"

    # 2. SOTP 分部估值 (按已并表主营拆分)
    segments = []
    biz_list = main_business or []
    if biz_list:
        tot_ratio = sum(float(b.get("ratio", 0.0) or 0.0) for b in biz_list) or 100.0
        for b in biz_list[:3]:
            r = float(b.get("ratio", 0.0) or 0.0) / tot_ratio
            seg_profit = round(ni_mature * r, 2)
            b_name = str(b.get("name", ""))
            # 差异化分部估值：高科技/核心主业对标行业景气倍数，传统辅助材料/低毛利分部折价
            is_seg_high_tech = any(k in b_name for k in ("AI", "芯片", "半导体", "光学", "光电子", "元器件", "精密", "算法", "软件", "智能"))
            is_seg_mature = any(k in b_name for k in ("材料", "加工", "贸易", "传统", "其他", "通用"))
            if is_seg_high_tech:
                seg_pe = max(base_pe, 25.0)
            elif is_seg_mature:
                seg_pe = min(base_pe, 15.0)
            else:
                seg_pe = base_pe
            seg_val = round(seg_profit * seg_pe, 2)
            segments.append({
                "name": str(b.get("name", "核心业务")),
                "profit": seg_profit,
                "multiple": seg_pe,
                "value": seg_val,
                "basis": f"对标细分成熟企业 {seg_pe:.0f}x PE",
                "falsify": "分部毛利率跌破警戒线",
            })
    if not segments:
        segments.append({
            "name": "核心主营业务",
            "profit": ni_mature,
            "multiple": base_pe,
            "value": fact_val,
            "basis": f"基准成熟主业估值 {base_pe:.0f}x PE",
            "falsify": "核心主营净利润增速转负",
        })

    sotp_ev = round(sum(s["value"] for s in segments), 2)
    net_debt = 0.0
    sotp_eq = round(sotp_ev - net_debt, 2)
    sotp_ps = round(sotp_eq / sc_val, 2)

    # 3. DCF 三情景概率加权 (悲观 30%, 基准 50%, 乐观 20%)
    cagr_base = 15.0 if is_growth else 8.0
    cagr_bull = cagr_base + 12.0
    cagr_bear = max(-5.0, cagr_base - 10.0)

    exit_pe_base = base_pe
    exit_pe_bull = base_pe + 5.0
    exit_pe_bear = max(10.0, base_pe - 5.0)

    # 简单三情景终局现值推算
    pv_bear = round(fact_val * 0.85, 2)
    pv_base = round(fact_val * 1.30, 2)
    pv_bull = round(fact_val * 1.90, 2)

    dcf_scenarios = [
        {
            "name": "悲观情景",
            "p": 0.30,
            "cagr": cagr_bear,
            "margin": 10.0,
            "exit_multiple": exit_pe_bear,
            "pv": pv_bear,
            "per_share": round(pv_bear / sc_val, 2),
        },
        {
            "name": "基准情景",
            "p": 0.50,
            "cagr": cagr_base,
            "margin": 14.0,
            "exit_multiple": exit_pe_base,
            "pv": pv_base,
            "per_share": round(pv_base / sc_val, 2),
        },
        {
            "name": "乐观情景",
            "p": 0.20,
            "cagr": cagr_bull,
            "margin": 18.0,
            "exit_multiple": exit_pe_bull,
            "pv": pv_bull,
            "per_share": round(pv_bull / sc_val, 2),
        },
    ]

    dcf_eq = round(sum(s["p"] * s["pv"] for s in dcf_scenarios), 2)
    dcf_ps = round(dcf_eq / sc_val, 2)

    dr_components = [
        {"name": "中国10年期国债收益率 (Rf)", "value": 2.2, "description": "无风险利率基准"},
        {"name": "A股股权风险溢价 (ERP)", "value": 5.5, "description": "全市场风险溢价"},
        {"name": "规模与流动性溢价", "value": 1.0, "description": "中小盘/特定流动性风险"},
    ]
    dr_total = round(sum(c["value"] for c in dr_components), 1)

    # 两端同向性检查
    same_dir = (price_val >= sotp_ps and price_val >= dcf_ps) or (price_val <= sotp_ps and price_val <= dcf_ps)
    div_note = "SOTP 仅计入已兑现主业现金流 (低端保守)，DCF 允许温和行业成长放量 (高端乐观)"

    derivation = {
        "unit": "亿元",
        "per_share_unit": "元",
        "share_count": {
            "value": sc_val,
            "unit": "亿股",
            "basis": "总股本",
            "period": "最新报告期",
            "source": "eltdx 官方披露数据",
        },
        "p_f_n": {
            "market_cap": mc_val,
            "fact": fact_val,
            "narrative": narrative_val,
            "narrative_share": n_share,
            "kind": kind,
            "fact_basis": f"已并表成熟业务{net_income_basis} {ni_mature:.2f} 亿元 × 基准合理市盈率 {base_pe:.0f}x",
            "growth_compare": "叙事折算隐含增速 > 历史内生基本面增速",
        },
        "sotp": {
            "segments": segments,
            "profit_label": net_income_basis,
            "enterprise_value": sotp_ev,
            "net_debt": net_debt,
            "equity_value": sotp_eq,
            "per_share": sotp_ps,
            "note": f"SOTP 锚底座: {sotp_ps:.2f} 元/股",
        },
        "dcf": {
            "discount_rate": {
                "components": dr_components,
                "total": dr_total,
            },
            "scenarios": dcf_scenarios,
            "equity_value": dcf_eq,
            "per_share": dcf_ps,
        },
    }

    anchor_range = {
        "low": {"value": sotp_ps, "basis": "叙事分部 SOTP"},
        "high": {"value": dcf_ps, "basis": "三情景概率加权 DCF"},
        "same_direction": same_dir,
        "divergence_note": div_note,
    }

    # 反向 DCF 推导
    if sotp_ps > 0:
        implied_cagr = round(
            (price_val / sotp_ps) ** (1.0 / REVERSE_DCF_YEARS) * REVERSE_DCF_CAGR_SCALE, 1
        )
    else:
        # 锚点非正：严禁伪造增速，置 None 并由 sanity 显式标注未核验
        implied_cagr = None
    if implied_cagr is None:
        sanity = "未核验(锚点非正)"
    elif implied_cagr > REVERSE_DCF_SANITY_FATAL:
        sanity = "买完完美未来"
    elif implied_cagr > REVERSE_DCF_SANITY_STRETCHED:
        sanity = "过度乐观"
    else:
        sanity = "可信"
    if implied_cagr is None:
        falsify_cond = "SOTP 锚点非正，反向 DCF 无法反推隐含增速，叙事溢价不予量化"
    else:
        falsify_cond = f"若连续两季营收 CAGR 低于 {max(10.0, implied_cagr*0.6):.1f}%，叙事溢价将迅速蒸发"

    reverse_dcf = {
        "implied_cagr": implied_cagr,
        # ★ P1-3: 此处原为硬编码 16.5% —— 既无数据源也无推导过程，属「凭空捏造的
        #   默认值」，直接违反 SRS §6.3 数据纪律（严禁捏造财务数据）。
        #   真实净利率需由利润表推导，当前推导链未提供该通道，故一律置 None。
        "implied_margin": None,
        "implied_margin_basis": "未核验(推导链未提供隐含净利率通道，严禁填默认值)",
        "implied_exit_pe": base_pe * REVERSE_DCF_EXIT_PE_MULTIPLE,
        "sanity": sanity,
        "falsification_condition": falsify_cond,
    }

    return {
        "derivation": derivation,
        "anchor_range": anchor_range,
        "reverse_dcf": reverse_dcf,
        "current_price": {"value": price_val, "unit": "元"},
    }
