"""Rich terminal rendering for AST-Trader, strictly aligned with Ashare & UZI contracts."""
from __future__ import annotations

from typing import Any

from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from presentation.plain_language import (
    PLAIN_PILLAR_TITLES,
    generate_plain_triad_coaching,
    explain_terms,
    one_line_summary,
    plain,
)

console = Console()


def _draw_sparkline(points: list[dict[str, Any]]) -> str:
    """基于 Unicode 字符绘制紧凑迷你走势线 ( ▂▃▄▅▆▇█)."""
    if not points or len(points) < 2:
        return ""
    vals = [float(p.get("value", 0.0)) for p in points]
    min_v, max_v = min(vals), max(vals)
    if max_v == min_v:
        return "▄" * len(vals)
    bars = " ▂▃▄▅▆▇█"
    out = []
    for v in vals:
        idx = int((v - min_v) / (max_v - min_v) * (len(bars) - 1))
        out.append(bars[min(len(bars) - 1, max(0, idx))])
    return "".join(out)


def print_decision_card(card: dict[str, Any], verbose: bool = False) -> None:
    """在终端渲染单股决断卡 (深度整合质地五问、赚不赚钱看板、状态跃迁、估值双锚、主力行为与双轨实战决断)."""
    gear = card.get("decision_gear", "观察")
    gear_color = "red" if "回避" in gear else ("green" if "做多" in gear or "核心" in gear or "买入" in gear else "yellow")
    gear_style = f"[{gear_color} bold]【{gear}】[/{gear_color} bold]"

    ticker = card.get("ticker", "")
    name = card.get("name", "")
    price = card.get("price", 0.0)
    pct = card.get("pct_chg", 0.0)
    pct_color = "red" if pct > 0 else ("green" if pct < 0 else "white")
    board_name = card.get("board_name", "主板 (10%涨跌停)")
    track_name = card.get("track_name", "常规标的")

    circ_mv = card.get("circ_mv", 0.0) / 1e8
    total_mv = card.get("total_mv", 0.0) / 1e8
    turnover = card.get("turnover_ratio", 0.0)
    pe = card.get("pe", 0.0)

    # 1. 标的基本面与行情抬头
    header_info = (
        f"[bold white]{name}[/bold white] ([cyan]{ticker}[/cyan])  |  "
        f"现价: [bold]{price:.2f}[/bold]元 ([{pct_color}]{pct:+.2f}%[/{pct_color}])  |  "
        f"换手: [bold]{turnover:.2f}%[/bold]  |  "
        f"PE(TTM): [bold]{pe:.1f}x[/bold]"
    )
    mf_stage = card.get("main_force_stage", "【⏳ 存量震荡/等待方向期】")
    mf_conf = float(card.get("main_force_confidence", 80.0) or 80.0)
    is_trans = bool(card.get("is_transitional", False))
    trans_tag = " [bold yellow](⚠️多空过渡区)[/bold yellow]" if is_trans else ""

    sub_header = (
        f"板块规制: [bold cyan]{board_name}[/bold cyan]  |  "
        f"物种定位: [bold yellow]{track_name}[/bold yellow] (流通: {circ_mv:.1f}亿 / 总值: {total_mv:.1f}亿)\n"
        f"主力阶段: [bold magenta]{mf_stage}[/bold magenta] (置信度: [bold cyan]{mf_conf:.1f}%[/bold cyan]{trans_tag})  |  "
        f"决断档位: {gear_style}"
    )

    # ★ 一句话结论放在最上面：读者不该被要求先读完五段黑话才知道能不能买
    summary_line = f"[bold white on grey23]💡 一句话结论:[/bold white on grey23] [bold]{one_line_summary(card)}[/bold]"
    coaching_line = f"[bold yellow]{generate_plain_triad_coaching(card)}[/bold yellow]"

    body_lines = [
        header_info,
        sub_header,
        "[dim]─" * 78 + "[/dim]",
        summary_line,
        coaching_line,
        "[dim]─" * 78 + "[/dim]",
    ]

    # 2. 首页「赚不赚钱」数据看板 (Profitability Dashboard)
    dashboard = card.get("profitability_dashboard") or {}
    indicators = dashboard.get("indicators") or []
    if indicators:
        dash_lines = [
            f"[bold green]📊 首页「赚不赚钱」数据看板:[/bold green] [dim]{dashboard.get('industry_reason', '')}[/dim]"
        ]
        for ind in indicators:
            s_obj = ind.get("series")
            spark = ""
            if s_obj and s_obj.get("points"):
                pts = s_obj["points"]
                spark_bars = _draw_sparkline(pts)
                p_labels = f"({pts[0]['label']}~{pts[-1]['label']})"
                spark = f" [bold cyan]{spark_bars}[/bold cyan] [dim]{p_labels}[/dim]"

            st = ind.get("status", "✓")
            st_color = "green" if st == "✓" else ("yellow" if st == "⚠️" else "red")
            val_str = ind.get("value", "")
            trend_str = ind.get("trend", "")
            note_str = ind.get("note", "")
            note_desc = f" [dim]| 注: {note_str}[/dim]" if note_str else ""
            dash_lines.append(
                f"  [{st_color}]{st}[/{st_color}] [bold]{ind['name']}:[/bold] [bold white]{val_str}[/bold white]{spark} — {trend_str}{note_desc}"
            )
        body_lines.append("\n".join(dash_lines))
        body_lines.append("[dim]─" * 78 + "[/dim]")

    # 3. 五大核心支柱 (严格按新版买方框架)
    p1 = card.get("pillar_1_quality") or card.get("pillar_audit") or "未接入"
    p2 = card.get("pillar_2_state") or card.get("pillar_business") or "未接入"
    p3 = card.get("pillar_3_odds") or card.get("pillar_tape") or "未接入"
    p4 = card.get("pillar_4_path") or card.get("pillar_flow") or "未接入"
    p5_dict = card.get("pillar_5_decision") or {}

    t1, d1 = PLAIN_PILLAR_TITLES["1"]
    t2, d2 = PLAIN_PILLAR_TITLES["2"]
    t3, d3 = PLAIN_PILLAR_TITLES["3"]
    t4, d4 = PLAIN_PILLAR_TITLES["4"]
    t5, d5 = PLAIN_PILLAR_TITLES["5"]

    body_lines.extend([
        f"[bold cyan]❶ {t1}[/bold cyan] [dim]({d1})[/dim]\n  {plain(p1)}",
        f"[bold cyan]❷ {t2}[/bold cyan] [dim]({d2})[/dim]\n  {plain(p2)}",
        f"[bold cyan]❸ {t3}[/bold cyan] [dim]({d3})[/dim]\n  {plain(p3)}",
        f"[bold cyan]❹ {t4}[/bold cyan] [dim]({d4})[/dim]\n  {plain(p4)}",
        "[dim]─" * 78 + "[/dim]",
        f"[bold yellow]❺ {t5}[/bold yellow] [dim]({d5})[/dim] —— "
        f"[bold]{card.get('decision_title', '')}[/bold] "
        f"(能买多少: [bold yellow]{card.get('position_cap', 0.0)*100:.0f}%[/bold yellow])",
        f"  • [bold]三句话结论:[/bold] {p5_dict.get('triad_verdict', '')}",
        f"  • [bold]买方判定:[/bold] {p5_dict.get('three_part_conclusion', '')}",
        f"  • [bold]监管状态:[/bold] {p5_dict.get('regulatory_status', '')}",
    ])
    t_odds = p5_dict.get("tactical_odds") or card.get("tactical_odds")
    if t_odds and isinstance(t_odds, dict):
        body_lines.append(
            f"  • [bold]🎯 买方战术赔率卡:[/bold] 区间: {t_odds.get('entry_range', '')} | 目标: {t_odds.get('target_price', '')} | 止损: {t_odds.get('stop_loss', '')} | 盈亏比: [bold green]{t_odds.get('risk_reward_ratio', '')}[/bold green]"
        )
    body_lines.extend([
        f"[bold yellow]📌 核心矛盾（多空最关键的拉扯）:[/bold yellow] {plain(card.get('core_contradiction', ''))}",
        f"[bold yellow]⚡ 怎么买:[/bold yellow]\n  {plain(card.get('action_tactic', ''))}",
        f"[bold red]🛑 错了就退（必须守住）:[/bold red]\n  {plain(card.get('invalidation_line', ''))}",
    ])

    # ★ AI 情景研判：仅在 AI 启用时非空。刻意标注「不含价位」——
    #   AI 被明令禁止输出价格，价位一律以 execution_playbook 为准。
    pb_obj = card.get("playbook") or card.get("execution_playbook")
    scenario = getattr(pb_obj, "scenario_note", "") or ""
    if scenario:
        body_lines.append(
            f"[bold magenta]🧭 盘中情景应对 (AI 研判 · 不含价位):[/bold magenta]\n  {plain(scenario)}"
        )


    # 4. 数据链路健康度与信息缺口检测 (严格禁止静默 pass，显性化披露)
    dh = card.get("data_health") or {}
    if dh:
        total_if = dh.get("total_interfaces", 0)
        succ_if = dh.get("success_count", 0)
        fail_if = dh.get("failed_count", 0)
        empty_if = dh.get("empty_count", 0)
        has_err = dh.get("has_errors", False)

        dh_lines = []
        if has_err or fail_if > 0:
            dh_lines.append(f"[bold red]📡 数据接口状态与信息缺口审计: ⚠️ 检测到 {fail_if} 项接口取数异常 (共调用 {total_if} 个通道，成功 {succ_if})[/bold red]")
            for rec in dh.get("failed_details", []):
                dh_lines.append(f"  • [bold red]✗ 异常接口:[/bold red] [bold white]{rec.get('name')}[/bold white] (通道: {rec.get('channel')})")
                dh_lines.append(f"    [red]报错: [{rec.get('error_type')}] {rec.get('error_message')}[/red]")
                if rec.get("note"):
                    dh_lines.append(f"    [yellow]影响: {rec.get('note')}[/yellow]")
            body_lines.append("[dim]─" * 78 + "[/dim]")
            body_lines.append("\n".join(dh_lines))
        elif verbose:
            dh_lines.append(f"[bold green]📡 数据接口状态与信息缺口审计:[/bold green] [green]✓ 全通道取数健康 (已核验全部 {total_if} 个数据接口，成功 {succ_if} 项，空集 {empty_if} 项，零报错阻断)[/green]")
            body_lines.append("[dim]─" * 78 + "[/dim]")
            body_lines.append("\n".join(dh_lines))
        else:
            body_lines.append(f"[dim]📡 数据链路: ✓ 全通道健康 ({total_if}/{total_if} 接口核验无异常)[/dim]")

    # 5. Lint 质量门控异常检视
    lint_findings = card.get("lint_findings") or []
    if lint_findings:
        lint_lines = [f"[bold red]🛡️ Lint 质量门控机检拦截警示 ({len(lint_findings)} 项):[/bold red]"]
        for item in lint_findings:
            lint_lines.append(f"  • [red]{item}[/red]")
        body_lines.append("[dim]─" * 78 + "[/dim]")
        body_lines.append("\n".join(lint_lines))

    # 术语解释：★ 只列正文里**真正出现**的词 —— 整表照抄没人会看
    terms = explain_terms(
        " ".join(
            str(x)
            for x in (p1, p2, p3, p4, card.get("action_tactic", ""), card.get("core_contradiction", ""))
        ),
        limit=10,
    )
    if terms:
        term_lines = ["[dim]📖 本报告用到的说法:[/dim]"]
        term_lines += [f"  [dim]· {j}[/dim] = {m}" for j, m in terms]
        body_lines.append("[dim]─" * 78 + "[/dim]")
        body_lines.append("\n".join(term_lines))

    panel = Panel(
        "\n\n".join([body_lines[0], body_lines[1]]) + "\n" + "\n\n".join(body_lines[2:]),
        title=f"🎯 [bold yellow]AST-Trader A股买方投研决断卡 (深度版)[/bold yellow]",
        border_style=gear_color,
    )
    console.print(panel)
    if verbose:
        _print_ai_analysis(card)


