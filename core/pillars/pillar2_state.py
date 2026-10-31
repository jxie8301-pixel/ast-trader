"""Pillar 2 Builder: 在变好吗？(状态跃迁 λ · 实锤/回声分级 · 全链唯一「该等什么」)."""
from __future__ import annotations

from typing import Any
from core.types import SingleStockContext, StateVerdict


def build_pillar_2_state(
    ctx: SingleStockContext,
    derived_data: dict[str, Any],
    concept_list: list[str],
    ladder_info: dict[str, Any] | None,
    mainbz_list: list[dict[str, Any]],
    ai: dict[str, Any] | None = None,
    nodes: dict[str, Any] | None = None,
) -> StateVerdict:
    """支柱 ❷: 在变好吗？(状态跃迁 λ · 实锤/回声分级 · 全链唯一「该等什么」)."""
    growth_m = derived_data.get("growth", {})
    rev_yoy = growth_m.get("revenue_yoy_latest")
    ni_yoy = growth_m.get("net_income_yoy_latest")

    has_reorg = any("重组" in c or "国企改革" in c or "并购" in c for c in concept_list)

    top_biz_name = str(mainbz_list[0].get("name", "核心主业")) if mainbz_list else "核心业务"
    top_biz_ratio = float(mainbz_list[0].get("ratio", 0.0) or 0.0) if mainbz_list else 0.0

    search_tech = f"{' '.join(concept_list)} {top_biz_name} {ctx.name if ctx else ''}"
    is_tech = any(k in search_tech for k in (
        "AI", "算力", "半导体", "芯片", "机器人", "光学", "光电子", "电子", "元器件", "消费电子", "智能座舱", "HUD", "精密", "通信"
    ))

    if has_reorg:
        lambda_engine = "国企资产注入/并购重组重塑生产函数预期"
        identity_p = "P4 (重命名重组瓶颈候选)"
    elif is_tech and (rev_yoy is not None and rev_yoy > 0.25):
        lambda_engine = "新兴科技主线景气放量 + 龙头大客户供应链切入"
        identity_p = "P3 (高景气赛道先锋龙头)"
    elif rev_yoy is not None and rev_yoy > 0.15:
        lambda_engine = "主营内生稳健扩产 + 渠道下沉渗透"
        identity_p = "P2 (细分产业优势标的)"
    elif rev_yoy is not None:
        lambda_engine = "存量低速周期震荡"
        identity_p = "P1 (普通行业参与者)"
    else:
        lambda_engine = "增长数据未披露/未确认"
        identity_p = "P1 (普通行业参与者)"

    evidence_hierarchy = []
    if rev_yoy is not None and ni_yoy is not None:
        _pb = derived_data.get("period_basis", {}) or {}
        _lbl = _pb.get("label") or "最新定期报告"
        _cum = _pb.get("cumulative_desc") or ""
        _scope = f"（{_cum}，同比上年同期）" if _cum else ""
        evidence_hierarchy.append(
            f"【实锤】{_lbl}营收 YoY {rev_yoy*100:+.1f}% / 净利 YoY {ni_yoy*100:+.1f}%{_scope} (经财务披露核验)"
        )
    if mainbz_list:
        evidence_hierarchy.append(f"【实锤】核心主业【{top_biz_name}】占比 {top_biz_ratio:.1f}% 并表放量")
    if ladder_info:
        evidence_hierarchy.append(f"【回声/传闻】所属【{ladder_info.get('theme_name','主线')}】题材热度高涨 (券商研报与社群情绪发酵)")
    if not evidence_hierarchy:
        evidence_hierarchy.append("【未确认】主线催化剂尚处于传闻调研阶段，缺乏审计报表与大客户确收实锤")

    ocf_ratio = (derived_data.get("quality_metrics", {}) or {}).get("ocf_to_net_income")
    if has_reorg:
        critical_wait = "等待资产重组预案披露日及交易所问询函回复，重点核验置入标的净资产评估增值率与对赌承诺"
    elif is_tech:
        critical_wait = "等待下次定期报告中科技新品分部营收占比是否持续拓宽，以及下游核心大客户放量确收实锤"
    elif ocf_ratio is not None and ocf_ratio < 0.5:
        critical_wait = "等待行业下游资本开支指引拐点，或下次定期报告中经营现金流 (OCF) 能否实现同比由负转正"
    else:
        critical_wait = "等待行业下游资本开支指引拐点，或下次定期报告中综合毛利率能否维持在行业前列"

    # AI 语义增强（仅当启用）：催化临界点（文本型结论）
    if ai:
        from core.ai_coprocessor import apply_text as _apply_ai_text
        critical_wait = _apply_ai_text(critical_wait, ai.get("catalyst"))

    if rev_yoy and rev_yoy > 0.20 and ni_yoy and ni_yoy > 0.15 and "【实锤】" in evidence_hierarchy[0]:
        state_verdict = "↑变好+证据确认"
    elif ladder_info and ladder_info.get("board_level", 0) >= 2:
        state_verdict = "↑变好但仅注意力·未确认"
    elif rev_yoy and rev_yoy < -0.05:
        state_verdict = "↓变差"
    else:
        state_verdict = "横盘"

    # 大模型节点覆写
    if nodes:
        _node = nodes.get("node_state")
        _nv = getattr(_node, "verdict", None) if _node else None
        if _nv:
            # ★ 20261029 审计 P0-2：此处原为裸覆写 ``state_verdict = _nv`` —— AI 可以
            #   把「↓变差」直接抬成「↑变好+证据确认」，等于给模型开了升级后门。
            #   现统一走降级单向阀：只能变差，不能变好；越界/弃权一律回退规则判定。
            from core.ai_coprocessor import apply_verdict_downgrade_only as _apply_verdict
            state_verdict = _apply_verdict(state_verdict, _node, "node_state")
            _analysis = getattr(_node, "analysis", None) or {}
            _cw = _analysis.get("critical_wait") if isinstance(_analysis, dict) else None
            if isinstance(_cw, str) and _cw.strip():
                critical_wait = _cw.strip()

    pillar_state_summary = (
        f"判定: 【{state_verdict}】 (变好引擎 λ: {lambda_engine})\n"
        f"  • 身份定位: 当前处于【{identity_p}】，升级基本面需真实产业订单接棒\n"
        f"  • 证据分级: {' | '.join(evidence_hierarchy[:2])}\n"
        f"  • 无记忆性警示: 坚决戒除均值回归假象，买入必须由 λ↑ 或证据斜率转正驱动\n"
        f"  • ★ 全链唯一「该等什么」: {critical_wait}"
    )

    return StateVerdict(
        verdict=state_verdict,
        pillar_text=pillar_state_summary,
        critical_wait=critical_wait,
        is_tech=is_tech,
    )
