"""第一批「验收补齐」专属回归用例。

覆盖 E-1 双档仓位上限、E-2 左尾腰斩、E-3 预告变脸量化判据、
E-4 游资席位属性接线、C-7 换手率阈值对齐 SRS。

每项均含「正向命中」与「反向不误报」两类断言，任一子项失败可直接定位到具体条目。
"""

from __future__ import annotations

import pytest

import config
from core.audit_engine import AuditEngine
from core.execution_playbook import PlaybookBuilder, _dump_risk_personas
from core.judgment_chain import _left_tail_depth_pct, _resolve_position_cap
from core.red_flags import LEVEL_FATAL, LEVEL_HIGH


# =============================================================================
# E-1 双档仓位上限
# =============================================================================


def test_e1_normal_tier_never_exceeds_regular_cap():
    """常规档：无论主力建议多高，仓位不得超过 config.MAX_SINGLE_POSITION。"""
    cap = _resolve_position_cap(mf_cap=0.20, mf_confidence=80.0)
    assert cap == pytest.approx(config.MAX_SINGLE_POSITION)

    # 即使主力引擎误传超额建议，也须被常规档封顶
    assert _resolve_position_cap(mf_cap=0.99, mf_confidence=50.0) == pytest.approx(
        config.MAX_SINGLE_POSITION
    )


def test_e1_extreme_tier_requires_both_gates():
    """极端档：必须同时满足「主力满档建议」与「高置信度」两个门槛。"""
    cap = _resolve_position_cap(
        mf_cap=config.POSITION_EXTREME_MIN_STAGE_CAP,
        mf_confidence=config.POSITION_EXTREME_MIN_CONFIDENCE,
    )
    assert cap == pytest.approx(config.MAX_SINGLE_POSITION_EXTREME)
    assert config.MAX_SINGLE_POSITION_EXTREME > config.MAX_SINGLE_POSITION


@pytest.mark.parametrize(
    "mf_cap, mf_conf, expected_tier",
    [
        (0.20, 95.0, "extreme"),   # 满档 + 高置信度 → 极端档
        (0.15, 95.0, "normal"),    # 高置信度但主力未给满档 → 常规档
        (0.20, 80.0, "normal"),    # 满档但置信度不足 → 常规档
        (0.15, 80.0, "normal"),    # 两者均不足 → 常规档
    ],
)
def test_e1_tier_selection_matrix(mf_cap: float, mf_conf: float, expected_tier: str) -> None:
    """档位裁决矩阵：确认双档由置信度与主力建议**共同**决定，而非任一单独条件。"""
    cap = _resolve_position_cap(mf_cap=mf_cap, mf_confidence=mf_conf)
    if expected_tier == "extreme":
        assert cap == pytest.approx(config.MAX_SINGLE_POSITION_EXTREME)
    else:
        assert cap <= config.MAX_SINGLE_POSITION + 1e-9


def test_e1_small_track_half_of_regular():
    """期权仓(小) 轨道：上限为常规档的一半。"""
    cap = _resolve_position_cap(mf_cap=0.20, mf_confidence=95.0, small_track=True)
    assert cap == pytest.approx(config.MAX_SINGLE_POSITION / 2.0)
    # 小仓位轨道不得因高置信度跃升到极端档
    assert cap < config.MAX_SINGLE_POSITION_EXTREME


def test_e1_missing_mf_cap_falls_back_to_config():
    """主力未给建议时回退到 config 常量，不得出现裸数字默认值。"""
    assert _resolve_position_cap(mf_cap=None, mf_confidence=0.0) == pytest.approx(
        config.MAX_SINGLE_POSITION
    )
    assert _resolve_position_cap(mf_cap=None, mf_confidence=0.0, small_track=True) == pytest.approx(
        config.MAX_SINGLE_POSITION / 2.0 * 0.8
    )


# =============================================================================
# E-2 左尾腰斩
# =============================================================================


