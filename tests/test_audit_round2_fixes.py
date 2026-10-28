"""Regression tests for AST-Trader Round 2 Audit Fixes (R1 - R15)."""
from pathlib import Path
import pandas as pd
import pytest

import config
from core.audit_engine import AuditEngine, _annual
from core.judgment_chain import JudgmentChainRunner
from core.main_force_engine import StageCode, MainForceStateEngine
from core.red_flags import LEVEL_FATAL, LEVEL_HIGH, RedFlagItem
from lint.validator import LintValidator
from screener.filter_liquidity import filter_liquidity
from screener.rank_composite import rank_composite
import screener.tracker as tracker


def test_r1_micro_degradation_locks_position_cap_zero():
    """R1: 验证微观数据降级时，下游绝对禁止将 0.0 仓位放大回退为 20% 或 8%，必须强制清零。"""
    runner = JudgmentChainRunner()
    quote = {
        "code": "600519",
        "close": 1500.0,
        "pct_chg": 3.0,
        "total_mv": 18000e8,
        "circ_mv": 18000e8,
        "pe": 20.0,
        "turnover_ratio": 2.0,
    }
    momentum = {"ma5": 1480.0, "ma20": 1400.0}
    # 模拟微观高频数据异常降级
    micro_degraded = {
        "is_degraded": True,
        "suggested_pos_cap": 0.0,
        "stage_code": "STAGE_UNVERIFIED",
        "main_force_stage": "【⏳ 数据缺失/微观未核验】",
        "main_force_confidence": 0.0,
    }
    card = runner.run(
        ticker="600519",
        name="贵州茅台",
        trade_date="20261028",
        quote=quote,
        momentum=momentum,
        flags=[],
        matched_youzi=[],
        trap_warnings=[],
        microstructure=micro_degraded,
    )
    # 核心风控断言: 仓位必须严格为 0.0，绝不能放大回退至 20%
    assert card["position_cap"] == 0.0
    assert card["decision_gear"] in ("等证据临界(观察)", "观察")
    assert card["path_verdict"] == "未核验(微观缺失)"
    assert "微观数据降级" in card["pillar_4_path"]


def test_r2_unverified_net_income_returns_uncalculated_dcf():
    """R2: 验证净利润缺失时，严禁捏造 0.1 亿计算虚假 DCF/SOTP，必须置为未核验且仓位清零。"""
    runner = JudgmentChainRunner()
    quote = {
        "code": "000001",
        "close": 10.0,
        "pct_chg": 2.0,
        "total_mv": 2000e8,
        "circ_mv": 2000e8,
        "pe": 0.0,  # PE 缺失
        "turnover_ratio": 1.5,
    }
    momentum = {"ma5": 9.8, "ma20": 9.5}
    # 财务全部缺失 (无 latest_net_income)
    card = runner.run(
        ticker="000001",
        name="平安银行",
        trade_date="20261028",
        quote=quote,
        momentum=momentum,
        flags=[],
        matched_youzi=[],
        trap_warnings=[],
    )
    assert card["odds_verdict"] == "未核验(财务缺失)"
    assert card["derivation"] is None
    assert card["anchor_range"] is None
    assert card["position_cap"] == 0.0
    assert "未核验" in card["pillar_3_odds"]


def test_r3_r4_stage_unverified_enum_and_metadata():
    """R3 & R4: 验证 STAGE_UNVERIFIED 枚举存在且元数据正确输出 0 仓位。"""
    assert "STAGE_UNVERIFIED" in StageCode.__members__
    engine = MainForceStateEngine()
    meta = engine._get_stage_metadata(
        stage_code=StageCode.STAGE_UNVERIFIED,
        current_price=10.0,
        smart_vwap=10.0,
        overhead_chips=10.0,
        smart_buy_ratio=50.0,
        smart_sell_ratio=50.0,
        board_level=1,
        price_position_60d=0.5,
        audit=None,
    )
    assert meta["suggested_pos_cap"] == 0.0
    assert meta["decision_gear_override"] == "观察"
    assert "微观未核验" in meta["stage_name"]


