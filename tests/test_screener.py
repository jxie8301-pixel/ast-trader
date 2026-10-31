"""Unit tests for AST-Trader screener tier components."""
from __future__ import annotations

import time
from unittest.mock import MagicMock

import pytest

from screener.filter_audit import filter_audit
from screener.filter_liquidity import filter_liquidity
from screener.funnel_audit import STAGE_LIQUIDITY, FunnelAudit
from screener.rank_composite import rank_composite


def _make_candidates(n: int) -> list[dict]:
    """构造 n 只「治理干净」的候选标的（质押已核验且安全、无违规记录）。"""
    return [
        {
            "code": f"{600000 + i}",
            "name": f"标的{i}",
            "limit_reason": "热门题材",
        }
        for i in range(n)
    ]


def _safe_collector(delay_map: dict[str, float] | None = None) -> MagicMock:
    """返回一个恒定返回安全治理数据的 collector；delay_map 可制造完成序错乱。"""
    collector = MagicMock()

    def fake_gov(code: str) -> dict:
        if delay_map and code in delay_map:
            time.sleep(delay_map[code])
        return {"pledge_ratio": 0.10, "concepts": ["题材"], "violation_count": 0,
                "recent_violation_count": 0}

    collector.get_f10_governance_and_concept.side_effect = fake_gov
    return collector


def test_filter_audits_all_candidates_not_truncated_to_15():
    """P1-1: Tier 2 必须对 Tier 1 全部合格候选排雷，严禁隐性截断前 15 只。

    旧实现无条件 ``candidates[:15]``，第 16 名起被物理丢弃、永不进入 Tier 3。
    """
    candidates = _make_candidates(40)
    passed = filter_audit(candidates, _safe_collector())

    assert len(passed) == 40
    # 第 16~40 名（旧实现被丢弃的区间）必须全部在通过列表里
    passed_codes = [p["code"] for p in passed]
    for i in range(15, 40):
        assert f"{600000 + i}" in passed_codes


def test_filter_audit_output_order_matches_input_order():
    """P1-1: 并发只用于提速，输出顺序必须严格等于输入顺序。

    ``as_completed`` 是线程完成序；这里刻意让**前面的候选睡得更久**，
    若仍按完成序收集，输出顺序必然与输入相反。
    """
    candidates = _make_candidates(8)
    # 越靠前的候选睡得越久 → 完成序与输入序严格相反
    delay_map = {c["code"]: 0.05 * (8 - i) for i, c in enumerate(candidates)}

    passed = filter_audit(candidates, _safe_collector(delay_map), max_workers=8)
    passed_codes = [p["code"] for p in passed]

    assert passed_codes == [c["code"] for c in candidates]


def test_filter_audit_preserves_order_when_some_are_vetoed():
    """剔除部分标的后，幸存者的相对顺序仍必须保持输入序。"""
    candidates = _make_candidates(6)
    collector = MagicMock()

    def fake_gov(code: str) -> dict:
        # 第 2、4 只（索引 1、3）高质押一票否决
        if code in ("600001", "600003"):
            return {"pledge_ratio": 0.85, "concepts": [], "violation_count": 0,
                    "recent_violation_count": 0}
        return {"pledge_ratio": 0.10, "concepts": [], "violation_count": 0,
                "recent_violation_count": 0}

    collector.get_f10_governance_and_concept.side_effect = fake_gov

    passed = filter_audit(candidates, collector, max_workers=6)
    passed_codes = [p["code"] for p in passed]

    assert passed_codes == ["600000", "600002", "600004", "600005"]


def test_filter_audit_still_supports_explicit_limit():
    """显式传 top_audit_count 时仍按旧语义限流（兼容调用方），但默认不截断。"""
    candidates = _make_candidates(20)

    limited = filter_audit(candidates, _safe_collector(), top_audit_count=5)
    assert len(limited) == 5

    full = filter_audit(candidates, _safe_collector())
    assert len(full) == 20


def test_filter_liquidity_excludes_st_and_low_amount():
    """测试 Tier 1 过滤剔除 ST 与非涨停低流动性标的。"""
    ladder_rows = [
        {"code": "000001", "full_code": "sz000001", "name": "平安银行", "board_level": 1, "seal_amount": 1e8},
        {"code": "000002", "full_code": "sz000002", "name": "*ST万科", "board_level": 1, "seal_amount": 5e8},
        {"code": "000003", "full_code": "sz000003", "name": "PT退市股", "board_level": 1, "seal_amount": 5e8},
    ]
    quotes_map = {
        "sz000001": {"close": 12.5, "pct_chg": 9.95, "amount": 6e8},
        "sz000002": {"close": 5.2, "pct_chg": 5.0, "amount": 6e8},
        "sz000003": {"close": 1.1, "pct_chg": -10.0, "amount": 1e7},
    }

    passed = filter_liquidity(ladder_rows, quotes_map)
    assert len(passed) == 1
    assert passed[0]["code"] == "000001"