def test_e2_left_tail_halves_position():
    """左尾深度超过阈值时，仓位强制腰斩至常规档的一半。"""
    cap = _resolve_position_cap(
        mf_cap=0.20,
        mf_confidence=95.0,                       # 本可进入极端档 25%
        left_tail_depth_pct=40.0,                 # 但左尾 40% > 25%
    )
    assert cap == pytest.approx(config.MAX_SINGLE_POSITION / 2.0)
    assert cap < config.MAX_SINGLE_POSITION_EXTREME


def test_e2_left_tail_below_threshold_no_effect():
    """反向：左尾深度未超阈值时不得影响仓位裁决。"""
    with_tail = _resolve_position_cap(mf_cap=0.20, mf_confidence=95.0, left_tail_depth_pct=10.0)
    without_tail = _resolve_position_cap(mf_cap=0.20, mf_confidence=95.0)
    assert with_tail == pytest.approx(without_tail)


def test_e2_left_tail_threshold_boundary_is_strict():
    """边界：恰好等于阈值（25%）不触发，必须严格超过。"""
    at_threshold = _resolve_position_cap(
        mf_cap=0.20, mf_confidence=95.0, left_tail_depth_pct=config.LEFT_TAIL_WARN_THRESHOLD * 100
    )
    assert at_threshold == pytest.approx(config.MAX_SINGLE_POSITION_EXTREME)


@pytest.mark.parametrize(
    "depth_to_sotp, expected",
    [
        (-40.0, 40.0),   # 现价高于底座 40% → 左尾 40%
        (20.0, None),    # 现价已低于底座 → 无向下左尾空间，规则弃权
        (0.0, None),     # 恰好在底座 → 无左尾空间
        (None, None),    # 未核验 → 弃权，严禁当 0 处理
    ],
)
def test_e2_left_tail_unit_conversion(depth_to_sotp: float | None, expected: float | None) -> None:
    """量纲换算：`depth_to_sotp` 为百分比且现价高于底座时为负，须归一为正值左尾深度。"""
    assert _left_tail_depth_pct(depth_to_sotp) == expected


# =============================================================================
# E-3 预告变脸量化判据
# =============================================================================


def _forecast_gov(ftype: str = "", p_min: float | None = None, p_max: float | None = None) -> dict:
    return {
        "forecast": {
            "type": ftype,
            "p_change_min": p_min,
            "p_change_max": p_max,
            "net_profit_min": None,
            "ann_date": "2026-07-15",
        }
    }


def test_e3_quantitative_collapse_triggers_fatal():
    """预告同比跌破 config.FORECAST_DROP_FATAL_RATIO 时必须判致命。"""
    flags = AuditEngine()._check_forecast_anomaly(_forecast_gov(ftype="预减", p_min=-80.0, p_max=-60.0))
    fatal = [f for f in flags if f.level == LEVEL_FATAL]

    assert fatal, f"未触发致命旗标，实际: {[(f.level, f.title) for f in flags]}"
    assert "断崖" in fatal[0].title
    # 写死阈值：判据须严格对齐 config 常量换算后的百分数
    assert float(fatal[0].value) <= config.FORECAST_DROP_FATAL_RATIO * 100.0


def test_e3_moderate_decline_does_not_trigger_fatal():
    """反向：温和下滑（-20%）不得被判致命。"""
    flags = AuditEngine()._check_forecast_anomaly(_forecast_gov(ftype="预减", p_min=-20.0, p_max=-10.0))
    assert not any(f.level == LEVEL_FATAL for f in flags)


def test_e3_no_duplicate_fatal_with_negative_forecast_type():
    """去重：预告类型已判致命（首亏）时，不得叠加同一事实的第二条致命旗标。"""
    flags = AuditEngine()._check_forecast_anomaly(_forecast_gov(ftype="首亏", p_min=-150.0, p_max=-120.0))
    assert len([f for f in flags if f.level == LEVEL_FATAL]) == 1


