"""Rich terminal rendering for AST-Trader, strictly aligned with Ashare & UZI contracts."""
from __future__ import annotations

from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

console = Console()


def print_decision_card(card: dict[str, Any]) -> None:
    """在终端渲染单股决断卡 (严格基于A股双轨逻辑与五维实盘支柱，杜绝重复与矛盾)."""
    gear = card.get("decision_gear", "观察")
    gear_color = "red" if gear == "回避" else ("green" if gear == "买入" else "yellow")
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

    # 标的基本面与行情抬头
    header_info = (
        f"[bold white]{name}[/bold white] ([cyan]{ticker}[/cyan])  |  "
        f"现价: [bold]{price:.2f}[/bold]元 ([{pct_color}]{pct:+.2f}%[/{pct_color}])  |  "
        f"换手: [bold]{turnover:.2f}%[/bold]  |  "
        f"PE(TTM): [bold]{pe:.1f}x[/bold]"
    )
    mf_stage = card.get("main_force_stage", "【⏳ 存量震荡/等待方向期】")
    sub_header = (
        f"板块规制: [bold cyan]{board_name}[/bold cyan]  |  "
        f"物种定位: [bold yellow]{track_name}[/bold yellow] (流通: {circ_mv:.1f}亿 / 总值: {total_mv:.1f}亿)\n"
        f"主力阶段: [bold magenta]{mf_stage}[/bold magenta]  |  "
        f"决断档位: {gear_style}"
    )

    body_lines = [
        header_info,
        sub_header,
        "[dim]─" * 70 + "[/dim]",
        f"[bold cyan]❶ 宏观闸门 / 情绪周期:[/bold cyan]\n  {card.get('pillar_gate', '未接入')}",
        f"[bold cyan]❷ 业务纯度 / 题材身位:[/bold cyan]\n  {card.get('pillar_business', '未接入')}",
        f"[bold cyan]❸ 筹码阻力 / 封板生态:[/bold cyan]\n  {card.get('pillar_tape', '未接入')}",
        f"[bold cyan]❹ 资金动向 / 监管余量:[/bold cyan]\n  {card.get('pillar_flow', '未接入')}",
        f"[bold cyan]❺ 本土排雷 (二元风控):[/bold cyan]\n  {card.get('pillar_audit', '未接入')}",
        "[dim]─" * 70 + "[/dim]",
        f"[bold yellow]🎯 实战决断:[/bold yellow] [bold]{card.get('decision_title', '')}[/bold] (建议仓位: [bold yellow]{card.get('position_cap', 0.0)*100:.0f}%[/bold yellow])",
        f"[bold yellow]📌 核心矛盾:[/bold yellow] {card.get('core_contradiction', '')}",
        f"[bold yellow]⚡ 实盘战术:[/bold yellow] {card.get('action_tactic', '')}",
        f"[bold red]🛑 实战防线 (T+1纪律):[/bold red] {card.get('invalidation_line', '')}",
    ]

    panel = Panel(
        "\n\n".join([body_lines[0], body_lines[1]]) + "\n" + "\n\n".join(body_lines[2:]),
        title=f"🎯 [bold yellow]AST-Trader A股买方投研决断卡[/bold yellow]",
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

    # 1. 打印全市场涨停天梯与情绪周期面板
    if overview:
        ladder_desc = " | ".join(f"{k}板: {v}家" for k, v in sorted(overview.ladder_counts.items(), reverse=True))
        promo_desc = " | ".join(f"{k}板晋级率: {v*100:.1f}%" for k, v in sorted(overview.promotion_rates.items(), reverse=True))
        themes_desc = "；".join(f"{t.name}({t.count}家, 龙一:{t.leader_name} {t.leader_board}板)" for t in overview.strongest_themes[:3])
        space_tickers = "、".join(overview.space_board_tickers) if overview.space_board_tickers else "无"

        ladder_lines = [
            f"[bold]交易日期:[/bold] {overview.trade_date}  |  [bold]市场短线情绪水温:[/bold] [bold red]{overview.sentiment_phase}[/bold red]  |  [bold]全天涨停总数:[/bold] {overview.total_limit_up_count} 家",
            f"[bold]连板天梯分布:[/bold] {ladder_desc}",
            f"[bold]核心梯队晋级率:[/bold] {promo_desc if promo_desc else '首板为主'}",
            f"[bold]空间高度龙头:[/bold] [bold yellow]{overview.space_board_level} 板[/bold yellow] -> {space_tickers}",
            f"[bold]最强核心主线题材:[/bold] {themes_desc}",
        ]
        ladder_panel = Panel(
            "\n".join(ladder_lines),
            title="⚡ [bold yellow]全市场涨停连板天梯与短线情绪周期全景 (UZI Ladders)[/bold yellow]",
            border_style="yellow",
        )
        console.print(ladder_panel)

    # 2. 打印精选候选池及战术卡
    table = Table(title=f"🚀 AST-Trader 全市场短线漏斗筛选池 (模式: {mode})", show_lines=True)

    table.add_column("排名", justify="center", style="cyan", no_wrap=True)
    table.add_column("代码/名称", justify="center", style="bold")
    table.add_column("现价 (元)", justify="right")
    table.add_column("涨幅", justify="right")
    table.add_column("主力净流入 (万)", justify="right")
    table.add_column("行动状态 (UZI Action)", justify="center", style="bold")
    table.add_column("契合战法/席位", style="magenta")
    table.add_column("实操进场战术 (Playbook)", style="green")
    table.add_column("铁律死锁退出线", style="red")

    for i, c in enumerate(candidates, 1):
        pct = c.get("pct_chg", 0.0)
        pct_str = f"[red]{pct:+.2f}%[/red]" if pct > 0 else f"[green]{pct:+.2f}%[/green]"
        net_wan = c.get("main_net_wan", 0.0)
        net_str = f"[red]{net_wan:+.1f}[/red]" if net_wan > 0 else f"[green]{net_wan:+.1f}[/green]"

        action = c.get("action", "watch_only")
        if action == "buyable":
            act_str = "[bold green]主升买入[/bold green]"
        elif action == "wait_pullback":
            act_str = "[bold yellow]等待回踩[/bold yellow]"
        elif action == "wait_reseal":
            act_str = "[bold cyan]等待回封[/bold cyan]"
        else:
            act_str = "[dim]仅列入观察[/dim]"

        table.add_row(
            str(i),
            f"{c.get('name', '')}\n({c.get('code', '')})",
            f"{c.get('close', 0.0):.2f}",
            pct_str,
            net_str,
            act_str,
            c.get("supporters", "普通资金"),
            c.get("plan_high_open", "观察"),
            c.get("plan_stop_loss", "跌破 -3% 止损"),
        )

    console.print(table)


def print_tracker_summary(tracker_data: dict[str, Any]) -> None:
    """在终端渲染 Paper-Trading 选股追踪胜率与复盘大盘。"""
    table = Table(title="📈 AST-Trader 实盘选股收益追踪与胜率复盘账本 (Paper-Trading Tracker)", show_lines=True)
    table.add_column("指标名称", style="cyan", justify="left")
    table.add_column("统计数值", style="bold yellow", justify="right")

    table.add_row("历史累计跟踪选股样本", f"{tracker_data.get('total_samples', 0)} 只")
    table.add_row("已完成 T+1 检验样本数", f"{tracker_data.get('evaluated_samples', 0)} 只")
    table.add_row("T+1 实战胜率 (收盘上涨概率)", f"{tracker_data.get('win_rate_pct', 0.0):.1f}%")
    table.add_row("T+1 平均收盘收益率", f"{tracker_data.get('avg_return_pct', 0.0):+.2f}%")
    table.add_row("T+1 次日平均最大冲高幅度", f"{tracker_data.get('avg_runup_pct', 0.0):+.2f}%")
    table.add_row("T+1 次日平均最大下探回撤", f"{tracker_data.get('avg_drawdown_pct', 0.0):+.2f}%")

    console.print(table)

    details = tracker_data.get("details", [])
    if details:
        det_table = Table(title="🔍 近期选股样本 T+1 表现逐笔明细", show_lines=True)
        det_table.add_column("选入日期", justify="center")
        det_table.add_column("标的代码", justify="center", style="bold")
        det_table.add_column("标的名称", justify="center")
        det_table.add_column("选入价格", justify="right")
        det_table.add_column("T+1收盘收益", justify="right")
        det_table.add_column("T+1最大冲高", justify="right")
        det_table.add_column("T+1最大回撤", justify="right")
        det_table.add_column("检验状态", justify="center")

        for d in details[-10:]:
            t1_ret = d.get("t1_return_pct")
            ret_str = f"[red]{t1_ret:+.2f}%[/red]" if (t1_ret is not None and t1_ret > 0) else (f"[green]{t1_ret:+.2f}%[/green]" if t1_ret is not None else "待交易日")
            t1_run = d.get("t1_runup_pct")
            run_str = f"[red]{t1_run:+.2f}%[/red]" if t1_run is not None else "-"
            t1_dd = d.get("t1_drawdown_pct")
            dd_str = f"[green]{t1_dd:+.2f}%[/green]" if t1_dd is not None else "-"

            det_table.add_row(
                d.get("trade_date", ""),
                d.get("code", ""),
                d.get("name", ""),
                f"{d.get('close', 0.0):.2f}",
                ret_str,
                run_str,
                dd_str,
                d.get("status", ""),
            )
        console.print(det_table)
