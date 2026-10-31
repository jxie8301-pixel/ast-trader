"""HTML report renderer for AST-Trader single stock analysis (aligned with A-share Dual-Track Architecture)."""
from __future__ import annotations

import html
import os
from datetime import datetime
from typing import Any

from presentation.plain_language import (
    PLAIN_PILLAR_TITLES,
    explain_terms,
    generate_plain_triad_coaching,
    one_line_summary,
    plain,
)


def _scenario_block_html(pb: Any) -> str:
    """AI 情景研判区块。**仅在 AI 启用且确实给出研判时**才渲染。

    ★ 明确标注「不含价位」：AI 被明令禁止输出任何价格，
      挂单一律以 `entry_price_range` 为准，避免读者把研判当成价位指令。
    """
    note = getattr(pb, "scenario_note", "") or ""
    if not note.strip():
        return ""
    return f"""
            <div class="pb-item" style="grid-column: 1 / -1;">
                <span class="pb-label">🧭 盘中情景应对（AI 研判 · 不含价位）</span>
                <span class="pb-value" style="white-space: pre-wrap;">{html.escape(plain(note))}</span>
            </div>
            """


def _glossary_section_html(card: dict[str, Any]) -> str:
    """术语速查：★ 只列本报告正文里**真正出现**的说法。

    整表照抄没人会看，按需列出才有效；没有命中就不渲染，避免留个空表头。
    """
    blob = " ".join(
        str(card.get(k) or "")
        for k in (
            "pillar_1_quality", "pillar_2_state", "pillar_3_odds", "pillar_4_path",
            "action_tactic", "core_contradiction", "invalidation_line",
        )
    )
    terms = explain_terms(blob, limit=12)
    if not terms:
        return ""
    rows = "".join(
        f"<tr><td style='color:var(--neon-cyan); white-space:nowrap;'><strong>{html.escape(j)}</strong></td>"
        f"<td>{html.escape(m)}</td></tr>"
        for j, m in terms
    )
    return f"""
        <section class="section-card">
            <h2>📖 术语速查（本报告用到的说法）</h2>
            <table class="table">
                <tbody>{rows}</tbody>
            </table>
        </section>
        """


#: 行动档位 → (徽章样式, 顶部标签)。取值域对齐 pillar5 的六档词汇
#: （core/ai_enrichment.NODE_VERDICT_DOMAIN["node_decision"]）。
#:
#: ★ 20261029 审计 P1-13：原映射只认「买入 / 观察」两档，其余一律落到
#:   ``else → 🔴 回避/空仓`` ——「期权仓(小)」本是可小仓试错的档位，却在报告顶部
#:   被画成「🔴 回避 / 空仓」，与卡片正文的档位和仓位自相矛盾
#:   （reports/002273_SZ_20261029.html）。报告给实盘执行者的必须是唯一结论。
GEAR_BADGE: dict[str, tuple[str, str]] = {
    "核心仓": ("badge-buy", "🟢 进攻 / 核心仓"),
    "期权仓(小)": ("badge-buy", "🟢 试仓 / 小仓位博弈"),
    "等证据临界(观察)": ("badge-watch", "🟡 观察 / 等证据"),
    "不追高(贵但优质)": ("badge-watch", "🟡 观察 / 不追高"),
    "减仓": ("badge-avoid", "🟠 减仓 / 降风险"),
    "回避": ("badge-avoid", "🔴 回避 / 空仓"),
    # 旧报告与其它链路仍可能出现这两档，保留兼容
    "买入": ("badge-buy", "🟢 进攻 / 买入"),
    "观察": ("badge-watch", "🟡 观察 / 试仓"),
}


def gear_display(gear: str, position_cap: float | None = None) -> tuple[str, str]:
    """档位 → (徽章样式, 标签)。

    ★ 未知档位一律以**仓位**兜底：有仓位就不是回避档。旧实现的 ``else`` 分支
      把任何未知档位都画成「🔴 回避 / 空仓」，这正是「档位写着期权仓(小)、顶部
      却标回避空仓」的来源。
    """
    if gear in GEAR_BADGE:
        return GEAR_BADGE[gear]
    if (position_cap or 0.0) > 0:
        return ("badge-watch", f"🟡 观察 / {html.escape(str(gear))}")
    return ("badge-avoid", f"🔴 回避 / {html.escape(str(gear))}")


