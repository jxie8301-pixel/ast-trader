"""Rich terminal rendering for AST-Trader, strictly aligned with Ashare & UZI contracts."""
from __future__ import annotations

from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

console = Console()


def print_decision_card(card: dict[str, Any]) -> None:
    """在终端渲染单股决断卡 (完全对齐 Ashare CARD_ROWS 5 问与 UZI 游资战法)。"""
    gear = card.get("decision_gear", "观察")
    gear_color = "red" if gear == "回避" else "green" if gear == "买入" else "yellow"

    gear_style = f"[{gear_color} bold]{gear}[/{gear_color} bold]"
    ticker = card.get("ticker", "")
    name = card.get("name", "")
    price = card.get("price", 0.0)
    pct = card.get("pct_chg", 0.0)
    pct_color = "red" if pct > 0 else "green"

    header = (
        f"[bold white]{name}[/bold white] ([cyan]{ticker}[/cyan])  |  "
        f"现价: [bold]{price:.2f}[/bold] 元 ([{pct_color}]{pct:+.2f}%[/{pct_color}])  |  "
        f"行动档位: {gear_style}"
    )

    body_lines = [
        f"[bold cyan]① 质地 (是不是好公司):[/bold cyan] {card.get('quality_verdict')}",
        f"[bold cyan]② 状态 (在变好吗):[/bold cyan]     {card.get('state_verdict')}",
        f"[bold cyan]③ 赔率 (贵不贵):[/bold cyan]       {card.get('odds_verdict')}",
        f"[bold cyan]④ 路径 (扛得住吗):[/bold cyan]     {card.get('path_verdict')}",
        f"[bold cyan]⑤ 决策 (怎么办):[/bold cyan]       建议仓位: [bold yellow]{card.get('position_cap', 0.0)*100:.0f}%[/bold yellow] | "
        f"退出失效线: [bold red]{card.get('invalidation_line')}[/bold red]",
    ]

    # 展现 24 顶级游资战法契合清单
    personas = card.get("matched_personas", [])
    if personas:
        p_str = "、".join(f"[bold magenta]{p['youzi_name']}[/bold magenta]({p['style']} 契合度{p['fit_score']}分)" for p in personas[:3])
        body_lines.append(f"\n[bold yellow]⚡ 顶级游资战法共振:[/bold yellow] {p_str}")

    top3 = card.get("top3_risks", [])
    if top3:
        body_lines.append("\n[bold red]─── Top 3 核心致命排雷风险 ───[/bold red]")
        for i, r in enumerate(top3, 1):
            body_lines.append(f"  {r['level']} [{i}] {r['title']}: {r['evidence']}")

    panel = Panel(
        "\n".join(body_lines),
        title=f"🎯 [bold yellow]AST-Trader 短线作战决断卡[/bold yellow] - {header}",
        border_style=gear_color,
    )
    console.print(panel)


def print_screener_table(candidates: list[dict[str, Any]], mode: str = "close") -> None:
    """在终端渲染全市场漏斗筛选结果表格 (完全融合 UZI 战法与四态行动流转)。"""
    table = Table(title=f"🚀 AST-Trader 全市场短线漏斗筛选池 (模式: {mode})", show_lines=True)

    table.add_column("排名", justify="center", style="cyan", no_wrap=True)
    table.add_column("代码", justify="center", style="bold")
    table.add_column("现价 (元)", justify="right")
    table.add_column("涨幅", justify="right")
    table.add_column("主力净流入 (万)", justify="right")
    table.add_column("行动状态 (UZI Action)", justify="center", style="bold")
    table.add_column("契合游资战法", style="magenta")
    table.add_column("进场/低吸条件", style="green")
    table.add_column("铁律退出线", style="red")

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
            c.get("code", ""),
            f"{c.get('close', 0.0):.2f}",
            pct_str,
            net_str,
            act_str,
            c.get("supporters", "普通资金"),
            c.get("plan_high_open", "观察"),
            c.get("plan_stop_loss", "跌破 -3% 止损"),
        )

    console.print(table)