#: AI 节点 → 中文名（报告里不裸暴露模块名）
_NODE_TITLES: dict[str, str] = {
    "node_quality": "① 质地",
    "node_state": "② 状态",
    "node_odds": "③ 赔率",
    "node_path": "④ 路径",
    "node_decision": "⑤ 决策",
}

#: analysis 字段 → 中文标签
_FIELD_TITLES: dict[str, str] = {
    "derivation": "推导过程",
    "critical_wait": "该等什么（临界点）",
    "falsification": "证伪/退出清单",
    "left_tail_list": "左尾清单",
    "sub_verdicts": "子判定",
    "cap_check": "封顶检查",
    "action_detail": "裁决理由",
    "verdict_note": "口径说明",
}


def _print_ai_analysis(card: dict[str, Any]) -> None:
    """渲染模型的推导过程与语义挖掘结果 —— 独立「🧠 买方 AI 穿透视界」高亮专栏。"""
    aa = card.get("ai_analysis") or {}
    ai_map = card.get("ai_enrichment") or {}
    if not aa and not ai_map:
        return

    lines = []
    # 1. 语义挖掘结果
    for mod_name, item in ai_map.items():
        if item is not None:
            analysis_txt = getattr(item, "analysis", None) or getattr(item, "reason", None)
            if analysis_txt:
                lines.append(f"[bold cyan]🔍 【{mod_name} 语义穿透】[/bold cyan]")
                lines.append(f"  {analysis_txt}")

    # 2. 五节点推导过程
    for m in sorted(aa):
        lines.append(f"[bold cyan]【{_NODE_TITLES.get(m, m)} · {m}】[/bold cyan]")
        for k, v in (aa[m] or {}).items():
            label = _FIELD_TITLES.get(k, k)
            if isinstance(v, list) and v and all(isinstance(i, dict) for i in v):
                lines.append(f"  [dim]{label}:[/dim]")
                for item in v:
                    lines.append(f"    {item.get('judgment', '')} {item.get('question', item)}")
                continue
            lines.append(f"  [dim]{label}:[/dim] {v}")

    if lines:
        panel = Panel(
            "\n".join(lines),
            title="🧠 [bold cyan]买方 AI 穿透视界 (深度语义挖掘与可审计推导)[/bold cyan]",
            border_style="cyan",
        )
        console.print()
        console.print(panel)



