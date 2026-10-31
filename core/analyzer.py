"""Single stock quantitative & forensic analysis orchestrator.
封装完整的个股穿透流水线，使 CLI、批量回测器与外部 API 能够 100% 一键复用。
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

import config
from core.audit_engine import AuditEngine
from core.game_features import GameFeatureExtractor
from core.industry import INDUSTRY_FINANCIAL
from core.judgment_chain import JudgmentChainRunner
from core.microstructure import MicrostructureAnalyzer
from core.seat_matcher import SeatMatcher
from core.trap_detector import TrapDetector
from core.types import SingleStockContext
from core.youzi_personas import evaluate_youzi_personas, extract_tape_features
from data.eltdx_client import normalize_code
from data import eltdx_financial_map as fmap
from data.eltdx_collector import EltdxCollector
from data.supplement_api import fetch_lhb_seats
from presentation.html_renderer import render_decision_card_html
from screener.ladder_analyzer import LadderAnalyzer

logger = logging.getLogger("ast_trader.core.analyzer")


class SingleStockAnalyzer:
    """个股深度穿透分析统一服务引擎。"""

    def __init__(self, collector: EltdxCollector | None = None) -> None:
        self.collector = collector or EltdxCollector()
        self.audit_engine = AuditEngine()
        self.game_extractor = GameFeatureExtractor()
        self.micro_analyzer = MicrostructureAnalyzer()
        self.seat_matcher = SeatMatcher()
        self.trap_detector = TrapDetector()
        self.ladder_analyzer = LadderAnalyzer(collector=self.collector)
        self.chain_runner = JudgmentChainRunner()

    def _build_ai_enrichment(
        self,
        ts_code: str,
        stock_name: str,
        gov_info: dict[str, Any],
    ) -> dict[str, Any]:
        """构建 governance / theme_purity 模块的 AI 增强。"""
        if not config.AI_ENABLED:
            return {}

        try:
            from core.ai_coprocessor import enrich_many
            from core.ai_coprocessor.context import build_context

            ctx = build_context(
                ts_code,
                stock_name,
                concepts=gov_info.get("concepts") or [],
                mainbz_list=gov_info.get("main_business") or [],
            )
            result = enrich_many(ctx, ("governance", "theme_purity"))
            return {k: v for k, v in result.items() if v is not None}
        except Exception as exc:
            logger.warning("AI 语义分析异常: %s", exc)
            return {}

    def _merge_theme_nominations(self, flags: list[Any], ai_map: dict[str, Any]) -> None:
        """题材纯度提名并入红旗池。"""
        if not ai_map or ai_map.get("theme_purity") is None:
            return
        try:
            from core.ai_coprocessor.guard import nominations_to_flags

            flags.extend(nominations_to_flags({"theme_purity": ai_map.get("theme_purity")}))
        except Exception as exc:
            logger.warning("AI 题材纯度提名并入失败: %s", exc)

    def analyze(
        self,
        ticker_input: str,
        html_output: str | None = None,
        enable_ai: bool = False,
        ai_model: str | None = None,
    ) -> dict[str, Any] | None:
        """执行单股全链路分析并返回决断卡；代码非法或行情不可得时返回 None。"""
        if enable_ai:
            config.AI_ENABLED = True
        if ai_model:
            config.AI_MODEL = ai_model

        try:
            eltdx_code, ts_code = normalize_code(ticker_input)
        except ValueError as e:
            logger.error("代码格式错误: %s", e)
            return None

        # 1. 行情与动能
        # ★ 20261029 审计 §3.3：技术形态类指标（MA / 支撑压力 / 波动率 / ret_10d）
        #   必须用**前复权**序列 —— 不复权在除权除息日会产生虚假跳空，把金叉、支撑位、
        #   20 日波动率全算成假信号。执行价位（止损线 / 生命线 / 挂单）另以实时真实价
        #   与真实 pre_close 为准（见 pillar5 的 P1-7 修复），不用复权序列。
        daily_df = self.collector.get_daily(ts_code, count=60, adjust="qfq")
        quote = self.collector.get_realtime_quote(ts_code)
        if daily_df.empty or not quote:
            logger.warning("无法获取 %s 的行情数据", ts_code)
            return None

        momentum = self.game_extractor.extract_momentum(daily_df)
        num_code = ts_code.split(".")[0]
        stock_name = quote.get("name") or f"标的_{num_code}"

        # 2. 治理与财务扫雷
        gov_info = self.collector.get_f10_governance_and_concept(ts_code)
        f_data = self.collector.get_financial_reports(ts_code)

        # ★ 20261029 审计 P1-10：`eltdx_financial_map.looks_like_financial_row` /
        #   `check_identities` 此前沿**从未被生产调用过**（写了不用）。这里把它接上：
        #   简称/概念都判不出行业时，用资产负债表结构反查 —— 若应收、存货、流动资产、
        #   非流动资产、流动负债全为 0，则该主体没有工商业营运资本结构，只能是金融类
        #   （银行/券商/保险的报表结构如此）。据此让制造业校准的审计模型主动弃权。
        if not gov_info.get("industry"):
            for _raw in (f_data.get("balance_raw") or []):
                if fmap.looks_like_financial_row(_raw):
                    gov_info["industry"] = INDUSTRY_FINANCIAL
                    logger.info(
                        "%s 简称/概念未标明行业，但资产负债表无工商业营运资本结构 → 判为%s业",
                        ts_code, INDUSTRY_FINANCIAL,
                    )
                    break

        # 细分行业成分股动态估值中位数现场自算
        ind_val = self.collector.get_industry_peers_valuation(
            ts_code,
            concepts=gov_info.get("concepts", []),
            main_business=gov_info.get("main_business", []),
            company_name=stock_name,
        )

        # AI 判断层
        ai_map = self._build_ai_enrichment(ts_code, stock_name, gov_info)

        flags = self.audit_engine.run_audit(
            balance_df=f_data["balance"],
            cashflow_df=f_data["cashflow"],
            income_df=f_data["income"],
            governance_info=gov_info,
            quote_info=quote,
            ai=ai_map,
        )

        # 3. 大盘连板天梯与市场情绪周期
        sentiment_overview, stock_theme_map, _, _ = self.ladder_analyzer.analyze()
        ladder_info = stock_theme_map.get(num_code)

        # 4. 真实资金流与高频微观结构
        money_flow = self.collector.get_money_flow(ts_code)
        if isinstance(sentiment_overview, dict):
            market_ice = bool(sentiment_overview.get("is_market_ice", False)) or sentiment_overview.get("sentiment_phase") in ("冰点期", "退潮期", "退潮", "冰点")
        elif sentiment_overview is not None:
            phase = getattr(sentiment_overview, "sentiment_phase", "")
            market_ice = phase in ("冰点期", "退潮期", "退潮", "冰点") or bool(getattr(sentiment_overview, "is_market_ice", False))
        else:
            market_ice = False

        microstructure = self.collector.get_microstructure(
            ts_code,
            current_price=quote.get("close", 0.0),
            daily_df=daily_df,
            momentum=momentum,
            ladder_info=ladder_info,
            float_share=quote.get("float_share", 0.0),
            quote=quote,
            analyzer=self.micro_analyzer,
            flags=flags,
            market_ice=market_ice,
        )

        # 5. 龙虎榜席位匹配
        lhb_records = fetch_lhb_seats(num_code, days=30, health=self.collector.health)
        matched_youzi = self.seat_matcher.match_seats(lhb_records)

        # 6. 杀猪盘雷达检测
        trap_score, trap_warnings = self.trap_detector.evaluate(ts_code, gov_info.get("concepts", []))

        # 7. 游资战法特征提取与真实匹配
        # ★ 20261029 审计 P1-8：原实现在天梯缺失时给 ``leader_rank=1``（自封龙头）/
        #   ``breadth_pct=75.0``（自封热度），无概念时给 999 / 0.0 —— 全是凭空造数。
        #   现一律用真实观测值，取不到即 None（弃权），由画像匹配环节按"不可核验"处理。
        theme_ctx = {
            "concepts": gov_info.get("concepts", []),
            "leader_rank": (ladder_info or {}).get("leader_rank"),
            "breadth_pct": (ladder_info or {}).get("breadth_pct"),
            "has_theme": bool(gov_info.get("concepts")) or bool(ladder_info),
        }
        tape_features = extract_tape_features(
            quote=quote,
            momentum=momentum,
            market_cap=quote.get("total_mv", 0.0),
            theme_info=theme_ctx,
            governance_risk=any(f.level == "🔴" for f in flags),
            hard_event=len(gov_info.get("concepts", [])) > 0,
        )
        matched_personas = evaluate_youzi_personas(tape_features)
        self._merge_theme_nominations(flags, ai_map)

        # ★ 20261029 审计 P2：``trade_date`` 原为 ``datetime.now()`` —— 周末/节假日
        #   跑出的报告会被标成一个**非交易日**，而信号时效提示
        #   （``_build_signal_staleness_note``）按自然日计算，非交易日跑会凭空多算
        #   1~2 天、把当天的数据误判成"过期"。改用**真实最后一根日 K 的交易日**
        #   （零新增依赖）；取不到才回退自然日并记日志。
        trade_date = datetime.now().strftime("%Y%m%d")
        if daily_df is not None and not daily_df.empty and "trade_date" in daily_df.columns:
            _last_td = str(daily_df.iloc[0].get("trade_date") or "").strip()
            if len(_last_td) == 8:
                trade_date = _last_td
            else:
                logger.warning("日线未给出有效交易日，trade_date 回退为自然日 %s", trade_date)

        # 7.5. 链路 2：Pass 1 核心矛盾提审与针对性定向证据检索 (两阶段审问式验票)
        contradiction_inquiries = []
        evidence_pkg = None
        if config.TWO_PASS_AUDIT_ENABLED:
            try:
                from core.ai_coprocessor.inquiry import formulate_inquiries
                from core.evidence_retriever import TargetedEvidenceRetriever

                quant_summary = {
                    "pe": quote.get("pe"),
                    "pb": quote.get("pb"),
                    "smart_q": microstructure.get("smart_q") if isinstance(microstructure, dict) else None,
                    "apm_pattern": microstructure.get("apm_pattern") if isinstance(microstructure, dict) else None,
                }
                contradiction_inquiries = formulate_inquiries(ts_code, stock_name, quant_summary, flags)
                retriever = TargetedEvidenceRetriever()
                evidence_pkg = retriever.retrieve(ts_code, stock_name, contradiction_inquiries)
            except Exception as e_twopass:
                logger.warning("两阶段定向审问与补证执行异常: %s", e_twopass)

        # 8. 决断链执行
        card = self.chain_runner.run(
            ticker=ts_code,
            name=stock_name,
            trade_date=trade_date,
            quote=quote,
            momentum=momentum,
            flags=flags,
            matched_youzi=matched_youzi,
            trap_warnings=trap_warnings,
            matched_personas=matched_personas,
            concepts=gov_info.get("concepts", []),
            ladder_info=ladder_info,
            sentiment_overview=sentiment_overview,
            money_flow=money_flow,
            lhb_records=lhb_records,
            governance_info=gov_info,
            microstructure=microstructure,
            daily_df=daily_df,
            financial_reports=f_data,
            data_health=self.collector.health.summary(),
            industry_valuation=ind_val,
            contradiction_inquiries=contradiction_inquiries,
            evidence_package=evidence_pkg,
        )

        # 9. 注入细分行业估值中位数元数据
        if card:
            card["industry_valuation"] = ind_val

        # 10. 若指定 html_output，则生成离线研报
        if html_output is not None and card is not None:
            saved_path = render_decision_card_html(card, output_path=html_output if html_output != "default" else None)
            card["saved_html_path"] = saved_path

        return card