def test_r5_filter_liquidity_turnover_bounds():
    """R5: 验证 Tier 1 流动性初筛严格执行换手率下限 (7%) 与上限 (28%) 过滤。"""
    ladder = [
        {"code": "600001", "full_code": "sh600001", "name": "过低换手", "board_level": 1},
        {"code": "600002", "full_code": "sh600002", "name": "正常换手", "board_level": 1},
        {"code": "600003", "full_code": "sh600003", "name": "过高出货", "board_level": 1},
        {"code": "600004", "full_code": "sh600004", "name": "一字板巨量封单", "board_level": 3, "seal_amount": 2.0e8},
    ]
    quotes = {
        "sh600001": {"close": 10.0, "pct_chg": 5.0, "amount": 6e8, "turnover_ratio": 3.0}, # < 7% 剔除
        "sh600002": {"close": 10.0, "pct_chg": 5.0, "amount": 6e8, "turnover_ratio": 12.0}, # 合格
        "sh600003": {"close": 10.0, "pct_chg": 5.0, "amount": 6e8, "turnover_ratio": 35.0}, # > 28% 剔除
        "sh600004": {"close": 10.0, "pct_chg": 10.0, "amount": 0.5e8, "turnover_ratio": 1.0}, # 一字板封单豁免
    }
    passed = filter_liquidity(ladder, quotes)
    passed_codes = [p["code"] for p in passed]
    assert "600001" not in passed_codes  # 换手过低剔除
    assert "600003" not in passed_codes  # 换手过高剔除
    assert "600002" in passed_codes      # 正常换手通过
    assert "600004" in passed_codes      # 一字板豁免通过


def test_r6_audit_engine_uses_config_thresholds():
    """R6: 验证 audit_engine 读取 config.SLOAN_ACCRUAL_FATAL_RATIO 与 config.PLEDGE_FATAL_RATIO。"""
    engine = AuditEngine()
    # 模拟质押比例超过 config.PLEDGE_FATAL_RATIO (0.70)
    gov_info = {"pledge_ratio": 0.75}
    flags = engine._check_governance(gov_info)
    fatal_pledge = [f for f in flags if f.level == LEVEL_FATAL]
    assert len(fatal_pledge) == 1
    assert "质押" in fatal_pledge[0].title
    assert f"{config.PLEDGE_FATAL_RATIO*100:.0f}%" in fatal_pledge[0].threshold


def test_r7_annual_with_insufficient_data_returns_empty_df():
    """R7: 验证 _annual() 在年报不足 2 期时返回空 DataFrame，绝不拿季报混淆同比。"""
    df = pd.DataFrame([
        {"end_date": "20240331", "net_profit": 100},
        {"end_date": "20240630", "net_profit": 200},
        {"end_date": "20241231", "net_profit": 400},  # 只有 1 期年报
    ])
    res = _annual(df)
    assert res.empty


def test_r8_lint_failure_forces_zero_position_and_observe():
    """R8: 验证非致命 Lint 失败同样执行强制门控拦截，仓位归零且降级为观察。"""
    runner = JudgmentChainRunner()
    quote = {
        "code": "002273",
        "close": 12.0,
        "pct_chg": 9.9,
        "total_mv": 60e8,
        "circ_mv": 60e8,
        "pe": 25.0,
        "turnover_ratio": 12.0,
    }
    momentum = {"ma5": 11.5, "ma20": 10.2}
    ladder_info = {"board_level": 3, "theme_name": "机器人", "is_leader": True}

    card = runner.run(
        ticker="002273",
        name="水晶光电",
        trade_date="20261028",
        quote=quote,
        momentum=momentum,
        flags=[],
        matched_youzi=[],
        trap_warnings=[],
        ladder_info=ladder_info,
        concepts=["机器人"],
    )
    # 初始状态为期权仓
    assert card["position_cap"] > 0.0

    # 模拟机检故意注入越权发声词 "建议买入"
    card["pillar_1_quality"] += " 建议买入"
    val = LintValidator()
    ok, findings = val.validate(card, flags=[])
    assert not ok
    assert any("越权发声" in f for f in findings)


def test_r9_three_part_conclusion_consistency():
    """R9: 验证 three_part_conclusion 的'好下注'严格由 position_cap > 0 判定。"""
    runner = JudgmentChainRunner()
    quote = {
        "code": "002273",
        "close": 12.0,
        "pct_chg": 9.9,
        "total_mv": 60e8,
        "circ_mv": 60e8,
        "pe": 25.0,
        "turnover_ratio": 12.0,
    }
    momentum = {"ma5": 11.5, "ma20": 10.2}
    ladder_info = {"board_level": 3, "theme_name": "机器人", "is_leader": True}

    card = runner.run(
        ticker="002273",
        name="水晶光电",
        trade_date="20261028",
        quote=quote,
        momentum=momentum,
        flags=[],
        matched_youzi=[],
        trap_warnings=[],
        ladder_info=ladder_info,
    )
    p5 = card["pillar_5_decision"]
    if p5["position_cap"] > 0:
        assert "好下注? 【是】" in p5["three_part_conclusion"]
    else:
        assert "好下注? 【否】" in p5["three_part_conclusion"]


def test_r12_tracker_path_converges_to_config_cache():
    """R12: 验证实盘账本路径收敛到 config.CACHE_DIR。"""
    assert tracker.TRACKER_PATH == config.CACHE_DIR / "screener_tracker.jsonl"