def test_e3_rule_is_inert_without_data_source():
    """数据源状态：无预告数据时规则静默返回，不伪造任何旗标。"""
    assert AuditEngine()._check_forecast_anomaly({}) == []
    assert AuditEngine()._check_forecast_anomaly({"forecast": None}) == []


# =============================================================================
# E-4 游资席位属性接线
# =============================================================================


def test_e4_identifies_dump_risk_personas():
    """命中砸盘属性席位（一日游/砸盘王、散户大本营）时须被识别。"""
    hits = _dump_risk_personas(["佛山无影脚", "拉萨天团", "章盟主"])
    assert "佛山无影脚" in hits      # style = 一日游，翘板，砸盘王
    assert "拉萨天团" in hits        # style = 散户大本营，高频做T
    assert "章盟主" not in hits      # style = 大资金趋势波段，格局锁仓


def test_e4_safe_personas_produce_no_hits():
    """反向：锁仓型游资与空名单不得触发防砸纪律。"""
    assert _dump_risk_personas(["章盟主", "方新侠"]) == []
    assert _dump_risk_personas([]) == []
    assert _dump_risk_personas(None) == []
    assert _dump_risk_personas(["未知游资"]) == []     # 不在 SEATS 中


def test_e4_dump_risk_lowers_entry_range_and_tightens_exit():
    """命中砸盘席位时：挂单区间下移、禁止 9:25 抢筹、退出纪律收紧。"""
    builder = PlaybookBuilder()
    base_kwargs = {
        "quote": {"close": 20.0, "pre_close": 19.5},
        "momentum": {"support_level": 19.0, "resistance_level": 22.0},
        "action": "BUY",
        "ladder_info": {"is_leader": True, "board_level": 3},
        "fatal_flag": False,
        "position_cap": config.MAX_SINGLE_POSITION_EXTREME,
    }
    safe = builder.build(**base_kwargs, matched_personas=["章盟主"])
    risky = builder.build(**base_kwargs, matched_personas=["佛山无影脚"])

    assert "防砸" in risky.entry_tactic or "砸盘" in risky.entry_tactic
    assert risky.action == "BUY"                  # 防砸纪律不得误降级为 AVOID
    assert risky.entry_price_range != safe.entry_price_range
    assert "防砸" in risky.stop_loss_line
    assert "防砸退出线" in risky.invalidation_rule
    # 仓位配比不受席位属性影响（避免越权干预 ❺ 决策节点）
    assert risky.max_position_pct == safe.max_position_pct


# =============================================================================
# C-7 换手率阈值对齐 SRS FR-06
# =============================================================================


def test_c7_turnover_thresholds_match_srs():
    """SRS FR-06 要求换手率 8%~25%，config 必须严格一致。"""
    assert config.MOMENTUM_MIN_TURNOVER_RATE == 8.0
    assert config.MOMENTUM_MAX_TURNOVER_RATE == 25.0
    assert config.MOMENTUM_MIN_TURNOVER_RATE < config.MOMENTUM_MAX_TURNOVER_RATE


# =============================================================================
# C-1 Lint 规则覆盖声明
# =============================================================================


def test_c1_lint_rule_ids_declared():
    """Lint 实装 R7/R8/R9/R10/R11/R12/R13 共 7 条；R1~R6 无定义、保留空位。"""
    from lint.validator import LintValidator

    validator = LintValidator()
    for rule in ("_check_r10_verdict_domain", "_check_r11_single_truth_leak", "_check_r12_arithmetic_closure"):
        assert hasattr(validator, rule), f"缺失机检规则 {rule}"

    # 取值域白名单必须覆盖 judgment_chain 的全部合法取值
    assert "未核验(净利润为负)" in LintValidator.VERDICT_DOMAINS["odds_verdict"]
    assert "不好" in LintValidator.VERDICT_DOMAINS["quality_verdict"]