def print_universe_panel(universe: Any, funnel: Any = None) -> None:
    """渲染「沪深全市场母池对账」面板 —— 用来**证明这次真的扫了全市场**。

    ★ 没有这个面板，"全市场筛选"只是一句无法证伪的口号：改造前候选池来自
      涨停天梯（约 71 只 / 5225 只 ≈ 1.4%），却对外宣称全市场。现在每次跑批
      都必须先自报家门：扫了多少、预期多少、剔了什么、每层淘汰多少。
    """
    if universe is None:
        return

    scanned = getattr(universe, "scanned_total", 0)
    expected = getattr(universe, "expected_total", None)
    ratio = getattr(universe, "coverage_ratio", None)
    ok = bool(getattr(universe, "coverage_ok", False))

    ratio_txt = "分母不可得" if ratio is None else f"{ratio*100:.2f}%"
    head = (
        f"[bold]母池扫描:[/bold] {scanned} 只 / 预期 A股 "
        f"{'不可得' if expected is None else expected} 只 → 覆盖率 [bold yellow]{ratio_txt}[/bold yellow] "
        f"({'[green]闸门通过[/green]' if ok else '[red]闸门未通过[/red]'})"
    )

    lines = [head]
    excluded = dict(getattr(universe, "excluded", {}) or {})
    if excluded:
        lines.append(
            "[bold]L0 剔除:[/bold] "
            + " | ".join(f"{k}: {v}" for k, v in sorted(excluded.items(), key=lambda kv: -kv[1]))
        )
    lines.append(f"[bold]活跃母池:[/bold] {len(getattr(universe, 'rows', []) or [])} 只")

    if funnel is not None:
        try:
            for line in funnel.render_lines():
                lines.append(line)
        except Exception:  # noqa: BLE001  渲染失败不得拖垮主流程
            pass

    warnings = list(getattr(universe, "warnings", []) or [])
    for w in warnings:
        lines.append(f"[yellow]⚠️ {w}[/yellow]")

    console.print(
        Panel(
            "\n".join(lines),
            title="🧭 [bold cyan]沪深全市场母池对账与漏斗归因[/bold cyan]",
            border_style="cyan",
        )
    )


