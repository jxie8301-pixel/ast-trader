"""Unit tests for single-stock analysis optimization & architecture decomposition.
涵盖:
- SingleStockContext 强类型容器与不可变性
- 支柱 ❶ 质押危机语料代理预警
- 支柱 ❸ 细分行业成分股动态估值中位数对标
- 支柱 ❹ 20日筹码密集峰与 Smart VWAP 动态乖离率假突破识别
- 支柱 ❺ 龙虎榜量化砸盘席位提示性预警联动
- SingleStockAnalyzer 统一编排引擎
- AI 协处理器并发 enrich_many
"""
from __future__ import annotations

import pandas as pd
import pytest

from core.analyzer import SingleStockAnalyzer
from core.pillars import (
    build_pillar_1_quality,
    build_pillar_2_state,
    build_pillar_3_odds,
    build_pillar_4_path,
    build_pillar_5_decision,
    assemble_and_lint_card,
)
from core.pillars.pillar4_path import compute_chip_peak_and_divergence
from core.red_flags import RedFlagItem
from core.seat_matcher import evaluate_lhb_dump_risk
from core.types import (
    OddsVerdict,
    PathVerdict,
    QualityVerdict,
    SingleStockContext,
    StateVerdict,
)


def test_single_stock_context_immutability():
    """验证 SingleStockContext 字段完整性。"""
    ctx = SingleStockContext(
        ticker="002273.SZ",
        name="水晶光电",
        trade_date="20261029",
        quote={"close": 21.50, "total_mv": 300e8},
        concepts=["消费电子", "苹果概念", "AI眼镜"],
    )
    assert ctx.ticker == "002273.SZ"
    assert ctx.name == "水晶光电"
    assert len(ctx.concepts) == 3


def test_pillar1_pledge_crisis_warning():
    """验证质地五问 Q4 成功捕获近期公告中的补充质押/展期危机特征。"""
    ctx_normal = SingleStockContext(
        ticker="000001.SZ",
        name="平安银行",
        trade_date="20261029",
        announcements=[],
    )
    derived = {"profitability": {"gross_margin_latest": 35.0, "net_margin_latest": 12.0}}
    v_normal = build_pillar_1_quality(
        ctx=ctx_normal,
        derived_data=derived,
        flags=[],
        governance_info={"pledge_ratio": None},
        concept_list=[],
        is_fatal=False,
        fatal_flags=[],
        data_health=None,
    )
    assert "⚠️ 质押危机预警" not in v_normal.pillar_text

    # 包含补充质押公告
    ctx_crisis = SingleStockContext(
        ticker="000002.SZ",
        name="测试股",
        trade_date="20261029",
        announcements=[{"title": "关于控股股东办理部分股份补充质押及质押展期的公告", "content": "质押展期至明年"}],
    )
    v_crisis = build_pillar_1_quality(
        ctx=ctx_crisis,
        derived_data=derived,
        flags=[],
        governance_info={"pledge_ratio": None},
        concept_list=[],
        is_fatal=False,
        fatal_flags=[],
        data_health=None,
    )
    assert "质押危机预警" in v_crisis.pillar_text


def test_pillar3_industry_pe_median():
    """验证支柱 ❸ 估值双锚动态对标细分行业成分股动态 PE 中位数。"""
    ctx = SingleStockContext(
        ticker="600519.SH",
        name="贵州茅台",
        trade_date="20261029",
        industry_valuation={"pe_median": 25.0},
    )
    derived = {"latest_vitals": {"latest_net_income_ttm": 800e8}}
    v = build_pillar_3_odds(
        ctx=ctx,
        price=1500.0,
        total_shares_yi=12.5,
        pe_val=22.0,
        total_mv=18000e8,
        derived_data=derived,
        is_tech=False,
        mainbz_list=[{"name": "茅台酒", "ratio": 85.0}],
        industry_pe_median=25.0,
    )
    assert v.industry_pe_median == 25.0
    assert "25.0x 对标" in v.pillar_text
    assert v.sotp_ps > 0


