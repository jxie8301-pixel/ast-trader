"""Unit tests verifying Phase 1 fixes: no fabricated defaults, fail-closed audit, real liquidity filtering, and lint hardening."""
import pytest
from unittest.mock import MagicMock

import config
from screener.filter_liquidity import filter_liquidity
from screener.filter_audit import filter_audit
from lint.validator import LintValidator
from core.judgment_chain import JudgmentChainRunner
from data.eltdx_client import log_fail
import data.eltdx_client as ec


def test_eltdx_client_log_fail_exists():
    """验证 ec.log_fail 真实存在，绝不发生 AttributeError。"""
    assert hasattr(ec, "log_fail")
    # 调用不抛错
    ec.log_fail("测试日志消息", ValueError("模拟网络异常"))
    ec.log_fail("无异常纯消息")


def test_filter_liquidity_real_enforcement():
    """验证 Tier 1 流动性与涨幅门控真实生效，不再是空转。"""
    ladder_rows = [
        {"code": "000001", "full_code": "sz000001", "name": "平安银行", "board_level": 1, "seal_amount": 0.0},
        {"code": "000002", "full_code": "sz000002", "name": "*ST万科", "board_level": 1, "seal_amount": 0.0}, # ST 剔除
        {"code": "000003", "full_code": "sz000003", "name": "低流动小票", "board_level": 1, "seal_amount": 0.0}, # 金额不足
        {"code": "000004", "full_code": "sz000004", "name": "弱势滞涨票", "board_level": 1, "seal_amount": 0.0}, # 涨幅不足
        {"code": "000005", "full_code": "sz000005", "name": "一字连板龙头", "board_level": 3, "seal_amount": 2.0e8}, # 一字板封单大放行
    ]
    quotes_map = {
        "sz000001": {"close": 15.0, "pct_chg": 5.5, "amount": 8.0e8}, # 合格 (主板>5亿，涨幅>4.5%)
        "sz000002": {"close": 8.0, "pct_chg": 5.0, "amount": 6.0e8},  # ST 剔除
        "sz000003": {"close": 10.0, "pct_chg": 6.0, "amount": 1.0e8}, # 成交额 1 亿 < 5 亿，剔除
        "sz000004": {"close": 12.0, "pct_chg": 2.1, "amount": 6.0e8}, # 涨幅 2.1% < 4.5%，剔除
        "sz000005": {"close": 20.0, "pct_chg": 10.0, "amount": 0.5e8}, # 一字板成交量小但封单 2 亿且 3 板，放行
    }

    passed = filter_liquidity(ladder_rows, quotes_map)
    passed_codes = [p["code"] for p in passed]

    assert "000001" in passed_codes
    assert "000002" not in passed_codes # ST 拦截
    assert "000003" not in passed_codes # 流动性拦截
    assert "000004" not in passed_codes # 涨幅拦截
    assert "000005" in passed_codes     # 一字板特批通过


def test_filter_audit_fail_closed():
    """验证 Tier 2 机械排雷在异常时严格 Fail-Closed (剔除)，绝不无条件放行。"""
    mock_collector = MagicMock()

    # 标的 1: 正常且质押率安全
    # 标的 2: 质押率 85% > 70% 致命
    # 标的 3: 取数接口崩溃抛错 (必须 Fail-Closed 剔除，绝不可 return item)
    def fake_gov(code):
        if code == "000001":
            return {"pledge_ratio": 0.20, "concepts": ["新能源"]}
        elif code == "000002":
            return {"pledge_ratio": 0.85, "concepts": ["消费"]}
        elif code == "000003":
            raise ConnectionResetError("TDX 连接断开")
        return {}

    mock_collector.get_f10_governance_and_concept.side_effect = fake_gov

    candidates = [
        {"code": "000001", "name": "安全标的", "limit_reason": "新能源"},
        {"code": "000002", "name": "高质押标的", "limit_reason": "消费"},
        {"code": "000003", "name": "网络报错标的", "limit_reason": "科技"},
    ]

    passed = filter_audit(candidates, mock_collector)
    passed_codes = [p["code"] for p in passed]

    assert "000001" in passed_codes
    assert "000002" not in passed_codes # 高质押剔除
    assert "000003" not in passed_codes # 报错严格 Fail-Closed 剔除!


def test_judgment_chain_no_fabricated_defaults():
    """验证基本面数据缺失时，决断链绝不编造 28.5% 毛利率和 1.5 亿净利润。"""
    runner = JudgmentChainRunner()
    quote = {
        "code": "000001",
        "close": 10.0,
        "pct_chg": 1.0,
        "total_mv": 50e8,
        "circ_mv": 50e8,
        "pe": 0.0, # 无有效 PE
        "turnover_ratio": 2.0,
    }
    momentum = {"ma5": 10.0, "ma20": 10.0}

    # 传入完全空的财务三表
    card = runner.run(
        ticker="000001",
        name="测试缺失标的",
        trade_date="20261028",
        quote=quote,
        momentum=momentum,
        flags=[],
        matched_youzi=[],
        trap_warnings=[],
        financial_reports={"income": None, "balance": None, "cashflow": None},
    )

    # 1. 验证质地五问 Q1: 绝不可拿到 "✓" (之前依靠 28.5% 编造假及格)
    sub_v = card["sub_verdicts_quality"]
    q1 = next(q for q in sub_v if "生意模式" in q["question"])
    assert q1["judgment"] == "⚠️"
    assert "缺失" in q1["evidence"] or "未披露" in q1["evidence"]

    # 2. 验证 Q2 现金含量: 缺失时不编造 1.05x
    q2 = next(q for q in sub_v if "赚钱质量" in q["question"])
    assert q2["judgment"] == "⚠️"
    assert "缺失" in q2["evidence"]

    # 3. 验证 Q3 护城河: 无主营构成时不编造 55% 占比
    q3 = next(q for q in sub_v if "护城河" in q["question"])
    assert q3["judgment"] == "⚠️"
    assert "缺失" in q3["evidence"] or "未披露" in q3["evidence"]


def test_judgment_chain_gear_playbook_alignment():
    """验证期权仓(小)档位与战术手册动作必须一致为买入 (消除 C2 自相矛盾)。"""
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
        concepts=["机器人", "智能机器"],
    )

    assert card["decision_gear"] == "期权仓(小)"
    assert card["position_cap"] > 0.0
    # 战术手册动作不能是观望 (WAIT)，必须是 BUY!
    pb = card.get("playbook")
    assert pb is not None
    assert pb.action_label != "观望"
    assert "买入" in pb.action_label or "进攻" in pb.action_label or "打板" in pb.action_label or "做多" in pb.action_label


def test_lint_validator_r8_full_text():
    """验证 Lint R8 规则扩展检查支柱全文，一旦包含越权买卖指令立即检出。"""
    validator = LintValidator()
    # 模拟在 pillar_1_quality 正文中越权出现 "建议买入"
    card = {
        "decision_gear": "观察",
        "position_cap": 0.0,
        "quality_verdict": "好",
        "pillar_1_quality": "主营盈利良好，建议买入建仓两成仓位", # 越权发声
        "invalidation_line": "跌破10元止损",
    }
    passed, findings = validator.validate(card, flags=[])
    assert not passed
    assert any("越权发声" in f and "建议买入" in f for f in findings)