#: 拐点档位 → 中文短标签（UNVERIFIED 必须显眼，不能被当成"业绩零增长"）
_TREND_LABEL = {
    "turning_positive": "由负转正",
    "accelerating": "加速",
    "stable": "平稳",
    "decelerating": "减速",
    "UNVERIFIED": "未核验",
    "DISABLED": "未启用",
}


def print_tracks_panel(tracks: dict[str, list[dict[str, Any]]] | None) -> None:
    """渲染轨道 B / C / D 的分轨结果面板（轨道 A 由主表呈现）。

    ★ 没有这个面板，"多轨分流"就只是一句口号 —— 用户看不到中军和价值票到底
      有没有被选出来，也无法验证「美的集团必须且只能进轨道 C」这类穿透走查。
    """
    if not tracks:
        return

    from screener.tracks import TRACK_A, TRACK_B, TRACK_C, TRACK_D, TRACK_NAMES

    icons = {TRACK_B: "♻️", TRACK_C: "🏛️", TRACK_D: "🛡️"}

    for tk in (TRACK_B, TRACK_C, TRACK_D):
        picks = tracks.get(tk) or []
        if not picks:
            continue

        table = Table(
            title=f"{icons.get(tk, '')} 轨道 {tk}：{TRACK_NAMES.get(tk, tk)}（{len(picks)} 只）",
            box=box.ROUNDED,
            header_style="bold magenta",
            expand=True,
        )
        table.add_column("代码", style="cyan", overflow="fold")
        table.add_column("名称", style="bold white", overflow="fold")
        table.add_column("涨幅", justify="right", overflow="fold")
        table.add_column("关键判据", style="green", overflow="fold")
        table.add_column("决断", justify="center", overflow="fold")
        table.add_column("仓位", justify="right", overflow="fold")

        for p in picks[:15]:
            pct = float(p.get("pct_chg") or p.get("change_pct") or 0.0)
            pct_color = "red" if pct > 0 else ("green" if pct < 0 else "white")

            if tk == TRACK_B:
                crit = (
                    f"近{int(p.get('recent_limit_up_days') or 0)}日涨停"
                    f"{'(今日炸板)' if p.get('is_broken_today') else ''} "
                    f"量比{float(p.get('volume_ratio') or 0):.2f}"
                )
            elif tk == TRACK_C:
                inst = p.get("institutional_holding") or "UNVERIFIED"
                crit = (
                    f"市值分位{float(p.get('market_cap_pctile') or 0)*100:.0f}% "
                    f"20日均额{float(p.get('avg_amount_20d') or 0)/1e8:.1f}亿 "
                    f"机构{inst}"
                )
            else:
                pe = p.get("pe")
                pb = p.get("pb")
                crit = (
                    f"PE{pe:.1f} " if isinstance(pe, float) else "PE- "
                ) + (f"PB{pb:.1f} " if isinstance(pb, float) else "PB- ") + \
                     (f"ROE{float(p.get('roe_pct') or 0):.1f}%") + \
                     (f" 拐点[{_TREND_LABEL.get(p.get('roe_trend'), p.get('roe_trend') or '-')}]")

            pbk = p.get("playbook")
            gear = getattr(pbk, "action_label", "") or p.get("action_desc", "")
            pos = f"{getattr(pbk, 'max_position_pct', 0)}%" if pbk is not None else "0%"

            table.add_row(
                p.get("code") or p.get("full_code", ""),
                p.get("name", ""),
                f"[{pct_color}]{pct:+.2f}%[/{pct_color}]",
                crit,
                gear,
                pos,
            )

        console.print(table)

    # 轨道 A 一行汇总，避免与主表重复
    a_picks = tracks.get(TRACK_A) or []
    if a_picks:
        console.print(f"[dim]轨道 A（超短连板与题材接力）{len(a_picks)} 只见上方主表[/dim]")


