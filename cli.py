"""AST-Trader: A-Share Short-Term Quantitative Decision System CLI Entry."""
from __future__ import annotations

import argparse
import sys
import os
import logging
from datetime import datetime

# Windows 终端 UTF-8 编码适配
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")

import config

# 日志统一落盘配置 (收敛到 config.LOG_FILE)
os.makedirs(config.LOG_FILE.parent, exist_ok=True)
logging.basicConfig(
    filename=str(config.LOG_FILE),
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    encoding="utf-8",
)

from core.analyzer import SingleStockAnalyzer
from core.audit_engine import AuditEngine
from core.game_features import GameFeatureExtractor
from core.judgment_chain import JudgmentChainRunner
from core.microstructure import MicrostructureAnalyzer
from core.seat_matcher import SeatMatcher
from core.trap_detector import TrapDetector
from core.youzi_personas import evaluate_youzi_personas, extract_tape_features
from data.eltdx_client import normalize_code
from data.eltdx_collector import EltdxCollector
from data.supplement_api import fetch_lhb_seats
from presentation.html_renderer import render_decision_card_html
from presentation.terminal_view import print_decision_card, print_screener_table, print_tracker_summary
from screener.ladder_analyzer import LadderAnalyzer
from screener.pipeline import ScreenerPipeline
from screener.tracker import evaluate_tracker_performance


logger = logging.getLogger("ast_trader.cli")


# ---------------------------------------------------------------- AI 判断层接线
def _build_ai_enrichment(
    ts_code: str,
    stock_name: str,
    gov_info: dict[str, Any],
) -> dict[str, Any]:
    """构建 `governance` / `theme_purity` 两模块的 AI 增强。**AI 关闭时返回 {}**。

    ★ 上下文口径与 `judgment_chain` 共用 `ai_coprocessor.context` ——
      否则 cli 与决断链会各自拉取不同批公告，同一只票两个 AI 结论互相打脸。
    ★ 这两个模块都**只走提名单向阀**加风险，不改写任何既有量化判定。
    """
    if not config.AI_ENABLED:
        return {}

    from core.ai_coprocessor import enrich_many
    from core.ai_coprocessor.context import build_context

    ctx = build_context(
        ts_code, stock_name,
        concepts=gov_info.get("concepts") or [],
        mainbz_list=gov_info.get("main_business") or [],
    )
    result = enrich_many(ctx, ("governance", "theme_purity"))
    return {k: v for k, v in result.items() if v is not None}


def _merge_theme_nominations(flags: list[Any], ai_map: dict[str, Any]) -> None:
    """题材纯度提名并入红旗池（单向阀：只能加风险）。

    `governance` 的提名已由 `AuditEngine.run_audit(ai=...)` 内部并入，
    这里只补 `theme_purity` —— 避免同一批提名被并入两次。
    """
    if not ai_map or ai_map.get("theme_purity") is None:
        return
    try:
        from core.ai_coprocessor.guard import nominations_to_flags

        flags.extend(nominations_to_flags({"theme_purity": ai_map.get("theme_purity")}))
    except Exception as exc:                                # noqa: BLE001
        logger.warning("AI 题材纯度提名并入失败（已忽略）: %s", exc)


def analyze_ticker(ticker_input: str, html_output: str | None = None) -> dict[str, Any] | None:
    """执行单股全链路分析并返回决断卡；代码非法或行情不可得时返回 ``None``。

    委托给 SingleStockAnalyzer 统一编排引擎，保证单股分析流水线与批量回测、测试完全同源。
    """
    try:
        eltdx_code, ts_code = normalize_code(ticker_input)
    except ValueError as e:
        print(f"❌ 代码格式错误: {e}")
        return None

    print(f"\n🔍 正在获取 {ts_code} ({eltdx_code}) 的行情、财务与博弈数据...")
    analyzer = SingleStockAnalyzer()
    card = analyzer.analyze(ticker_input=ticker_input, html_output=html_output)
    if card and card.get("saved_html_path"):
        print(f"\n📊 离线 HTML 研报已成功生成: {card['saved_html_path']}")
    elif card is None:
        print(f"❌ 无法获取 {ts_code} 的行情数据或代码错误")
    return card


def run_analyze(
    ticker_input: str,
    html_output: str | None = None,
    ai: bool = False,
    ai_model: str | None = None,
    verbose: bool = False,
) -> None:
    """运行单股深度穿透分析（CLI 入口）。"""
    # --ai 显式开关优先于配置默认值（配置默认关闭以保证测试确定性与无网可用）
    if ai:
        config.AI_ENABLED = True
    if ai_model:
        config.AI_MODEL = ai_model

    ok, status = config.ai_status()
    print(("🧠 " if ok else "⚪ ") + status)
    if ai and not ok:
        print("   ⚠️  AI 不可用，将按既有规则判定继续 —— 结果仍然有效，只是少了语义增强")

    card = analyze_ticker(ticker_input, html_output=html_output)
    if card is None:
        sys.exit(1)
    print_decision_card(card, verbose=verbose)


def run_screen(mode: str, top_n: int) -> None:
    """运行全市场短线漏斗筛选。"""
    pipeline = ScreenerPipeline()
    results = pipeline.run_screener(mode=mode, top_n=top_n)
    print_screener_table(results, mode=mode)


def run_track() -> None:
    """运行实盘选股追踪胜率复盘。"""
    collector = EltdxCollector()
    summary = evaluate_tracker_performance(collector)
    print_tracker_summary(summary)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="AST-Trader: A股短线量化投研系统 (买方审计 + 游资博弈)",
        epilog="示例: python cli.py analyze 002273  |  python cli.py analyze 002273 --ai  |  "
               "python cli.py screen --mode close  |  python cli.py track",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # analyze
    analyze_parser = subparsers.add_parser("analyze", help="单股深度穿透分析与作战卡生成")
    analyze_parser.add_argument("ticker", help="股票代码或中文名 (如 002273, 600519)")
    analyze_parser.add_argument(
        "--html",
        nargs="?",
        const="default",
        default=None,
        help="生成独立离线 HTML 研报 (可指定路径，默认保存在 ./reports/ 目录)",
    )
    analyze_parser.add_argument(
        "--ai",
        action="store_true",
        help="启用 AI 语义判断层（护城河/催化临界点/治理穿透/题材纯度/情景战术）。"
             "默认关闭；需先在 .env 配置 AST_AI_API_KEY。单股耗时约 60~120s",
    )
    analyze_parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="展开详细调试信息（含全量底层数据接口审计日志与AI中间推导）",
    )
    analyze_parser.add_argument(
        "--ai-model",
        default=None,
        help=f"覆盖 AI 模型（当前默认: {config.AI_MODEL}）",
    )

    # screen
    screen_parser = subparsers.add_parser("screen", help="全市场短线三层漏斗筛选")
    screen_parser.add_argument("--mode", choices=["close", "noon"], default="close", help="筛选模式 (close 盘后 / noon 午盘)")
    screen_parser.add_argument("--top", type=int, default=10, help="输出候选上限 (默认 10)")

    # track
    subparsers.add_parser("track", help="实盘选股收益追踪与胜率复盘账本")

    args = parser.parse_args()

    if args.command == "analyze":
        run_analyze(args.ticker, html_output=args.html, ai=args.ai, ai_model=args.ai_model, verbose=args.verbose)
    elif args.command == "screen":
        run_screen(mode=args.mode, top_n=args.top)
    elif args.command == "track":
        run_track()


if __name__ == "__main__":
    main()