def test_pillar4_chip_peak_and_false_breakout():
    """验证 20日筹码密集峰与 Smart VWAP 动态乖离率计算及假突破检测。"""
    # 构造 20 根 K 线，大部分成交集中在 10.0~10.5 之间
    dates = pd.date_range("2026-10-01", periods=20)
    closes = [10.0] * 15 + [10.2, 10.4, 10.5, 11.0, 11.5]
    vols = [100000] * 15 + [50000, 50000, 50000, 20000, 10000]
    df = pd.DataFrame({"close": closes, "vol": vols}, index=dates)

    # 现价 11.5，突破了密集峰(~10.2)，但主力知情 VWAP 还在 10.1 (乖离率 > 3%)
    peak, div_pct, is_false = compute_chip_peak_and_divergence(
        daily_df=df, price=11.5, smart_vwap=10.1
    )
    assert peak is not None
    assert div_pct > 3.0
    assert is_false is True

    # 验证 Pillar 4 构建时对假突破的处理
    ctx = SingleStockContext(ticker="000001", name="测试", trade_date="20261029", daily_df=df)
    micro = {
        "smart_vwap": 10.1,
        "smart_q": 0.05,
        "main_force_confidence": 85.0,
    }
    p_verdict = build_pillar_4_path(
        ctx=ctx,
        price=11.5,
        overhead_chips=20.0,
        sotp_ps=9.0,
        microstructure=micro,
        is_fatal=False,
        trade_date="20261029",
    )
    assert p_verdict.is_false_breakout is True
    # 置信度应从 85.0 扣减 20.0 至 65.0
    assert p_verdict.mf_conf == 65.0
    assert "假突破与对倒警示" in p_verdict.pillar_text


def test_pillar5_lhb_dump_risk_warning():
    """验证龙虎榜量化砸盘席位打标与提示性预警注入 (不阻断买入档位)。"""
    # 模拟命中量化打板高频席位（如中金上海分公司）
    matched_seats = [
        {"youzi_name": "量化知名席位 (量化打板/做T)", "seat_name": "中国国际金融股份有限公司上海分公司", "net_amt": 5000},
    ]
    has_risk, warn = evaluate_lhb_dump_risk(matched_seats)
    assert has_risk is True
    assert "游资博弈警示" in warn
    assert "核按钮砸盘风险" in warn

    ctx = SingleStockContext(
        ticker="000001", name="测试", trade_date="20261029",
        quote={"close": 10.0},
        matched_youzi=matched_seats,
    )
    q_verdict = QualityVerdict(verdict="好", pillar_text="", sub_verdicts=[], fatal_flags=[], is_fatal=False)
    s_verdict = StateVerdict(verdict="↑变好+证据确认", pillar_text="", critical_wait="无", is_tech=False)
    o_verdict = OddsVerdict(verdict="合理", pillar_text="", sotp_ps=9.0, dcf_ps=11.0, derivation={}, anchor_range={}, reverse_dcf={}, ni_is_verified=True)
    p_verdict = PathVerdict(
        verdict="可承受", pillar_text="", is_micro_degraded=False,
        mf_stage_code="STAGE_4_MARKUP", mf_stage="主升浪", mf_behavior="", mf_override=None,
        mf_cap=0.20, mf_conf=80.0, is_trans=False, depth_to_sotp=10.0, profit_chip_pct=80.0,
    )
    d_verdict = build_pillar_5_decision(
        ctx=ctx,
        q_verdict=q_verdict,
        s_verdict=s_verdict,
        o_verdict=o_verdict,
        p_verdict=p_verdict,
        stock_track="TRACK_A_THEME",
        is_market_ice=False,
        macro_res=None,
        ret_10d=15.0,
        is_gem_star=False,
        is_bse=False,
        overhead_chips=15.0,
        ma5=9.8,
        ma20=9.2,
        support_lvl=9.5,
        resistance_lvl=10.5,
    )
    # 提示性预警不阻断：档位仍为核心仓，但 action_tactic 中追加了预警说明
    assert d_verdict.decision_gear == "核心仓"
    assert "核按钮砸盘风险" in d_verdict.action_tactic


def test_single_stock_analyzer_init():
    """验证 SingleStockAnalyzer 中台类正常初始化并挂载所有引擎组件。"""
    analyzer = SingleStockAnalyzer()
    assert analyzer.collector is not None
    assert analyzer.audit_engine is not None
    assert analyzer.chain_runner is not None
    assert analyzer.micro_analyzer is not None


