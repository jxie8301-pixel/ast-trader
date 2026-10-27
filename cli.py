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

# 日志统一落盘配置
os.makedirs("logs", exist_ok=True)
logging.basicConfig(
    filename="logs/ast_trader.log",
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    encoding="utf-8",
)

from core.audit_engine import AuditEngine
from core.game_features import GameFeatureExtractor
from core.judgment_chain import JudgmentChainRunner
from core.seat_matcher import SeatMatcher
from core.trap_detector import TrapDetector
from core.youzi_personas import evaluate_youzi_personas, extract_tape_features
from data.eltdx_client import normalize_code
from data.eltdx_collector import EltdxCollector
from data.supplement_api import fetch_lhb_seats
from presentation.html_renderer import render_decision_card_html
from presentation.terminal_view import print_decision_card, print_screener_table, print_tracker_summary
from screener.pipeline import ScreenerPipeline
from screener.tracker import evaluate_tracker_performance


def run_analyze(ticker_input: str, html_output: str | None = None) -> None:
    """运行单股深度穿透分析。"""
    try:
        eltdx_code, ts_code = normalize_code(ticker_input)
    except ValueError as e:
        print(f"❌ 代码格式错误: {e}")
        sys.exit(1)

    print(f"\n🔍 正在获取 {ts_code} ({eltdx_code}) 的行情、财务与博弈数据...")
    collector = EltdxCollector()

    # 1. 行情与动能
    daily_df = collector.get_daily(ts_code, count=60)
    quote = collector.get_realtime_quote(ts_code)
    if daily_df.empty or not quote:
        print(f"❌ 无法获取 {ts_code} 的行情数据")
        sys.exit(1)

    extractor = GameFeatureExtractor()
    momentum = extractor.extract_momentum(daily_df)

    # 2. 治理与财务扫雷
    gov_info = collector.get_f10_governance_and_concept(ts_code)
    f_data = collector.get_financial_reports(ts_code)

    audit_engine = AuditEngine()
    flags = audit_engine.run_audit(
        balance_df=f_data["balance"],
        cashflow_df=f_data["cashflow"],
        income_df=f_data["income"],
        governance_info=gov_info,
        quote_info=quote,
    )

    # 3. 龙虎榜席位匹配
    num_code = ts_code.split(".")[0]
    lhb_records = fetch_lhb_seats(num_code)
    matcher = SeatMatcher()
    matched_youzi = matcher.match_seats(lhb_records)

    # 4. 杀猪盘雷达检测
    detector = TrapDetector()
    trap_score, trap_warnings = detector.evaluate(ts_code, gov_info.get("concepts", []))

    # 5. 24 顶级游资战法特征提取与严苛匹配 (全面对齐 UZI F_PERSONAS)
    tape_features = extract_tape_features(
        quote=quote,
        momentum=momentum,
        market_cap=quote.get("total_mv", 0.0),
        theme_info={"concepts": gov_info.get("concepts", [])},
        governance_risk=any(f.level == "🔴" for f in flags),
        hard_event=len(gov_info.get("concepts", [])) > 0,
    )
    matched_personas = evaluate_youzi_personas(tape_features)

    # 6. 五节点判断链装配 (集成六大流派陪审团与实操执行剧本)
    runner = JudgmentChainRunner()
    card = runner.run(
        ticker=ts_code,
        name=f"标的_{num_code}",
        trade_date=datetime.now().strftime("%Y%m%d"),
        quote=quote,
        momentum=momentum,
        flags=flags,
        matched_youzi=matched_youzi,
        trap_warnings=trap_warnings,
        matched_personas=matched_personas,
        concepts=gov_info.get("concepts", []),
    )

    # 7. 渲染终端决断卡
    print_decision_card(card)

    # 8. 若指定 --html，则生成离线研报
    if html_output is not None:
        saved_path = render_decision_card_html(card, output_path=html_output if html_output != "default" else None)
        print(f"\n📊 离线 HTML 研报已成功生成: {saved_path}")


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
        epilog="示例: python cli.py analyze 002273 或 python cli.py screen --mode close 或 python cli.py track",
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

    # screen
    screen_parser = subparsers.add_parser("screen", help="全市场短线三层漏斗筛选")
    screen_parser.add_argument("--mode", choices=["close", "noon"], default="close", help="筛选模式 (close 盘后 / noon 午盘)")
    screen_parser.add_argument("--top", type=int, default=10, help="输出候选上限 (默认 10)")

    # track
    subparsers.add_parser("track", help="实盘选股收益追踪与胜率复盘账本")

    args = parser.parse_args()

    if args.command == "analyze":
        run_analyze(args.ticker, html_output=args.html)
    elif args.command == "screen":
        run_screen(mode=args.mode, top_n=args.top)
    elif args.command == "track":
        run_track()


if __name__ == "__main__":
    main()
