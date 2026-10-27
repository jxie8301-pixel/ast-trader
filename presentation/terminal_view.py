"""Rich terminal rendering for AST-Trader, strictly aligned with Ashare & UZI contracts."""
from __future__ import annotations

from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

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


def print_decision_card(card: dict[str, Any]) -> None:
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

    body_lines = [
        header_info,
        sub_header,
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

    body_lines.extend([
        f"[bold cyan]❶ 是不是好公司？(质地五问 · 铁门筛选):[/bold cyan]\n  {p1}",
        f"[bold cyan]❷ 在变好吗？(状态跃迁 λ · 稀疏事件与临界点):[/bold cyan]\n  {p2}",
        f"[bold cyan]❸ 贵不贵？(P=F+N 叙事溢价拆解 · 反向DCF · [SOTP, DCF]双锚):[/bold cyan]\n  {p3}",
        f"[bold cyan]❹ 主力行为生命周期与路径承载 (7阶段微观穿透与筹码承载):[/bold cyan]\n  {p4}",
        "[dim]─" * 78 + "[/dim]",
        f"[bold yellow]❺ 实战决断与执行战术:[/bold yellow] [bold]{card.get('decision_title', '')}[/bold] (建议仓位: [bold yellow]{card.get('position_cap', 0.0)*100:.0f}%[/bold yellow])",
        f"  • [bold]三元组状态:[/bold] {p5_dict.get('triad_verdict', '')}",
        f"  • [bold]三分买方判定:[/bold] {p5_dict.get('three_part_conclusion', '')}",
        f"  • [bold]监管监控状态:[/bold] {p5_dict.get('regulatory_status', '')}",
        f"[bold yellow]📌 核心矛盾:[/bold yellow] {card.get('core_contradiction', '')}",
        f"[bold yellow]⚡ 实盘战术 (双轨实操指引):[/bold yellow]\n  {card.get('action_tactic', '')}",
        f"[bold red]🛑 实战防线 (T+1纪律):[/bold red]\n  {card.get('invalidation_line', '')}",
    ])

    panel = Panel(
        "\n\n".join([body_lines[0], body_lines[1]]) + "\n" + "\n\n".join(body_lines[2:]),
        title=f"🎯 [bold yellow]AST-Trader A股买方投研决断卡 (深度版)[/bold yellow]",
        border_style=gear_color,
    )
    console.print(panel)


def print_screener_table(result_obj: Any, mode: str = "close") -> None:
    """在终端渲染全市场涨停天梯、情绪周期概览与精选漏斗候选池。"""
    candidates = []
    overview = None

    if isinstance(result_obj, dict):
        candidates = result_obj.get("picks", [])
        overview = result_obj.get("overview")
    elif isinstance(result_obj, list):
        candidates = result_obj

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

    # 2. 打印精选候选股漏斗表格
    table = Table(
        title=f"🏆 [bold yellow]AST-Trader A股短线实战精选池 ({mode.upper()} 模式)[/bold yellow]",
        show_header=True,
        header_style="bold magenta",
    )
    table.add_column("代码", style="cyan", width=10)
    table.add_column("名称", style="bold white", width=10)
    table.add_column("现价", justify="right", width=8)
    table.add_column("涨跌幅", justify="right", width=9)
    table.add_column("梯队身位", style="yellow", width=12)
    table.add_column("所属题材", style="green", width=14)
    table.add_column("决断档位", justify="center", width=10)
    table.add_column("建议仓位", justify="right", width=10)
    table.add_column("主力阶段与微观特征", style="dim", width=28)

    for item in candidates:
        card = item.get("card", {})
        ticker = card.get("ticker", item.get("ticker", ""))
        name = card.get("name", item.get("name", ""))
        price = card.get("price", 0.0)
        pct = card.get("pct_chg", 0.0)
        pct_color = "red" if pct > 0 else ("green" if pct < 0 else "white")

        ladder = card.get("ladder_info") or {}
        b_lvl = ladder.get("board_level", 0)
        t_name = ladder.get("theme_name", "主线")
        is_lead = ladder.get("is_leader", False)
        lead_str = f" [bold red](龙一)[/bold red]" if is_lead else ""
        tier_desc = f"{b_lvl}连板{lead_str}" if b_lvl > 0 else "首板/潜伏"

        gear = card.get("decision_gear", "观察")
        gear_color = "red" if "回避" in gear else ("green" if "做多" in gear or "核心" in gear or "买入" in gear else "yellow")
        gear_fmt = f"[{gear_color} bold]【{gear}】[/{gear_color} bold]"

        pos_str = f"{card.get('position_cap', 0.0)*100:.0f}%"
        mf_st = card.get("main_force_stage", "【⏳ 存量震荡】")
        micro = card.get("microstructure") or {}
        smart_q = micro.get("smart_q")
        q_str = f" Q={smart_q:.2f}" if smart_q is not None else ""
        mf_summary = f"{mf_st}{q_str}"

        table.add_row(
            ticker,
            name,
            f"{price:.2f}",
            f"[{pct_color}]{pct:+.2f}%[/{pct_color}]",
            tier_desc,
            t_name,
            gear_fmt,
            pos_str,
            mf_summary,
        )

    console.print(table)


def print_tracker_summary(tracker_stats: dict[str, Any]) -> None:
    """在终端渲染自研选股跟踪器回测/实盘绩效面板。"""
    summary = tracker_stats.get("summary", {})
    t = Table(title="📊 [bold green]AST-Trader 实盘候选池追踪与胜率统计[/bold green]")
    t.add_column("统计维度", style="cyan")
    t.add_column("指标数值", style="bold yellow")

    t.add_row("已跟踪总标的数", str(summary.get("total_tracked", 0)))
    t.add_row("买入档位标的数", str(summary.get("buy_count", 0)))
    t.add_row("次日溢价胜率 (T+1 win rate)", f"{summary.get('t1_win_rate_pct', 0.0):.1f}%")
    t.add_row("次日平均收益率 (T+1 avg return)", f"{summary.get('t1_avg_return_pct', 0.0):+.2f}%")
    t.add_row("累计阿尔法收益 (T+1 sum return)", f"{summary.get('t1_sum_return_pct', 0.0):+.2f}%")

    console.print(t)