def print_screener_table(result_obj: Any, mode: str = "close") -> None:
    """在终端渲染母池对账、涨停天梯情绪概览与精选漏斗候选池。"""
    candidates = []
    overview = None
    universe = None
    funnel = None
    tracks = None
    macro_gate = None

    if isinstance(result_obj, dict):
        candidates = result_obj.get("picks", [])
        overview = result_obj.get("overview")
        universe = result_obj.get("universe")
        funnel = result_obj.get("funnel")
        tracks = result_obj.get("tracks")
        macro_gate = result_obj.get("macro_gate")
    elif isinstance(result_obj, list):
        candidates = result_obj

    # 0. 打印母池对账（证明"全市场"不是口号）
    print_universe_panel(universe, funnel)

    if isinstance(result_obj, dict) and result_obj.get("blocked"):
        console.print(
            Panel(
                f"[bold red]{result_obj.get('block_reason') or '筛选已被闸门阻断'}[/bold red]\n\n"
                "按 Fail-Closed 原则：母池完整性无法自证时**拒绝输出精选池** —— "
                "一份残缺的\"全市场\"结果比没有结果更危险。",
                title="⛔ [bold red]筛选已阻断[/bold red]",
                border_style="red",
            )
        )
        return

    # 1. 打印全市场涨停天梯与宏观大盘情绪全景
    if overview:
        macro_res = getattr(overview, "macro_regime_result", None)
        ladder_desc = " | ".join(f"{k}板: {v}家" for k, v in sorted(overview.ladder_counts.items(), reverse=True))
        promo_desc = " | ".join(f"{k}板晋级率: {v*100:.1f}%" for k, v in sorted(overview.promotion_rates.items(), reverse=True))
        themes_desc = "；".join(f"{t.name}({t.count}家, 龙一:{t.leader_name} {t.leader_board}板)" for t in overview.strongest_themes[:3])
        space_tickers = "、".join(overview.space_board_tickers) if overview.space_board_tickers else "无"

        if macro_res is not None:
            idx_m = macro_res.index_metrics
            brd_m = macro_res.breadth_metrics
            vol_m = macro_res.volume_metrics
            spc_m = macro_res.speculative_metrics
            tot_amt_trillion = vol_m.total_amount / 1e12

            ladder_lines = [
                f"[bold]交易日期:[/bold] {overview.trade_date}  |  [bold]大盘宏观状态:[/bold] [bold red]{macro_res.macro_regime_label}[/bold red] (综合评分: [bold yellow]{macro_res.composite_score:.0f}/100[/bold yellow])",
                f"[bold]大盘基准趋势:[/bold] {idx_m.name}({idx_m.code}) 收盘 {idx_m.close:.2f} ({idx_m.pct_chg:+.2f}%)，均线【{idx_m.ma_alignment}】，连跌 {idx_m.consecutive_down_days} 日，5日动量 {idx_m.ret_5d:+.2f}%",
                f"[bold]全市场广度量能:[/bold] 【{brd_m.breadth_regime}】 上涨 {brd_m.up_count}家 / 下跌 {brd_m.down_count}家 (涨跌比 {brd_m.breadth_ratio*100:.1f}%) | 总成交 {tot_amt_trillion:.2f}万亿 ({vol_m.volume_regime})",
                f"[bold]短线连板投机:[/bold] 【{spc_m.speculative_regime}】 空间板 [bold yellow]{spc_m.space_board_level}板[/bold yellow] [{space_tickers}] | 涨停 {spc_m.limit_up_count}家 / 跌停 {spc_m.limit_down_count}家 (炸板率 {spc_m.broken_rate_pct:.1f}%)",
                f"[bold]连板天梯分布:[/bold] {ladder_desc}",
                f"[bold]最强核心主线题材:[/bold] {themes_desc}",
            ]
            if macro_res.risk_warnings:
                for w in macro_res.risk_warnings:
                    ladder_lines.append(f"[bold red]⚠️ 核心宏观警示:[/bold red] {w}")
        else:
            ladder_lines = [
                f"[bold]交易日期:[/bold] {overview.trade_date}  |  [bold]市场情绪水温:[/bold] [bold red]{overview.sentiment_phase}[/bold red]  |  [bold]涨停:[/bold] [bold red]{overview.total_limit_up_count}[/bold red]家 / [bold]跌停:[/bold] [bold green]{overview.total_limit_down_count}[/bold green]家 / [bold]炸板:[/bold] [bold yellow]{overview.total_broken_count}[/bold yellow]家 (炸板率 {overview.broken_rate_pct:.1f}%)",
                f"[bold]连板天梯分布:[/bold] {ladder_desc}",
                f"[bold]核心梯队晋级率:[/bold] {promo_desc if promo_desc else '首板为主'}",
                f"[bold]空间高度龙头:[/bold] [bold yellow]{overview.space_board_level} 板[/bold yellow] -> {space_tickers}",
                f"[bold]最强核心主线题材:[/bold] {themes_desc}",
            ]
        ladder_panel = Panel(
            "\n".join(ladder_lines),
            title="📈 [bold cyan]全市场短线连板梯队与市场情绪总览[/bold cyan]",
            border_style="cyan",
        )
        console.print(ladder_panel)

    # ★ 20261029 审计 P0-1：市场级闸门结论必须显式呈现 —— 否则用户看到的是
    #   一屏标的，却不知道大盘层面已经禁止开仓（单股链路早就写了"严禁开仓"，
    #   全市场链路却只把 overview 原样带回，两条链路口径不一致）。
    if macro_gate:
        g_status = str(macro_gate.get("status") or "")
        g_note = str(macro_gate.get("market_note") or "")
        g_style = "red" if g_status == "CLOSED" else ("yellow" if g_status == "UNVERIFIED" else "green")
        g_lines = [
            f"[bold]闸门状态:[/bold] [{g_style}]{g_status}[/{g_style}]",
            g_note,
        ]
        if macro_gate.get("single_name_cap_pct") is not None:
            g_lines.append(f"[bold]单票仓位上限:[/bold] {float(macro_gate['single_name_cap_pct']):.0f}%")
        if g_status in ("CLOSED", "UNVERIFIED"):
            g_lines.append(
                f"[bold red]已将 {int(macro_gate.get('buyable_rewritten') or 0)} 只标的的"
                f"『可买』动作改写为等待闸门放行[/bold red]"
            )
        console.print(Panel(
            "\n".join(g_lines),
            title="🚦 [bold cyan]宏观情绪闸门 (市场级)[/bold cyan]",
            border_style=g_style,
        ))

    # 2. 打印精选候选股漏斗表格
    table = Table(
        title=f"🏆 [bold yellow]AST-Trader A股短线实战精选池 ({mode.upper()} 模式)[/bold yellow]",
        show_header=True,
        header_style="bold magenta",
    )
    # ★ 不再写死列宽：原 10 列固定宽合计 112 + 边框 > 实际终端宽度（实测 83 列），
    #   导致每一列都被 Rich 截成 "…"。改为让 Rich 按可用宽度自适应并**折行**，
    #   保证窄终端下信息仍可读（宁可换行，不可丢字）。
    # 表头尽量短：窄终端下 Rich 按表头最小宽度切分，长表头会挤掉内容宽度。
    # ★ 全部列用 ``overflow="fold"``：宁可**折行**也不丢字（默认 ellipsis 会把
    #   "襄阳轴承" 截成 "襄阳…"，在 83 列终端上每列都会变成这样）。
    table.add_column("代码", style="cyan", overflow="fold")
    table.add_column("名称", style="bold white", overflow="fold")
    table.add_column("涨幅", justify="right", overflow="fold")
    table.add_column("梯队", style="yellow", overflow="fold")
    table.add_column("题材", style="green", overflow="fold")
    table.add_column("主力净额", justify="right", overflow="fold")
    table.add_column("决断", justify="center", overflow="fold")
    table.add_column("仓位", justify="right", overflow="fold")
    table.add_column("战术", style="dim", overflow="fold")

    for item in candidates:
        # ★ 修渲染 bug：``screen`` 流程输出的 pick **根本没有 "card" 键**，
        #   旧实现 ``card = item.get("card", {})`` 恒取到 {}，导致：
        #     · 梯队身位恒显示「首板/潜伏」（真实的连板身位被吞掉）
        #     · 决断档位恒显示默认值「观察」
        #     · 建议仓位恒显示 0%
        #   把真实判定整体掩盖成了默认值，用户据此得出「全是首板、全部 0 仓位」
        #   的结论（实际上 10-28 那次有 2 只是连板、走的是 wait_reseal 分支）。
        #   现一律从 pick 自身取数，并保留明确的降级兜底。
        # 沪深口径下 sh/sz 前缀无信息量，且会多占 2 列导致 6 位代码被截断
        ticker = item.get("code") or item.get("full_code", "")
        name = item.get("name", "")
        pct = float(item.get("pct_chg") or 0.0)
        pct_color = "red" if pct > 0 else ("green" if pct < 0 else "white")

        b_lvl = int(item.get("board_level") or 0)
        is_lead = bool(item.get("is_leader"))
        lead_str = " [bold red](龙一)[/bold red]" if is_lead else ""
        if b_lvl > 1:
            tier_desc = f"{b_lvl}连板{lead_str}"
        elif b_lvl == 1:
            tier_desc = f"首板{lead_str}"
        else:
            tier_desc = "非涨停强势"

        theme = item.get("theme_info") or {}
        t_name = theme.get("name") or theme.get("theme_name") or (item.get("limit_reason") or "—")

        # 主力资金流呈现 (支持降级标识)
        if item.get("money_flow_degraded", False) or item.get("main_net_wan") is None:
            flow_str = "[yellow]未核验(降级)[/yellow]"
        else:
            net_w = float(item.get("main_net_wan", 0.0) or 0.0)
            main_ratio = float(item.get("main_ratio", 0.0) or 0.0)
            f_color = "red" if net_w > 0 else ("green" if net_w < 0 else "white")
            flow_str = f"[{f_color}]{net_w:+.0f}万 ({main_ratio:+.1f}%)[/{f_color}]"

        pb = item.get("playbook")
        if pb is not None:
            gear = getattr(pb, "action_label", "") or item.get("action_desc", "观察")
            pos_str = f"{getattr(pb, 'max_position_pct', 0)}%"
            mf_summary = item.get("action_desc") or getattr(pb, "entry_tactic", "")
        else:
            gear = item.get("action_desc", "观察")
            pos_str = "0%"
            mf_summary = "—"
        gear_color = "red" if "回避" in gear else (
            "green" if ("做多" in gear or "核心" in gear or "买入" in gear or "竞价" in gear) else "yellow"
        )
        gear_fmt = f"[{gear_color} bold]【{gear}】[/{gear_color} bold]"

        table.add_row(
            ticker,
            name,
            f"[{pct_color}]{pct:+.2f}%[/{pct_color}]",
            tier_desc,
            t_name,
            flow_str,
            gear_fmt,
            pos_str,
            mf_summary,
        )

    console.print(table)

    # 3. 打印轨道 B / C / D 分轨结果
    print_tracks_panel(tracks)