# ---------------------------------------------------------------- 换手率死代码修复
def _liq_row(code: str, full_code: str, board: str | None = None, board_level: int = 1):
    return {"code": code, "full_code": full_code, "name": f"N{code}",
            "board_level": board_level, "seal_amount": 0.0, "board": board}


def test_turnover_rule_is_no_longer_dead_code():
    """★ 换手率门槛（8%~25%）必须真正生效 —— 它曾经是一条死代码。

    根因：``QuoteSnapshot`` 没有 ``turnover_ratio``，而 pipeline 只装了四个键，
    于是 ``turnover`` 恒为 0.0，``if turnover > 0.0`` 恒 False，规则从未拦下过
    任何一只票。现在换手率由 ``stock_profile_table`` 提供真实值。
    """
    rows = [
        _liq_row("600001", "sh600001"),   # 换手 2%  → 低于下限，剔除
        _liq_row("600002", "sh600002"),   # 换手 12% → 通过
        _liq_row("600003", "sh600003"),   # 换手 30% → 高于上限，剔除
    ]
    quotes_map = {
        "sh600001": {"close": 10.0, "pct_chg": 10.0, "amount": 6e8, "turnover_ratio": 2.0},
        "sh600002": {"close": 10.0, "pct_chg": 10.0, "amount": 6e8, "turnover_ratio": 12.0},
        "sh600003": {"close": 10.0, "pct_chg": 10.0, "amount": 6e8, "turnover_ratio": 30.0},
    }
    passed = filter_liquidity(rows, quotes_map)
    assert [p["code"] for p in passed] == ["600002"]


def test_turnover_unverified_does_not_false_kill():
    """换手率不可核验时**不适用**该门槛（缺失≠0，也≠不合格），走 NFR-02。"""
    rows = [_liq_row("600001", "sh600001")]
    quotes_map = {"sh600001": {"close": 10.0, "pct_chg": 10.0, "amount": 6e8, "turnover_ratio": None}}
    assert len(filter_liquidity(rows, quotes_map)) == 1


def test_689_cdr_uses_growth_board_thresholds():
    """★ 科创板 CDR（689）必须按双创档（3 亿 / 20cm），不能当主板处理。

    改造前 ``is_gem_star`` 只认 300/301/688，689 会被误判为主板。
    """
    rows = [_liq_row("689009", "sh689009", board="sse_star_market")]
    # 成交额 4 亿：主板门槛 5 亿会剔除，双创门槛 3 亿会通过
    quotes_map = {"sh689009": {"close": 50.0, "pct_chg": 19.8, "amount": 4e8, "turnover_ratio": 12.0}}
    passed = filter_liquidity(rows, quotes_map)
    assert len(passed) == 1
    assert passed[0]["board_kind"] == "growth"


def test_302_new_segment_uses_growth_thresholds():
    """★ 深市 302 新代码段（20261028 全量实测存在）按双创档处理。"""
    rows = [_liq_row("302132", "sz302132", board="szse_chinext")]
    quotes_map = {"sz302132": {"close": 20.0, "pct_chg": 19.9, "amount": 4e8, "turnover_ratio": 12.0}}
    passed = filter_liquidity(rows, quotes_map)
    assert len(passed) == 1 and passed[0]["board_kind"] == "growth"


def test_bse_is_explicitly_excluded_with_reason_code():
    """北交所必须产出显式剔除码，而不是靠成交额门槛隐式排掉。"""
    rows = [_liq_row("920002", "bj920002")]
    quotes_map = {"bj920002": {"close": 10.0, "pct_chg": 29.0, "amount": 6e8, "turnover_ratio": 12.0}}
    audit = FunnelAudit()
    assert filter_liquidity(rows, quotes_map, audit=audit) == []
    assert audit.stage(STAGE_LIQUIDITY).dropped.get("BSE_OUT_OF_SCOPE") == 1


def test_liquidity_drops_are_attributed_to_funnel():
    audit = FunnelAudit()
    rows = [_liq_row("600001", "sh600001"), _liq_row("600002", "sh600002")]
    quotes_map = {
        "sh600001": {"close": 10.0, "pct_chg": 10.0, "amount": 1e7, "turnover_ratio": 12.0},
        "sh600002": {"close": 10.0, "pct_chg": 10.0, "amount": 6e8, "turnover_ratio": 12.0},
    }
    filter_liquidity(rows, quotes_map, audit=audit)
    assert audit.stage(STAGE_LIQUIDITY).dropped.get("AMOUNT_BELOW_BOARD") == 1


# ---------------------------------------------------------------- 首板死锁
def _rank_collector(pct: float = 10.0) -> MagicMock:
    c = MagicMock()
    c.get_realtime_quote.return_value = {
        "close": 10.0, "pct_chg": pct, "amount": 6e8,
        "turnover_ratio": 12.0, "total_mv": 5e9,
    }
    c.get_money_flow.return_value = {"main_net_wan": 1200.0, "main_ratio": 6.0}
    return c