def render_decision_card_html(card: dict[str, Any], output_path: str | None = None) -> str:
    """将决断卡渲染为独立的离线 HTML 研报 (基于 A 股双轨逻辑与五维实盘支柱)."""
    ticker = card.get("ticker", "未知")
    name = card.get("name", ticker)
    price = card.get("price", 0.0)
    pct_chg = card.get("pct_chg", 0.0)
    gear = card.get("decision_gear", "回避")
    cap = card.get("position_cap", 0.0)
    invalidation = card.get("invalidation_line", "无")
    top3 = card.get("top3_risks", [])
    all_flags = card.get("all_flags", top3)
    youzi = card.get("matched_youzi", [])
    date_str = card.get("trade_date", datetime.now().strftime("%Y%m%d"))
    pb = card.get("playbook") or card.get("execution_playbook")
    matrix = card.get("capital_matrix")

    board_name = card.get("board_name", "主板 (10%涨跌停)")
    track_name = card.get("track_name", "常规标的")
    circ_mv = card.get("circ_mv", 0.0) / 1e8
    turnover = card.get("turnover_ratio", 0.0)
    pe = card.get("pe", 0.0)
    coaching = generate_plain_triad_coaching(card)

    # ★ 财务数据期次：不写出来，读者无法知道报告里的毛利率是哪一期的数。
    #   A 股三张表是累计口径，期次 + 累计口径必须同时标出。
    _pb = card.get("period_basis") or {}
    period_label = str(_pb.get("label") or "")
    period_cum = str(_pb.get("cumulative_desc") or "")
    if period_label and not _pb.get("is_annual"):
        period_strip = (
            f"<span class='meta-item'>财务期次: <strong style='color:#fbbf24;'>"
            f"{html.escape(period_label)}（{html.escape(period_cum)}口径，TTM 滚动）</strong></span>"
        )
    elif period_label:
        period_strip = (
            f"<span class='meta-item'>财务期次: <strong>{html.escape(period_label)}（全年）</strong></span>"
        )
    else:
        period_strip = ""

    # 档位颜色与标识（六档逐档映射，见 GEAR_BADGE）
    gear_badge_class, gear_label = gear_display(gear, cap)

    pct_color = "#ef4444" if pct_chg > 0 else ("#10b981" if pct_chg < 0 else "#94a3b8")
    pct_sign = "+" if pct_chg > 0 else ""

    # Lint 门控机检展示
    lint_findings = card.get("lint_findings") or []
    lint_banner_html = ""
    if lint_findings:
        lint_items = "".join(f"<li>{html.escape(str(item))}</li>" for item in lint_findings)
        lint_banner_html = f"""
        <div style="background: rgba(239, 68, 68, 0.15); border: 1px solid #dc2626; border-radius: 8px; padding: 12px 16px; margin-bottom: 20px;">
            <div style="color: #f87171; font-weight: bold; margin-bottom: 6px;">🛡️ Lint 质量门控机检拦截发现 {len(lint_findings)} 项异常:</div>
            <ul style="color: #fca5a5; font-size: 13px; margin-left: 20px;">{lint_items}</ul>
        </div>
        """

    # 红旗列表渲染
    # 风险清单渲染 (严格去重)
    risk_rows = ""
    seen_flags = set()
    deduped_flags = []
    for r in all_flags:
        f_key = (str(r.get("framework", "")).strip().lower(), str(r.get("title", "")).strip().lower())
        if f_key not in seen_flags:
            seen_flags.add(f_key)
            deduped_flags.append(r)

    for idx, r in enumerate(deduped_flags, 1):
        lvl = r.get("level", "🟡")
        badge_cls = "badge-fatal" if lvl == "🔴" else ("badge-warn" if lvl == "🟠" else "badge-info")
        risk_rows += f"""
        <tr>
            <td style="text-align:center;"><span class="badge {badge_cls}">{lvl} {html.escape(str(r.get('framework', '')))}</span></td>
            <td><strong>{html.escape(str(r.get('title', '')))}</strong></td>
            <td>{html.escape(str(r.get('evidence', '')))}</td>
            <td style="color:#94a3b8; font-size:12px;">{html.escape(str(r.get('threshold', '')))}</td>
        </tr>
        """
    if not risk_rows:
        risk_rows = '<tr><td colspan="4" style="text-align:center; color:#10b981; padding:20px;">✓ 审计与治理指标全面通过，未触发任何严重排雷红旗</td></tr>'

    # 游资战法与席位渲染
    personas = card.get("matched_personas", [])
    youzi_rows = ""
    for p in personas:
        if isinstance(p, dict):
            name_p = p.get("youzi_name", "")
            style_p = p.get("style", "")
            score_p = p.get("fit_score", 0)
            youzi_rows += f"""
            <div class="juror-card">
                <div class="juror-header">
                    <span class="juror-name">⚡ 战法: {html.escape(name_p)}</span>
                    <span class="badge-buy" style="font-size:11px; padding:2px 6px;">契合度 {score_p}分</span>
                </div>
                <div class="juror-comment">{html.escape(style_p)}</div>
            </div>
            """
        elif isinstance(p, str):
            youzi_rows += f"""
            <div class="juror-card">
                <div class="juror-header">
                    <span class="juror-name">⚡ 战法: {html.escape(p)}</span>
                </div>
            </div>
            """

    for y in youzi:
        styles = ", ".join(y.get("styles", []))
        level = y.get("level", "主力")
        tag_color = "#991b1b" if level == "一线顶级游资" else "#1e40af"
        youzi_rows += f"""
        <div class="juror-card">
            <div class="juror-header">
                <span class="juror-name">🏛️ 上榜席位: {html.escape(y.get('youzi_name', ''))}</span>
                <span style="background:{tag_color}; color:#fff; font-size:11px; padding:2px 6px; border-radius:4px;">{level}</span>
            </div>
            <div class="juror-comment">{html.escape(y.get('branch_name', ''))} | 风格: {html.escape(styles)}</div>
        </div>
        """

    # 四维资金博弈雷达 HTML 渲染
    matrix_cards_html = ""
    synergy_score = 0.0
    matrix_verdict_str = "无资金雷达数据"
    dominant_force_str = "存量博弈"
    bull_cat_str = ""
    bear_rk_str = ""

    if matrix:
        if isinstance(matrix, dict):
            synergy_score = float(matrix.get("synergy_score", 0.0) or 0.0)
            matrix_verdict_str = str(matrix.get("matrix_verdict") or matrix.get("verdict") or "中性观望")
            dominant_force_str = str(matrix.get("dominant_force", "存量博弈"))
            bull_cat_str = str(matrix.get("bull_catalyst", ""))
            bear_rk_str = str(matrix.get("bear_risk", ""))
            dims = matrix.get("dimensions", [])
        else:
            synergy_score = getattr(matrix, "synergy_score", 0.0)
            matrix_verdict_str = getattr(matrix, "matrix_verdict", "中性观望")
            dominant_force_str = getattr(matrix, "dominant_force", "存量博弈")
            bull_cat_str = getattr(matrix, "bull_catalyst", "")
            bear_rk_str = getattr(matrix, "bear_risk", "")
            dims = getattr(matrix, "dimensions", [])
        for d in dims:
            d_name = d.get("dimension_name", "") if isinstance(d, dict) else getattr(d, "dimension_name", "")
            d_score = float(d.get("score", 0.0) if isinstance(d, dict) else getattr(d, "score", 0.0))
            d_status = str(d.get("status", "NEUTRAL") if isinstance(d, dict) else getattr(d, "status", "NEUTRAL"))
            d_sum = str(d.get("summary", "") if isinstance(d, dict) else getattr(d, "summary", ""))
            d_badge_color = "#10b981" if d_status == "BULL" else ("#ef4444" if d_status == "VETO" else ("#f59e0b" if d_status == "NEUTRAL" else "#dc2626"))
            matrix_cards_html += f"""
            <div class="juror-card">
                <div class="juror-header">
                    <span class="juror-name">{html.escape(d_name)}</span>
                    <span class="juror-school">得分: {d_score:.0f}分</span>
                    <span class="juror-vote" style="background:{d_badge_color}">{d_status}</span>
                </div>
                <div class="juror-comment">{html.escape(d_sum)}</div>
            </div>
            """

    # 实盘战术执行手册 HTML 渲染
    pb_html = ""
    if pb:
        pb_html = f"""
        <div class="playbook-grid">
            <div class="pb-item">
                <span class="pb-label">行动意图</span>
                <span class="pb-value" style="color:#38bdf8; font-weight:700;">{html.escape(getattr(pb, 'action_label', ''))}</span>
            </div>
            <div class="pb-item">
                <span class="pb-label">买入战术</span>
                <span class="pb-value">{html.escape(getattr(pb, 'entry_tactic', ''))}</span>
            </div>
            <div class="pb-item">
                <span class="pb-label">挂单参考区间</span>
                <span class="pb-value" style="color:#4ade80; font-family:monospace; font-weight:700;">{html.escape(getattr(pb, 'entry_price_range', ''))}</span>
            </div>
            <div class="pb-item">
                <span class="pb-label">仓位配比节奏</span>
                <span class="pb-value">基准首仓 <strong>{getattr(pb, 'base_position_pct', 0)}%</strong> | 确认加仓 <strong>{getattr(pb, 'add_position_pct', 0)}%</strong> | 单票上限 <strong style="color:#f87171">{getattr(pb, 'max_position_pct', 0)}%</strong></span>
            </div>
            <div class="pb-item">
                <span class="pb-label">动态止盈目标</span>
                <span class="pb-value">{html.escape(getattr(pb, 'take_profit_target', ''))}</span>
            </div>
            <div class="pb-item">
                <span class="pb-label">铁律死锁退出线（错了就卖）</span>
                <span class="pb-value" style="color:#f87171; font-weight:700;">{html.escape(getattr(pb, 'invalidation_rule', ''))}</span>
            </div>
            {_scenario_block_html(pb)}
        </div>
        """


    # 数据接口健康度与信息缺口审计 HTML 渲染
    dh = card.get("data_health", {})
    all_health_records = dh.get("all_records", [])
    has_dh_errors = dh.get("has_errors", False)
    total_interfaces = dh.get("total_interfaces", 0)
    failed_interfaces = dh.get("failed_count", 0)
    succ_interfaces = dh.get("success_count", 0)
    empty_interfaces = dh.get("empty_count", 0)

    health_rows = ""
    for r in all_health_records:
        st = r.get("status", "SUCCESS")
        if st == "SUCCESS":
            st_badge = '<span class="badge badge-buy">✓ 成功</span>'
        elif st == "FAILED":
            st_badge = '<span class="badge badge-fatal">🔴 异常失败</span>'
        elif st == "EMPTY":
            st_badge = '<span class="badge badge-warn">🟡 空数据</span>'
        else:
            st_badge = f'<span class="badge badge-info">{html.escape(st)}</span>'

        detail_msg = html.escape(str(r.get("note", "") or ""))
        if st == "FAILED":
            err_type = html.escape(str(r.get("error_type", "")))
            err_msg = html.escape(str(r.get("error_message", "")))
            detail_msg = f'<span style="color:#f87171; font-weight:700;">[{err_type}] {err_msg}</span>'
            if r.get("note"):
                detail_msg += f'<br><span style="color:#fbbf24; font-size:12px;">业务影响: {html.escape(r.get("note"))}</span>'

        health_rows += f"""
        <tr>
            <td><strong>{html.escape(str(r.get('name', '')))}</strong></td>
            <td style="color:#94a3b8; font-size:12px; font-family:monospace;">{html.escape(str(r.get('channel', '')))}</td>
            <td style="text-align:center;">{st_badge}</td>
            <td style="text-align:right; font-family:monospace;">{r.get('record_count', 0)}</td>
            <td style="font-size:13px;">{detail_msg}</td>
        </tr>
        """

    if not health_rows:
        health_rows = '<tr><td colspan="5" style="text-align:center; color:#94a3b8; padding:16px;">未记录接口健康度信息</td></tr>'

    t_odds = card.get("tactical_odds") or (card.get("pillar_5_decision") or {}).get("tactical_odds")
    tactical_odds_html = ""
    if t_odds and isinstance(t_odds, dict):
        if t_odds.get("is_circuit_broken") or gear in ("回避", "减仓") or cap <= 0.0:
            tactical_odds_html = f'''
        <div class="verdict-row" style="background: rgba(239, 68, 68, 0.08); border-left: 3px solid #ef4444; padding: 8px 12px; margin: 10px 0; border-radius: 4px;">
            <strong style="color:#f87171;">⚡ 买方战术赔率熔断:</strong> 
            当前决断为【{html.escape(gear)}】(仓位上限 {cap*100:.0f}%)，启动买方合规熔断，<strong>禁止设定买入区间与向上目标价</strong>，严格执行防守回避。
        </div>
        '''
        else:
            tactical_odds_html = f'''
        <div class="verdict-row" style="background: rgba(16, 185, 129, 0.08); border-left: 3px solid #10b981; padding: 8px 12px; margin: 10px 0; border-radius: 4px;">
            <strong>🎯 买方战术赔率卡:</strong> 
            区间: <strong>{html.escape(str(t_odds.get('entry_range', '')))}</strong> &nbsp;|&nbsp; 
            止损: <strong style="color:#f87171;">{html.escape(str(t_odds.get('stop_loss', '')))}</strong> &nbsp;|&nbsp; 
            目标: <strong style="color:#34d399;">{html.escape(str(t_odds.get('target_price', '')))}</strong> &nbsp;|&nbsp; 
            盈亏比: <strong style="color:#fbbf24;">{html.escape(str(t_odds.get('risk_reward_ratio', '')))}</strong>
        </div>
        '''

    if has_dh_errors or failed_interfaces > 0:
        health_status_banner = f'<span style="color:#ef4444; font-weight:700;">⚠️ 检测到 {failed_interfaces} 个数据通道发生异常阻断 (共调用 {total_interfaces} 个接口，成功 {succ_interfaces} 项，信息存在缺口降级)</span>'
    else:
        health_status_banner = f'<span style="color:#10b981; font-weight:700;">✓ 全通道数据调用健康 (共核验 {total_interfaces} 个接口，成功 {succ_interfaces} 项，空集 {empty_interfaces} 项，零静默拦截)</span>'

    html_content = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>AST-Trader 深度作战研报 - {html.escape(name)} ({html.escape(ticker)})</title>
    <style>
        :root {{
            --bg-void: #090d16;
            --bg-card: #131b2e;
            --bg-elevated: #1e293b;
            --border: #2d3b55;
            --neon-cyan: #38bdf8;
            --neon-gold: #f59e0b;
            --neon-green: #10b981;
            --neon-red: #ef4444;
            --text-main: #f8fafc;
            --text-dim: #94a3b8;
        }}
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{
            background: var(--bg-void);
            color: var(--text-main);
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "PingFang SC", "Microsoft YaHei", sans-serif;
            line-height: 1.6;
            padding: 24px;
        }}
        .container {{ max-width: 1120px; margin: 0 auto; }}
        .header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            background: var(--bg-card);
            padding: 24px 32px;
            border-radius: 12px;
            border: 1px solid var(--border);
            margin-bottom: 24px;
            box-shadow: 0 4px 20px rgba(0, 0, 0, 0.4);
        }}
        .header-title h1 {{ font-size: 28px; font-weight: 800; }}
        .ticker-code {{ font-size: 16px; color: var(--text-dim); font-family: monospace; margin-left: 8px; }}
        .price-badge {{ font-size: 26px; font-weight: 800; margin-left: 16px; }}
        .badge {{
            display: inline-block;
            padding: 6px 14px;
            border-radius: 6px;
            font-weight: 700;
            font-size: 14px;
        }}
        .badge-buy {{ background: rgba(16, 185, 129, 0.2); color: #34d399; border: 1px solid #059669; }}
        .badge-watch {{ background: rgba(245, 158, 11, 0.2); color: #fbbf24; border: 1px solid #d97706; }}
        .badge-avoid {{ background: rgba(239, 68, 68, 0.2); color: #f87171; border: 1px solid #dc2626; }}
        .badge-fatal {{ background: #dc2626; color: #fff; }}
        .badge-warn {{ background: #d97706; color: #fff; }}
        .badge-info {{ background: #2563eb; color: #fff; }}

        .meta-strip {{
            background: var(--bg-elevated);
            padding: 10px 16px;
            border-radius: 8px;
            margin-top: 12px;
            font-size: 13px;
            color: var(--text-dim);
            display: flex;
            gap: 20px;
            flex-wrap: wrap;
        }}
        .meta-item strong {{ color: var(--text-main); }}

        .section-card {{
            background: var(--bg-card);
            border: 1px solid var(--border);
            border-radius: 12px;
            padding: 24px;
            margin-bottom: 24px;
            box-shadow: 0 4px 15px rgba(0,0,0,0.3);
        }}
        .section-card h2 {{
            font-size: 18px;
            margin-bottom: 16px;
            padding-bottom: 8px;
            border-bottom: 1px solid var(--border);
            color: var(--neon-cyan);
            display: flex;
            align-items: center;
            gap: 8px;
        }}

        .pillar-card {{
            background: var(--bg-elevated);
            border-radius: 8px;
            padding: 14px 18px;
            margin-bottom: 12px;
            border-left: 4px solid var(--neon-cyan);
        }}
        .pillar-title {{
            font-weight: 700;
            color: #60a5fa;
            font-size: 14px;
            margin-bottom: 6px;
        }}
        .pillar-content {{
            font-size: 14px;
            color: #f1f5f9;
            line-height: 1.6;
        }}

        .verdict-box {{
            background: rgba(30, 41, 59, 0.7);
            border: 1px solid var(--neon-gold);
            border-radius: 10px;
            padding: 20px;
            margin-bottom: 16px;
        }}
        .verdict-title {{
            font-size: 20px;
            font-weight: 800;
            color: var(--neon-gold);
            margin-bottom: 12px;
        }}
        .verdict-row {{
            margin-bottom: 10px;
            font-size: 14px;
            line-height: 1.6;
        }}

        .playbook-grid {{
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 12px;
        }}
        .pb-item {{
            background: var(--bg-elevated);
            padding: 12px 16px;
            border-radius: 8px;
            border-left: 3px solid var(--neon-gold);
        }}
        .pb-label {{ font-size: 12px; color: var(--text-dim); display: block; margin-bottom: 4px; }}
        .pb-value {{ font-size: 14px; line-height: 1.4; }}

        .table {{ width: 100%; border-collapse: collapse; font-size: 14px; }}
        .table th, .table td {{ padding: 10px 14px; text-align: left; border-bottom: 1px solid var(--border); }}
        .table th {{ background: var(--bg-elevated); color: var(--text-dim); font-weight: 600; }}

        .juror-grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 12px; }}
        .juror-card {{ background: var(--bg-elevated); border-radius: 8px; padding: 12px 16px; border: 1px solid var(--border); }}
        .juror-header {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px; }}
        .juror-name {{ font-weight: 700; color: var(--neon-cyan); }}
        .juror-school {{ font-size: 12px; color: var(--text-dim); }}
        .juror-vote {{ font-size: 11px; font-weight: 800; padding: 2px 8px; border-radius: 4px; color: #fff; }}
        .juror-comment {{ font-size: 13px; color: #cbd5e1; line-height: 1.5; }}

        .footer {{ text-align: center; color: var(--text-dim); font-size: 12px; margin-top: 32px; }}
    </style>
</head>
<body>
    <div class="container">
        {lint_banner_html}
        <!-- 头部概览 -->
        <header class="header">
            <div>
                <h1>{html.escape(name)} <span class="ticker-code">{html.escape(ticker)}</span></h1>
                <span class="price-badge" style="color: {pct_color}">{price:.2f} 元 ({pct_sign}{pct_chg:.2f}%)</span>
                <div class="meta-strip">
                    <span class="meta-item">板块规制: <strong>{html.escape(board_name)}</strong></span>
                    <span class="meta-item">物种属性: <strong>{html.escape(track_name)}</strong></span>
                    <span class="meta-item">流通市值: <strong>{circ_mv:.1f} 亿元</strong></span>
                    <span class="meta-item">换手率: <strong>{turnover:.2f}%</strong></span>
                    <span class="meta-item">PE(TTM): <strong>{pe:.1f}x</strong></span>
                    {period_strip}
                </div>
            </div>
            <div>
                <span class="badge {gear_badge_class}">{gear_label}</span>
            </div>
        </header>

        <!-- 1. 五节点因果决断卡与实战战术 -->
        <section class="section-card">
            <h2>🎯 AST-Trader 五节点因果决断卡 (含实战战术执行)</h2>
            <div class="verdict-box">
                <div class="verdict-title">⚡ 决断档位: {html.escape(gear)} | 建议仓位: <strong>{cap*100:.0f}%</strong></div>
                {f'<div class="verdict-coaching" style="background: rgba(56, 189, 248, 0.12); border-left: 4px solid #38bdf8; padding: 10px 14px; border-radius: 6px; margin-bottom: 14px; color: #bae6fd; font-size: 13.5px; line-height: 1.5;">{html.escape(coaching)}</div>' if coaching else ''}
                <div class="verdict-row"><strong>📌 核心买方矛盾:</strong> {html.escape(card.get('core_contradiction', ''))}</div>
                {tactical_odds_html}
                <div class="verdict-row"><strong>⚡ 实盘操作战术:</strong> {html.escape(card.get('action_tactic', ''))}</div>
                <div class="verdict-row" style="color:#f87171;"><strong>🛑 错了就退（必须守住）:</strong> {html.escape(plain(invalidation))}</div>
            </div>
        </section>

        <!-- 2. 主力行为生命周期透视 -->
        <section class="section-card">
            <h2>⚡ 主力行为生命周期透视 (Main Force Lifecycle)</h2>
            <div class="verdict-box" style="border-color: #38bdf8;">
                <div class="verdict-title" style="color: #38bdf8;">
                    当前阶段: {html.escape(card.get('main_force_stage', '【⏳ 存量震荡/等待方向期】'))} 
                    <span style="font-size:12px; color:#94a3b8; font-weight:normal;">(置信度: {card.get('main_force_confidence', 80.0):.1f}%{(' <span style=\"color:#fbbf24;\">⚠️多空过渡区</span>' if card.get('is_transitional') else '')})</span>
                </div>
                <div class="verdict-row"><strong>🎯 实操动作:</strong> <span style="color:#38bdf8;">{html.escape(card.get('recommended_action', '观望'))}</span> (建议主力仓位上限: <strong>{card.get('position_cap', 0.0)*100:.0f}%</strong>)</div>
                <div class="verdict-row"><strong>🔍 操盘透视:</strong> {html.escape(card.get('main_force_behavior', ''))}</div>
                {"<div class='verdict-row' style='color:#a78bfa;'><strong>🛡️ 反伪装审计:</strong> " + html.escape(' | '.join([x for x in card.get('anti_spoofing_summary', []) if '未检测到明显' not in x])) + "</div>" if [x for x in card.get('anti_spoofing_summary', []) if '未检测到明显' not in x] else ""}
                {f"<div class='verdict-row' style='color:#f87171;'><strong>⚠️ 证伪/突变条件:</strong> {html.escape(str(card.get('main_force_risk', '')))}</div>" if card.get('main_force_risk') else ""}
            </div>
        </section>

        <!-- 2.5 首页「赚不赚钱」数据看板 -->
        <section class="section-card">
            <h2>📊 首页「赚不赚钱」数据看板</h2>
            <div style="margin-bottom:12px; font-size:13px; color:var(--text-dim);">
                {html.escape(card.get('profitability_dashboard', {}).get('industry_reason', ''))}
            </div>
            {f"<div style='margin-bottom:10px; font-size:12px; color:#fbbf24;'>⚠️ 口径标注：最新值为 TTM 滚动 12 个月（截至 {html.escape(period_label)}）；A 股定期报告为年初至今累计口径，趋势序列前段为各年年报，末位 TTM 点为滚动口径，两者不可直接横比。</div>" if period_label and not _pb.get('is_annual') else ""}
            <table class="table">
                <thead>
                    <tr>
                        <th style="width: 180px;">核心指标</th>
                        <th style="width: 120px;">最新数值</th>
                        <th style="width: 220px;">多期趋势与状态</th>
                        <th>避坑警示与主营穿透 (Note)</th>
                    </tr>
                </thead>
                <tbody>
                    {''.join([f"<tr><td><strong>{html.escape(ind.get('name',''))}</strong></td><td style='font-size:16px; font-weight:700; color:#38bdf8;'>{html.escape(ind.get('value',''))}</td><td>[{html.escape(ind.get('status','✓'))}] {html.escape(ind.get('trend',''))}</td><td style='color:#cbd5e1; font-size:12px;'>{html.escape(ind.get('note','') or '—')}</td></tr>" for ind in card.get('profitability_dashboard', {}).get('indicators', [])])}
                </tbody>
            </table>
        </section>

        <!-- 2.6 一句话结论（放在五段正文之前：读者不该被要求先读完黑话才知道能不能买） -->
        <section class="section-card">
            <h2>💡 一句话结论</h2>
            <div class="verdict-box" style="border-color:#fbbf24;">
                <div class="verdict-title" style="color:#fbbf24; white-space: pre-wrap;">{html.escape(one_line_summary(card))}</div>
            </div>
        </section>

        <!-- 3. A股五维实盘支柱 -->
        <section class="section-card">
            <h2>📊 A股五维实盘量化投研支柱 (Five Pillars)</h2>
            <div class="pillar-card" style="border-left-color: #38bdf8;">
                <div class="pillar-title">❶ {PLAIN_PILLAR_TITLES['1'][0]} <span style="font-weight:400; opacity:.7;">— {PLAIN_PILLAR_TITLES['1'][1]}</span></div>
                <div class="pillar-content" style="white-space: pre-wrap;">{html.escape(plain(card.get('pillar_1_quality') or card.get('pillar_gate') or '未接入'))}</div>
            </div>
            <div class="pillar-card" style="border-left-color: #818cf8;">
                <div class="pillar-title">❷ {PLAIN_PILLAR_TITLES['2'][0]} <span style="font-weight:400; opacity:.7;">— {PLAIN_PILLAR_TITLES['2'][1]}</span></div>
                <div class="pillar-content" style="white-space: pre-wrap;">{html.escape(plain(card.get('pillar_2_state') or card.get('pillar_business') or '未接入'))}</div>
            </div>
            <div class="pillar-card" style="border-left-color: #f59e0b;">
                <div class="pillar-title">❸ {PLAIN_PILLAR_TITLES['3'][0]} <span style="font-weight:400; opacity:.7;">— {PLAIN_PILLAR_TITLES['3'][1]}</span></div>
                <div class="pillar-content" style="white-space: pre-wrap;">{html.escape(plain(card.get('pillar_3_odds') or card.get('pillar_tape') or '未接入'))}</div>
            </div>
            <div class="pillar-card" style="border-left-color: #10b981;">
                <div class="pillar-title">❹ {PLAIN_PILLAR_TITLES['4'][0]} <span style="font-weight:400; opacity:.7;">— {PLAIN_PILLAR_TITLES['4'][1]}</span></div>
                <div class="pillar-content" style="white-space: pre-wrap;">{html.escape(plain(card.get('pillar_4_path') or card.get('pillar_flow') or '未接入'))}</div>
            </div>
            <div class="pillar-card" style="border-left-color: #ef4444;">
                <div class="pillar-title">❺ {PLAIN_PILLAR_TITLES['5'][0]} <span style="font-weight:400; opacity:.7;">— {PLAIN_PILLAR_TITLES['5'][1]}</span></div>
                <div class="pillar-content" style="white-space: pre-wrap;"><strong>决断: {html.escape(plain(card.get('decision_title', '')))}</strong>\n{html.escape(plain(card.get('action_tactic', '')))}\n防线: {html.escape(plain(invalidation))}</div>
            </div>
        </section>

        <!-- 3.5 术语速查（只列本报告真正用到的说法） -->
        {_glossary_section_html(card)}

        <!-- 3. 实盘战术执行手册 -->
        <section class="section-card">
            <h2>📋 实盘战术执行手册 (Execution Playbook)</h2>
            {pb_html if pb_html else '<div style="color:var(--text-dim)">未配置实操执行剧本</div>'}
        </section>

        <!-- 4. 四维资金博弈雷达 -->
        <section class="section-card">
            <h2>📊 四维资金博弈雷达 (Capital Force Matrix)</h2>
            <div style="margin-bottom:12px; font-size:13px; color:var(--text-dim);">
                博弈研判: <strong>{html.escape(matrix_verdict_str)}</strong> | 主导力量: <strong style="color:var(--neon-cyan)">{html.escape(dominant_force_str)}</strong> | 合力得分: <strong style="color:var(--neon-green)">{synergy_score:.1f}</strong>
            </div>
            <div class="juror-grid">
                {matrix_cards_html if matrix_cards_html else youzi_rows}
            </div>
        </section>

        <!-- 5. 本土会计审计与治理排雷明细 -->
        <section class="section-card">
            <h2>🛡️ 本土会计审计与治理排雷明细 (Audit Red Flags)</h2>
            <table class="table">
                <thead>
                    <tr>
                        <th style="width: 140px; text-align:center;">红旗级别 / 框架</th>
                        <th style="width: 200px;">风险项</th>
                        <th>审计穿透依据 (Fact Evidence)</th>
                        <th style="width: 160px;">触发阈值</th>
                    </tr>
                </thead>
                <tbody>
                    {risk_rows}
                </tbody>
            </table>
        </section>

        <!-- 6. 数据接口状态与信息缺口审计 -->
        <section class="section-card">
            <h2>📡 数据接口状态与信息缺口审计 (Data Health & Gap Audit)</h2>
            <div style="margin-bottom:12px; font-size:13px;">
                {health_status_banner}
            </div>
            <details style="margin-top: 10px;">
                <summary style="cursor: pointer; color: var(--neon-cyan); font-size: 13px; font-weight: 600; padding: 6px 0; outline: none;">
                    🔍 点击展开 / 收起 {total_interfaces} 项底层数据通道状态明细
                </summary>
                <table class="table" style="margin-top: 12px;">
                    <thead>
                        <tr>
                            <th style="width: 220px;">数据接口名称</th>
                            <th style="width: 170px;">数据通道/源</th>
                            <th style="width: 110px; text-align:center;">调用状态</th>
                            <th style="width: 90px; text-align:right;">记录数</th>
                            <th>异常详情 / 取数审计说明</th>
                        </tr>
                    </thead>
                    <tbody>
                        {health_rows}
                    </tbody>
                </table>
            </details>
        </section>

        <footer class="footer">
            AST-Trader 本地量化投研系统 · 数据引擎: eltdx · 交易日: {date_str}
        </footer>
    </div>
</body>
</html>
"""

    if output_path is None:
        os.makedirs("reports", exist_ok=True)
        safe_ticker = ticker.replace(".", "_")
        output_path = os.path.join("reports", f"{safe_ticker}_{date_str}.html")

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html_content)

    return os.path.abspath(output_path)