def print_tracker_summary(tracker_stats: dict[str, Any]) -> None:
    """在终端渲染自研选股跟踪器回测/实盘绩效面板。

    ★ 20261029 审计 P0-4：旧实现读的是 ``tracker_stats["summary"]`` 里的
      ``total_tracked / t1_win_rate_pct / t1_sum_return_pct`` ……而
      ``evaluate_tracker_performance`` 从来没产出过这些键，面板恒显示 0
      —— 追踪器等于"算了但没人看得见"。现改为直接读真实返回键，并把
      口径变化（开盘买入 / 扣费 / 一字板不计入分母）显式写在面板上。
    """
    summary = tracker_stats.get("summary") or tracker_stats
    t = Table(title="📊 [bold green]AST-Trader 实盘候选池追踪与胜率统计[/bold green]")
    t.add_column("统计维度", style="cyan")
    t.add_column("指标数值", style="bold yellow")

    t.add_row("已跟踪总标的数", str(summary.get("total_samples", 0)))
    t.add_row("已测算样本 (T+1 可成交)", str(summary.get("evaluated_samples", 0)))
    t.add_row("不可成交 (一字板·已剔出分母)", str(summary.get("unfillable", 0)))
    t.add_row("待 T+1 行情", str(summary.get("waiting", 0)))
    t.add_row("次日胜率 (T+1 win rate)", f"{float(summary.get('win_rate_pct') or 0.0):.1f}%")
    t.add_row("次日平均净收益 (扣费后)", f"{float(summary.get('avg_return_pct') or 0.0):+.2f}%")
    t.add_row("次日平均毛收益 (未扣费)", f"{float(summary.get('avg_return_gross_pct') or 0.0):+.2f}%")
    t.add_row(
        "平均最大冲高 / 最大回撤",
        f"{float(summary.get('avg_runup_pct') or 0.0):+.2f}% / "
        f"{float(summary.get('avg_drawdown_pct') or 0.0):+.2f}%",
    )
    plr = summary.get("profit_loss_ratio")
    t.add_row("盈亏比 (均赢/均亏)", f"{plr:.2f}" if plr else "—")

    console.print(t)
    console.print(
        "[dim]★ 口径：T+1 开盘价买入、当日收盘价卖出，扣除双边佣金 / 印花税 / 过户费；"
        "一字板（开盘即封死无法成交）不计入胜率分母。[/dim]"
    )

    # ★ 分轨胜率：四轨各自成账（旧实现只记轨道 A，B/C/D 无法复盘）
    by_track = summary.get("by_track") or {}
    if by_track:
        tt = Table(title="🧭 [bold cyan]分轨道 T+1 胜率[/bold cyan]")
        tt.add_column("轨道", style="cyan")
        tt.add_column("样本", justify="right")
        tt.add_column("胜率", justify="right")
        tt.add_column("平均净收益", justify="right")
        for tr, s in by_track.items():
            tt.add_row(
                str(tr),
                str(s.get("samples", 0)),
                f"{float(s.get('win_rate_pct') or 0.0):.1f}%",
                f"{float(s.get('avg_return_pct') or 0.0):+.2f}%",
            )
        console.print(tt)