def test_first_board_limit_up_gets_auction_action_not_zero_position():
    """★ 解开「非涨停不选、涨停了又不让买」的死锁。

    旧实现：``if pct_val >= 7.0 and not leader: wait_pullback`` —— 把**所有首板
    涨停**（占涨停池约 88.7%）一律判成追高、仓位清零。而 Tier 0 又规定非涨停
    不得入池，于是精选池恒为 0% 看戏（20261028 实测 5 只全部 0%）。

    现在首板封板走 ``wait_auction``：当日不建仓，给出次日 9:25 可验证的竞价条件。
    """
    cands = [{"code": "600519", "name": "首板票", "pct_chg": 10.0, "amount": 6e8,
              "seal_amt": 0.0, "board_level": 1, "board_kind": "main", "limit_reason": "题材"}]
    ranked = rank_composite(cands, _rank_collector())

    assert ranked[0]["action"] == "wait_auction"
    assert ranked[0]["playbook"].action == "AUCTION"
    # ★ 关键：不再是"一口都不能吃"的 0 仓位，而是给了明确的试错仓与废单条件
    assert ranked[0]["playbook"].base_position_pct == 0       # 当日绝不建仓
    assert ranked[0]["playbook"].max_position_pct > 0         # 次日条件满足可建试错仓
    assert "9:25" in ranked[0]["playbook"].entry_tactic
    assert "废单" in ranked[0]["playbook"].invalidation_rule


def test_non_sealed_big_gain_still_waits_pullback():
    """未封板却大涨（双创 +10.3% 未到 20cm 涨停）仍属日内追高，保持 wait_pullback。"""
    cands = [{"code": "300308", "name": "未封板", "pct_chg": 10.3, "amount": 6e8,
              "seal_amt": 0.0, "board_level": 1, "board_kind": "growth", "limit_reason": "题材"}]
    ranked = rank_composite(cands, _rank_collector(pct=10.3))

    assert ranked[0]["action"] == "wait_pullback"
    assert ranked[0]["playbook"].action == "WAIT"


def test_momentum_proxy_no_longer_fabricates_volume_ratio():
    """★ 量比不得再被硬编码成 1.5；不可核验时标记弃权。"""
    cands = [{"code": "600519", "name": "首板票", "pct_chg": 10.0, "amount": 6e8,
              "seal_amt": 0.0, "board_level": 1, "board_kind": "main", "limit_reason": "题材"}]
    ranked = rank_composite(cands, _rank_collector())
    # 采集层未提供量比 → 应显式标记未核验，而不是塞一个定值充当真实量比
    assert ranked[0].get("volume_ratio_unverified") is True


# ---------------------------------------------------------------- 归因矩阵
def test_funnel_conservation_holds():
    f = FunnelAudit()
    f.register_expected_rules(STAGE_LIQUIDITY, ("A", "B"))
    f.record_input(STAGE_LIQUIDITY, 10)
    f.record_drop(STAGE_LIQUIDITY, "A", 4)
    f.record_output(STAGE_LIQUIDITY, 6)
    assert f.all_conserved
    assert f.violations() == []


def test_funnel_detects_unattributed_loss():
    """有标的被无声丢弃（守恒被打破）必须能被检出。"""
    f = FunnelAudit()
    f.record_input(STAGE_LIQUIDITY, 10)
    f.record_drop(STAGE_LIQUIDITY, "A", 1)
    f.record_output(STAGE_LIQUIDITY, 6)
    assert not f.all_conserved
    assert f.violations() and "差额 +3" in f.violations()[0]


def test_funnel_dead_rule_detection():
    """★ 死规则检测 —— 换手率门槛曾因取错字段恒为 0，正是靠这条才能暴露。"""
    f = FunnelAudit()
    f.register_expected_rules(STAGE_LIQUIDITY, ("AMOUNT_BELOW_BOARD", "TURNOVER_OUT_OF_RANGE"))
    f.record_input(STAGE_LIQUIDITY, 10)
    f.record_drop(STAGE_LIQUIDITY, "AMOUNT_BELOW_BOARD", 4)
    f.record_output(STAGE_LIQUIDITY, 6)
    assert f.dead_rules() == ["T1_liquidity/TURNOVER_OUT_OF_RANGE"]


def test_funnel_dead_rule_whitelist_supports_stage_qualified_form():
    f = FunnelAudit()
    f.register_expected_rules(STAGE_LIQUIDITY, ("TURNOVER_OUT_OF_RANGE", "ST_RISK_WARNING"))
    f.record_input(STAGE_LIQUIDITY, 5)
    f.record_output(STAGE_LIQUIDITY, 5)
    dead = f.dead_rules(whitelist=frozenset({"T1_liquidity/ST_RISK_WARNING"}))
    assert dead == ["T1_liquidity/TURNOVER_OUT_OF_RANGE"]


def test_funnel_render_lines_include_stage_and_dead_rules():
    f = FunnelAudit()
    f.register_expected_rules(STAGE_LIQUIDITY, ("A",))
    f.record_input(STAGE_LIQUIDITY, 3)
    f.record_drop(STAGE_LIQUIDITY, "A", 1)
    f.record_output(STAGE_LIQUIDITY, 2)
    lines = f.render_lines()
    assert any("T1_liquidity" in ln for ln in lines)
    assert any("A:1" in ln for ln in lines)