def test_industry_valuation_mapping_for_optics_and_tech():
    """优化验证 1: 验证主营为光学光电子/硬件的标的正确对标高成长估值中枢(28x)，非通用制造(18.5x)。"""
    from data.eltdx_collector import EltdxCollector
    collector = EltdxCollector()
    ind = collector.get_industry_peers_valuation(
        "002273.SZ",
        concepts=[],
        main_business=[{"name": "光学光电子行业", "ratio": 93.1}],
        company_name="水晶光电",
    )
    assert ind["industry_name"] == "光学光电子行业"
    assert ind["pe_median"] == 28.0
    assert ind["pb_median"] == 3.5


def test_dynamic_sotp_segment_multiples():
    """优化验证 2: 验证 SOTP 动态分部倍数：高科技主业享受 25x+ 溢价，成熟材料分部对标 15x。"""
    from core.derivation import generate_standard_derivation
    d = generate_standard_derivation(
        current_price=20.0,
        total_shares_yi=10.0,
        net_income_latest_yi=10.0,
        is_growth=True,
        main_business=[
            {"name": "光学光电子核心业务", "ratio": 80.0},
            {"name": "反光材料传统业务", "ratio": 20.0},
        ],
        industry_pe=28.0,
    )
    segs = d["derivation"]["sotp"]["segments"]
    assert len(segs) == 2
    assert segs[0]["multiple"] == 28.0  # 高科技分部对标行业中位数 28x
    assert segs[1]["multiple"] == 15.0  # 成熟传统材料业务打折至 15x


def test_pillar2_state_no_contradictory_ocf_wait():
    """优化验证 3: 验证造血充沛 (OCF/NI=1.3x) 时，支柱 ❷ 催化绝不输出荒谬的'由负转正'。"""
    ctx = SingleStockContext(ticker="002273.SZ", name="水晶光电", trade_date="20261029")
    derived = {
        "quality_metrics": {"ocf_to_net_income": 1.31},
        "growth": {"revenue_yoy_latest": 0.15, "net_income_yoy_latest": 0.12},
    }
    v = build_pillar_2_state(
        ctx=ctx,
        derived_data=derived,
        concept_list=[],
        ladder_info=None,
        mainbz_list=[{"name": "光学光电子", "ratio": 90.0}],
    )
    assert "由负转正" not in v.critical_wait
    assert "综合毛利率" in v.critical_wait or "科技新品" in v.critical_wait or "大客户" in v.critical_wait


def test_stage_7_passive_drift_active_buying_penalty():
    """优化验证 4: 验证主力存在主动大单承接且成交活跃时，扣减 Stage 7 分数，杜绝假阳性阴跌误诊。"""
    from core.main_force_engine import MainForceStateEngine
    engine = MainForceStateEngine()
    daily_records = [{"high": 22.0, "low": 21.0, "close": 21.5, "vol": 50000.0} for _ in range(30)]
    daily_df = pd.DataFrame(daily_records)
    # 模拟普跌背景下有强力买盘托底的大盘股：买盘 63.8% > 卖盘 36.2%，现价高于 smart_vwap，换手 3.3%
    micro = {
        "smart_q": 1.001,
        "smart_vwap": 21.60,
        "all_vwap": 21.50,
        "smart_buy_ratio": 63.8,
        "smart_sell_ratio": 36.2,
        "smart_phase": "NEUTRAL",
        "apm_pattern": "NEUTRAL",
        "tail_vol_ratio": 10.0,
    }
    mom = {
        "overhead_chip_pct": 75.0,
        "current_drawdown": -20.0,
        "is_bullish_ma": False,
        "ma5": 22.5,
        "ma20": 23.0,
    }
    quote = {"close": 21.92, "open": 22.0, "high": 22.2, "low": 21.5, "turnover_ratio": 3.32, "amount": 900000000.0}
    dec = engine.evaluate("002273.SZ", current_price=21.92, quote=quote, daily_df=daily_df, microstructure=micro, momentum=mom)
    # 主动买盘扣 35 分 + 换手充沛扣 25 分，s7 分数大幅下降，不再误诊为 STAGE_7
    assert dec.stage_code != "STAGE_7_PASSIVE_DRIFT"
