"""Pillar 1 Builder: 是不是好公司？(质地五问 · 铁门筛选 · 筛选信号不进估值乘法)."""
from __future__ import annotations

from typing import Any
from core.red_flags import RedFlagItem
from core.types import QualityVerdict, SingleStockContext


def _normalize_pledge_pct(raw: Any) -> float | None:
    """质押率量纲归一 (小数或百分比统一转为 0~100 百分比数值)。"""
    if raw is None:
        return None
    try:
        val = float(raw)
        return val * 100.0 if 0.0 < val <= 1.0 else val
    except (ValueError, TypeError):
        return None


def build_pillar_1_quality(
    ctx: SingleStockContext,
    derived_data: dict[str, Any],
    flags: list[RedFlagItem],
    governance_info: dict[str, Any] | None,
    concept_list: list[str],
    is_fatal: bool,
    fatal_flags: list[RedFlagItem],
    data_health: dict[str, Any] | None,
    ai: dict[str, Any] | None = None,
    nodes: dict[str, Any] | None = None,
) -> QualityVerdict:
    """支柱 ❶: 是不是好公司？(质地五问 · 铁门筛选 · 筛选信号不进乘法)."""
    prof_m = derived_data.get("profitability", {})
    cf_m = derived_data.get("cashflow", {})
    vit_m = derived_data.get("latest_vitals", {})

    gm_val = prof_m.get("gross_margin_latest")
    nm_val = prof_m.get("net_margin_latest")
    c_ratio = cf_m.get("cash_content_latest") if cf_m.get("cash_content_latest") is not None else prof_m.get("cash_content_latest")
    roe_val = prof_m.get("roe_latest")
    inv_ratio = vit_m.get("invest_income_ratio")
    debt_ratio = prof_m.get("debt_to_assets")
    pledge_ratio = _normalize_pledge_pct((governance_info or {}).get("pledge_ratio"))
    pledge_verified = pledge_ratio is not None
    has_reduction = bool((governance_info or {}).get("has_reduction_plan", False))
    mainbz_list = (governance_info or {}).get("main_business", [])

    # Q1: 生意模式赚钱吗
    if gm_val is None or nm_val is None:
        j_biz = "⚠️"
        ev_biz = "毛利率/净利率财务数据缺失或未披露，主营生意盈利能力暂无法核验"
    else:
        j_biz = "✓" if gm_val >= 30.0 and nm_val >= 8.0 else ("⚠️" if gm_val >= 18.0 else "✗")
        ev_biz = f"毛利率 {gm_val:.1f}% / 净利率 {nm_val:.1f}% (行业标杆分位良好，具备一定向下游转嫁定价权)" if j_biz == "✓" else (
            f"毛利率 {gm_val:.1f}% / 净利率 {nm_val:.1f}% (赚辛苦钱，议价权中等)" if j_biz == "⚠️" else
            f"毛利率 {gm_val:.1f}% / 净利率 {nm_val:.1f}% (红海恶性价格战，薄利甚至亏损)"
        )
    if roe_val is not None:
        ev_biz += f"；最新ROE={roe_val:.1f}%"

    # Q2: 赚钱质量真吗
    if c_ratio is None:
        j_quality = "⚠️"
        ev_quality = "现金流数据缺失，赚钱质量与现金含量(OCF/NI)无法核验"
    else:
        inv_r = inv_ratio if inv_ratio is not None else 0.0
        j_quality = "✓" if (c_ratio >= 0.8 and inv_r < 25.0) else ("⚠️" if (c_ratio >= 0.5 and inv_r < 50.0) else "✗")
        if inv_r >= 50.0:
            ev_quality = f"投资收益占营业利润高达 {inv_r:.1f}% (纸面利润严重依赖非主营收益，主营现金流偏弱 OCF/NI={c_ratio:.2f}x)"
        elif c_ratio < 0.5:
            ev_quality = f"现金含量仅 {c_ratio:.2f}x (营收未能有效转化为真金白银现金流，存在应收账款滞压风险)"
        elif c_ratio < 0.8:
            ev_quality = f"现金含量仅 {c_ratio:.2f}x (<0.8x 偏弱)，投资收益占比 {inv_r:.1f}% (利润转化为现金的效率下滑，需盯应收与存货占用)"
        else:
            ev_quality = f"现金含量 {c_ratio:.2f}x，投资收益占比 {inv_r:.1f}% (经营造血充沛，利润真实度高)"

    # Q3: 护城河存在吗
    if not mainbz_list:
        j_moat = "⚠️"
        ev_moat = "主营构成明细缺失或未披露，业务纯度与护城河无法核验"
    else:
        top_biz_ratio = float(mainbz_list[0].get("ratio", 0.0) or 0.0)
        top_biz_name = str(mainbz_list[0].get("name", "主营产品"))
        has_tech_barrier = any("AI" in c or "半导体" in c or "芯片" in c or "算力" in c or "机器人" in c for c in concept_list)
        if top_biz_ratio >= 60.0:
            j_moat = "✓" if (has_tech_barrier or (gm_val is not None and gm_val >= 35.0)) else "⚠️"
            ev_moat = f"核心业务【{top_biz_name}】营收占比 {top_biz_ratio:.1f}%，客户黏性与转换成本较高"
        elif top_biz_ratio >= 30.0:
            j_moat = "⚠️"
            ev_moat = f"核心业务【{top_biz_name}】营收占比 {top_biz_ratio:.1f}%，主营多元分散，单项壁垒无法对全公司完全背书"
        else:
            j_moat = "✗"
            ev_moat = "主营分散且传统，热点概念营收占比极微，缺乏长期结构性护城河"

    # Q4: 管理层可信吗 (含公告语料质押危机特征词代理预警)
    # 扫描上下文或公告语料中是否存在补充质押/展期/冻结
    announcement_texts = [
        str(a.get("title", "")) + " " + str(a.get("content", ""))
        for a in ctx.announcements
    ]
    has_pledge_crisis_signs = any(
        kw in txt for txt in announcement_texts for kw in ("补充质押", "质押展期", "轮候冻结", "被动平仓", "司法冻结")
    )

    if not pledge_verified:
        j_mgmt = "⚠️"
        ev_mgmt = (
            f"{'存在大股东在途减持计划' if has_reduction else '无大股东在途减持计划'}；"
            "大股东质押率未核验 (接口调用异常或无数据)，严禁按「无质押」视为安全线内"
        )
        if has_pledge_crisis_signs:
            ev_mgmt += "；⚠️ 质押危机预警: 近期公告出现补充质押/展期/冻结危机特征，大股东资金链偏紧(提示性预警)"
    elif has_reduction and pledge_ratio >= 40.0:
        j_mgmt = "✗"
        ev_mgmt = f"大股东在途减持计划叠加高质押率 {pledge_ratio:.1f}% (减持意愿强烈，质押平仓风险高企)"
    elif has_reduction or pledge_ratio >= 30.0:
        j_mgmt = "⚠️"
        ev_mgmt = f"{'存在大股东在途减持计划' if has_reduction else ''}{'，' if has_reduction and pledge_ratio>0 else ''}{'大股东质押率 ' + str(round(pledge_ratio,1)) + '%' if pledge_ratio>0 else ''}"
        if has_pledge_crisis_signs:
            ev_mgmt += "；⚠️ 伴随补充质押/展期危机特征(提示性预警)"
    else:
        j_mgmt = "✓"
        ev_mgmt = f"无大股东在途减持计划，质押率 {pledge_ratio:.1f}% 处于安全线内，治理结构相对稳健"
        if has_pledge_crisis_signs:
            j_mgmt = "⚠️"
            ev_mgmt += "；⚠️ 提示: 近期公告出现质押展期或补充质押特征(提示性预警)"

    # Q5: 财务底子稳吗
    if is_fatal:
        j_fin = "✗"
        fatal_titles = "；".join(f.title for f in fatal_flags) if fatal_flags else "未知致命财务红旗"
        ev_fin = f"触发严重财务红旗: {fatal_titles} (资产负债率 {debt_ratio:.1f}%)" if debt_ratio is not None else f"触发严重财务红旗: {fatal_titles}"
    elif debt_ratio is None:
        j_fin = "⚠️"
        ev_fin = "资产负债率数据缺失，财务稳健度无法完全核验"
    elif debt_ratio >= 65.0:
        j_fin = "⚠️"
        ev_fin = f"资产负债率 {debt_ratio:.1f}% 偏高，有息负债偿付压力偏大"
    else:
        j_fin = "✓"
        ev_fin = f"资产负债率 {debt_ratio:.1f}%，短期流动性充裕，破产与债务违约风险极低"

    # 检查数据健康度与接口异常缺口
    failed_names = [f.get("name", "") for f in (data_health or {}).get("failed_details", [])]
    if any("减持" in n for n in failed_names):
        if j_mgmt == "✓":
            j_mgmt = "⚠️"
        ev_mgmt += " (⚠️ 减持计划接口取数异常，在途减持暂无法核验)"
    if any("主营" in n for n in failed_names):
        if j_moat == "✓":
            j_moat = "⚠️"
        ev_moat += " (⚠️ 主营构成接口取数异常，业务纯度暂无法穿透)"
    if any("财务三表" in n or "资产负债" in n or "利润" in n for n in failed_names):
        if j_fin == "✓":
            j_fin = "⚠️"
        ev_fin += " (⚠️ 财务三表部分接口取数异常，财务数据已降级估算)"

    # AI 语义增强（仅当启用）：护城河只允许被降级
    if ai:
        from core.ai_coprocessor import apply_enrichment as _apply_ai

        j_moat = _apply_ai(j_moat, ai.get("moat"))

    sub_verdicts_quality = [
        {"question": "① 生意模式赚钱吗", "judgment": j_biz, "evidence": ev_biz},
        {"question": "② 赚钱质量真吗", "judgment": j_quality, "evidence": ev_quality},
        {"question": "③ 护城河存在吗", "judgment": j_moat, "evidence": ev_moat},
        {"question": "④ 管理层可信吗", "judgment": j_mgmt, "evidence": ev_mgmt},
        {"question": "⑤ 财务底子稳吗", "judgment": j_fin, "evidence": ev_fin},
    ]

    checks = [j_biz, j_quality, j_moat, j_mgmt, j_fin]
    if checks.count("✓") >= 4 and "✗" not in checks:
        quality_verdict = "好"
        quality_desc = "主营盈利扎实、现金流充沛且治理健康，基本面质地优秀"
    elif checks.count("✗") >= 2 or is_fatal:
        quality_verdict = "不好"
        quality_desc = "存在明显财务与治理硬伤或主营持续失血，基本面质地欠佳"
    else:
        quality_verdict = "部分好"
        quality_desc = "具备特定业务或赛道卡位优势，但赚钱质量或治理端存在待解瑕疵"

    # AI 节点推导覆写（非致命红旗时）
    if nodes:
        _node = nodes.get("node_quality")
        _nv = getattr(_node, "verdict", None) if _node else None
        if _nv and not is_fatal:
            quality_verdict = _nv
            quality_desc = "大模型依据判据手册分析数据后判定（推导过程见报告「🧠 AI 分析」段）"

    pillar_quality_summary = (
        f"判定: 【{quality_verdict}】 — {quality_desc} (筛选信号，不进估值乘法)\n"
        + "\n".join([f"  • {sv['question']}: [{sv['judgment']}] {sv['evidence']}" for sv in sub_verdicts_quality])
    )

    return QualityVerdict(
        verdict=quality_verdict,
        pillar_text=pillar_quality_summary,
        sub_verdicts=sub_verdicts_quality,
        fatal_flags=fatal_flags,
        is_fatal=is_fatal,
    )
