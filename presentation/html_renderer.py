"""HTML report renderer for AST-Trader single stock analysis (aligned with Bloomberg Bento UI & UZI Panel)."""
from __future__ import annotations

import html
import os
from datetime import datetime
from typing import Any


def render_decision_card_html(card: dict[str, Any], output_path: str | None = None) -> str:
    """将决断卡、实操执行剧本、六大流派陪审团和审计扫雷渲染为独立的离线 HTML 研报。"""
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
    trap_warnings = card.get("trap_warnings", [])
    date_str = card.get("trade_date", datetime.now().strftime("%Y%m%d"))
    pb = card.get("playbook")
    panel_res = card.get("panel_review")

    # 档位颜色与标识
    if gear == "买入":
        gear_badge_class = "badge-buy"
        gear_label = "🟢 进攻 / 买入"
    elif gear == "观察":
        gear_badge_class = "badge-watch"
        gear_label = "🟡 观察 / 试仓"
    else:
        gear_badge_class = "badge-avoid"
        gear_label = "🔴 回避 / 空仓"

    pct_color = "#ef4444" if pct_chg > 0 else ("#10b981" if pct_chg < 0 else "#94a3b8")
    pct_sign = "+" if pct_chg > 0 else ""

    # 红旗列表渲染
    risk_rows = ""
    for idx, r in enumerate(all_flags, 1):
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
    for p in personas[:4]:
        name_p = p.get("youzi_name", "")
        style_p = p.get("style", "")
        score_p = p.get("fit_score", 0)
        entry_p = p.get("entry_condition", "")
        inval_p = p.get("invalidation", "")
        youzi_rows += f"""
        <div class="youzi-card">
            <div class="youzi-header">
                <span class="youzi-name">⚡ 契合战法: {html.escape(name_p)}</span>
                <span class="youzi-tier" style="background:#dc2626">契合度 {score_p}分</span>
            </div>
            <div class="youzi-body">
                <div><strong>核心风格:</strong> {html.escape(style_p)}</div>
                <div><strong>进场信号:</strong> {html.escape(entry_p)}</div>
                <div><strong>逻辑证伪:</strong> <span style="color:#f87171">{html.escape(inval_p)}</span></div>
            </div>
        </div>
        """

    for y in youzi:
        styles = ", ".join(y.get("styles", []))
        level = y.get("level", "主力")
        tag_color = "#991b1b" if level == "一线顶级游资" else "#1e40af"
        youzi_rows += f"""
        <div class="youzi-card">
            <div class="youzi-header">
                <span class="youzi-name">🏛️ 上榜席位: {html.escape(y.get('youzi_name', ''))}</span>
                <span class="youzi-tier" style="background:{tag_color}">{level}</span>
            </div>
            <div class="youzi-body">
                <div><strong>席位:</strong> {html.escape(y.get('branch_name', ''))}</div>
                <div><strong>操盘风格:</strong> {html.escape(styles)}</div>
            </div>
        </div>
        """
    if not youzi_rows:
        youzi_rows = '<div style="color:#94a3b8; padding: 15px;">当前盘口未触发一线游资战法模型，亦未见一线游资席位上榜</div>'

    # 六大流派陪审团 HTML 渲染
    panel_cards_html = ""
    consensus_pct = 0.0
    panel_verdict_str = "无陪审记录"
    bull_arg_str = ""
    bear_arg_str = ""

    if panel_res:
        consensus_pct = panel_res.consensus_pct
        panel_verdict_str = panel_res.panel_verdict
        bull_arg_str = panel_res.bull_argument
        bear_arg_str = panel_res.bear_argument
        for v in panel_res.votes:
            v_badge_color = "#10b981" if v.vote == "BUY" else ("#ef4444" if v.vote == "VETO" else "#f59e0b")
            panel_cards_html += f"""
            <div class="juror-card">
                <div class="juror-header">
                    <span class="juror-name">{html.escape(v.juror_name)}</span>
                    <span class="juror-school">{html.escape(v.school)}</span>
                    <span class="juror-vote" style="background:{v_badge_color}">{v.vote}</span>
                </div>
                <div class="juror-comment">{html.escape(v.comment)}</div>
            </div>
            """

    # 实操执行剧本 HTML 渲染
    pb_html = ""
    if pb:
        pb_html = f"""
        <div class="playbook-grid">
            <div class="pb-item">
                <span class="pb-label">行动意图</span>
                <span class="pb-value" style="color:#38bdf8; font-weight:700;">{html.escape(pb.action_label)}</span>
            </div>
            <div class="pb-item">
                <span class="pb-label">买入战术</span>
                <span class="pb-value">{html.escape(pb.entry_tactic)}</span>
            </div>
            <div class="pb-item">
                <span class="pb-label">挂单参考区间</span>
                <span class="pb-value" style="color:#4ade80; font-family:monospace; font-weight:700;">{html.escape(pb.entry_price_range)}</span>
            </div>
            <div class="pb-item">
                <span class="pb-label">仓位配比节奏</span>
                <span class="pb-value">基准首仓 <strong>{pb.base_position_pct}%</strong> | 确认加仓 <strong>{pb.add_position_pct}%</strong> | 单票上限 <strong style="color:#f87171">{pb.max_position_pct}%</strong></span>
            </div>
            <div class="pb-item">
                <span class="pb-label">动态止盈目标</span>
                <span class="pb-value">{html.escape(pb.take_profit_target)}</span>
            </div>
            <div class="pb-item">
                <span class="pb-label">铁律死锁退出线</span>
                <span class="pb-value" style="color:#f87171; font-weight:700;">{html.escape(pb.invalidation_rule)}</span>
            </div>
        </div>
        """

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

        .decision-chain-node {{
            display: flex;
            padding: 10px 14px;
            margin-bottom: 8px;
            background: var(--bg-elevated);
            border-radius: 8px;
            border-left: 3px solid var(--neon-cyan);
        }}
        .node-tag {{ font-weight: 700; min-width: 160px; color: #60a5fa; }}
        .node-content {{ color: #e2e8f0; }}

        /* 陪审团网格 */
        .jury-overview {{
            background: var(--bg-elevated);
            padding: 16px;
            border-radius: 8px;
            margin-bottom: 16px;
        }}
        .progress-bar {{
            height: 8px;
            background: #334155;
            border-radius: 4px;
            overflow: hidden;
            margin: 8px 0;
        }}
        .progress-fill {{
            height: 100%;
            background: linear-gradient(90deg, #10b981, #38bdf8);
        }}
        .juror-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
            gap: 12px;
        }}
        .juror-card {{
            background: var(--bg-elevated);
            border: 1px solid var(--border);
            border-radius: 8px;
            padding: 12px 16px;
        }}
        .juror-header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 6px;
        }}
        .juror-name {{ font-weight: 700; font-size: 14px; color: #e2e8f0; }}
        .juror-school {{ font-size: 12px; color: var(--text-dim); }}
        .juror-vote {{
            font-size: 11px;
            font-weight: 800;
            padding: 2px 8px;
            border-radius: 4px;
            color: #fff;
        }}
        .juror-comment {{ font-size: 13px; color: #cbd5e1; line-height: 1.5; }}

        /* Playbook 战术卡网格 */
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

        .youzi-grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 14px; }}
        .youzi-card {{ background: var(--bg-elevated); border-radius: 8px; padding: 14px; border: 1px solid var(--border); }}
        .youzi-header {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px; }}
        .youzi-name {{ font-weight: 700; color: var(--neon-cyan); }}
        .youzi-tier {{ font-size: 11px; padding: 2px 6px; border-radius: 4px; color: #fff; }}
        .youzi-body {{ font-size: 13px; color: var(--text-dim); line-height: 1.5; }}

        .footer {{ text-align: center; color: var(--text-dim); font-size: 12px; margin-top: 32px; }}
    </style>
</head>
<body>
    <div class="container">
        <!-- 头部概览 -->
        <header class="header">
            <div>
                <h1>{html.escape(name)} <span class="ticker-code">{html.escape(ticker)}</span></h1>
                <span class="price-badge" style="color: {pct_color}">{price:.2f} 元 ({pct_sign}{pct_chg:.2f}%)</span>
            </div>
            <div>
                <span class="badge {gear_badge_class}">{gear_label}</span>
            </div>
        </header>

        <!-- 1. 五节点因果决断卡 -->
        <section class="section-card">
            <h2>🎯 AST-Trader 五节点闭环作战决断</h2>
            <div class="decision-chain-node">
                <span class="node-tag">① 质地 (成色与造假):</span>
                <span class="node-content">{html.escape(card.get('quality_verdict', ''))}</span>
            </div>
            <div class="decision-chain-node">
                <span class="node-tag">② 状态 (动能与催化):</span>
                <span class="node-content">{html.escape(card.get('state_verdict', ''))}</span>
            </div>
            <div class="decision-chain-node">
                <span class="node-tag">③ 赔率 (空间与估值):</span>
                <span class="node-content">{html.escape(card.get('odds_verdict', ''))}</span>
            </div>
            <div class="decision-chain-node">
                <span class="node-tag">④ 路径 (回撤与共振):</span>
                <span class="node-content">{html.escape(card.get('path_verdict', ''))}</span>
            </div>
            <div class="decision-chain-node" style="border-left-color: #ef4444;">
                <span class="node-tag">⑤ 决策 (档位与失效):</span>
                <span class="node-content">建议仓位: <strong>{cap*100:.0f}%</strong> | 退出失效线: <strong style="color:#f87171">{html.escape(invalidation)}</strong></span>
            </div>
        </section>

        <!-- 2. 实盘战术执行手册 (Execution Playbook) -->
        <section class="section-card">
            <h2>📋 实盘战术执行手册 (Execution Playbook)</h2>
            {pb_html if pb_html else '<div style="color:var(--text-dim)">未配置实操执行剧本</div>'}
        </section>

        <!-- 3. 六大流派大师陪审团 (Investor Panel Jury) -->
        <section class="section-card">
            <h2>🏛️ 全球投资大师与游资陪审团 (Investor Panel Jury)</h2>
            <div class="jury-overview">
                <div style="display:flex; justify-content:space-between; align-items:center;">
                    <span style="font-weight:700;">裁决总评: {panel_verdict_str}</span>
                    <span style="font-size:13px; color:var(--text-dim);">多头赞成率: <strong style="color:var(--neon-green); font-size:16px;">{consensus_pct}%</strong></span>
                </div>
                <div class="progress-bar">
                    <div class="progress-fill" style="width: {consensus_pct}%;"></div>
                </div>
                <div style="margin-top:10px; font-size:13px;">
                    <p style="color:#34d399; margin-bottom:4px;"><strong>▲ 多方主张:</strong> {html.escape(bull_arg_str)}</p>
                    <p style="color:#f87171;"><strong>▼ 空方质疑:</strong> {html.escape(bear_arg_str)}</p>
                </div>
            </div>
            <div class="juror-grid">
                {panel_cards_html}
            </div>
        </section>

        <!-- 4. 24 顶级游资战法契合与龙虎榜席位 -->
        <section class="section-card">
            <h2>⚡ 24 顶级游资战法画像与席位协同 (UZI F_PERSONAS)</h2>
            <div class="youzi-grid">
                {youzi_rows}
            </div>
        </section>

        <!-- 5. 11 会计审计排雷明细 -->
        <section class="section-card">
            <h2>🛡️ 11 会计审计与治理排雷明细 (Audit Red Flags)</h2>
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
