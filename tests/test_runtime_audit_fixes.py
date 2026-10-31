"""20261029 运行时审计（docs/REVIEW_20261029_RUNTIME_AUDIT.md）修复的回归防线。

★ 事故背景（审计 P0-3）：系统里存在三类"字段名错配"，它们的共同特征是
  **不报错、静默退化为 0 / 兜底值**，因此 591 个单测全绿却从未真正测到过：

  1. ``main_force_engine`` 读 ``quote["turnover"]``，而生产 quote 只有
     ``turnover_ratio`` → 换手率恒 0，STAGE_4/5/7 的换手判据永不触发，
     主力阶段置信度被虚增 30 个百分点；
  2. ``eltdx_financial_map`` 产出 ``undistr_porfit``（拼写错误），而
     ``audit_engine`` 读 ``undistr_profit`` → Altman Z-Score 的 RE 项恒为 0；
  3. ``audit_engine`` 读 ``b["total_equity"]``，而生产 balance 只有
     ``total_hldr_eqy_inc_min_int`` / ``total_hldr_eqy_exc_min_int``
     → Altman 的 MV 兜底恒退化为 1.0。

  更根本的成因是**双份真相**：``eltdx_collector`` 与 ``eltdx_financial_map``
  各写一份 T 码映射且口径不一致（已删除前者副本）。

本模块用"契约测试"把这类问题永久拦截：
  * 从 ``eltdx_financial_map`` **生成**期望键集合，反向扫描消费方源码里所有
    ``.get("xxx")`` / ``_first_present(..., ("xxx", ...))`` 的字面量键名，
    凡不在生产键集合内的即判失败；
  * 为 quote 字典建立同样的契约（生产键集合来自
    ``EltdxCollector.get_realtime_quote`` 的返回字面量）。

后续各批次（宏观闸门、AI 单向阀、tracker 口径……）的回归用例也会追加在
本文件里，保持"一次审计 = 一份防线"。
"""
from __future__ import annotations

import re
from pathlib import Path

import pandas as pd
import pytest

from core.audit_engine import AuditEngine
from core.main_force_engine import MainForceStateEngine
from data import eltdx_financial_map as fmap

ROOT = Path(__file__).resolve().parents[1]

# ────────────────────────────────────────────────────────────────
# 生产 quote 契约：EltdxCollector.get_realtime_quote 的返回键
# （★ 改动该返回结构时必须同步这里，否则契约测试会红）
# ────────────────────────────────────────────────────────────────
QUOTE_KEYS: frozenset[str] = frozenset({
    "ts_code", "eltdx_code", "name", "close", "pre_close", "open", "high", "low",
    "pct_chg", "vol", "amount", "total_share", "float_share", "total_mv",
    "circ_mv", "turnover_ratio", "bps", "eps", "pe", "pb",
})

#: 从 quote 字典取数的消费方（相对仓库根目录）
QUOTE_CONSUMERS: tuple[str, ...] = (
    "core/main_force_engine.py",
    "core/capital_matrix.py",
    "core/judgment_chain.py",
    "core/youzi_personas.py",
    "core/investor_panel.py",
    "core/execution_playbook.py",
    "core/derived_metrics.py",
    "core/analyzer.py",
    "screener/rank_composite.py",
)

#: 从财报行（balance/income/cashflow）取数的消费方
STATEMENT_CONSUMERS: tuple[str, ...] = (
    "core/audit_engine.py",
    "core/derived_metrics.py",
)

#: 消费方会从**非财报字典**里读取的键（治理字典 / quote 快照 / 预告子字典）。
#: 这些键不属于 eltdx_financial_map 的产出，需在此显式登记。
NON_STATEMENT_KEYS: frozenset[str] = frozenset({
    # quote 快照
    "close", "name", "pre_close", "total_mv", "circ_mv", "pct_chg", "amount",
    "vol", "turnover_ratio",
    # governance 治理字典（collector.get_f10_governance_and_concept）
    "pledge_ratio", "pledge_ratio_of_own_max", "pledge_source", "violation_count",
    "recent_violation_count", "has_reduction_plan", "hold_decrease_shares",
    "top1_holder_ratio", "holder_change_pct", "forecast", "industry", "concepts",
    "main_business",
    # forecast 预告子字典
    "type", "p_change_min", "p_change_max", "net_profit_min", "ann_date",
    # 旧口径遗留键：DuPont / Buffett / Valuation 仍接受它作为**回退**
    # （见 audit_engine 的 _first_present(..., ("total_hldr_eqy_exc_min_int", "total_equity"))）
    "total_equity",
})


def _produced_statement_keys() -> set[str]:
    """eltdx_financial_map 实际会产出的全部财报字段名（唯一权威）。"""
    keys: set[str] = {"end_date"}          # collector 在落 DataFrame 时补的报告期列
    for mapping in (
        fmap.INCOME_MAP,
        fmap.BALANCE_MAP,
        fmap.CASHFLOW_MAP,
        fmap.BALANCE_ZIP_MAP,
    ):
        for _idx, (_cn_name, field) in mapping.items():
            if field:
                keys.add(field)
    return keys


#: 财报**行**变量的常见命名（用于把"从财报取数"与"从派生结果字典取数"区分开）。
#: 例：``row.get("revenue")`` 是财报取数，``prof.get("roe_latest")`` 是派生结果取数。
STATEMENT_RECEIVERS: frozenset[str] = frozenset({
    "row", "bs_row", "cf_row", "inc_row", "latest_bs", "latest_cf", "latest_inc",
    "old", "new", "b", "bs", "inc", "y", "i",
    "b_now", "b_prev", "bs_now", "bs_prev", "y_now", "y_prev",
    "inc_now", "cf_now", "c_now", "now",
})

_GET_CALL_RE = re.compile(r'([A-Za-z_0-9\]]+)\.get\(\s*["\']([a-z_][a-z0-9_]*)["\']')


def _scan_get_keys(rel_path: str) -> set[str]:
    """扫描源码里**财报行**的 ``X.get("键名")`` 与 ``_first_present(..., ("键名", ...))``。

    只保留两类取数点：
      1. 接收者属于 :data:`STATEMENT_RECEIVERS`（如 ``b.get`` / ``row.get``）；
      2. 接收者是 ``iloc[...]`` 取出的行（形如 ``inc.iloc[-1].get(...)``）。
    派生结果字典（``prof.get("roe_latest")`` 等）不在此契约管辖范围。
    """
    src = _strip_comments((ROOT / rel_path).read_text(encoding="utf-8"))
    keys = {
        key
        for receiver, key in _GET_CALL_RE.findall(src)
        if receiver in STATEMENT_RECEIVERS or receiver.endswith("]")
    }
    # _first_present(row, ("a", "b")) —— 同一行内的字面量键
    for line in src.splitlines():
        if "_first_present(" in line:
            keys |= set(re.findall(r'["\']([a-z_][a-z0-9_]*)["\']', line))
    return keys


def _strip_comments(src: str) -> str:
    """去掉整行注释 —— 注释里引用的键名（如"旧代码读 turnover"）不应触发契约。"""
    return "\n".join(ln for ln in src.splitlines() if not ln.strip().startswith("#"))


def _scan_quote_keys(rel_path: str) -> set[str]:
    """扫描源码里从 quote 字典取数的键名（``quote.get`` / ``real_quote.get`` / ``q.get``）。"""
    src = _strip_comments((ROOT / rel_path).read_text(encoding="utf-8"))
    return set(re.findall(r'(?:real_)?quote\.get\(\s*["\']([a-z_][a-z0-9_]*)["\']', src)) | set(
        re.findall(r'(?<![a-z_])q\.get\(\s*["\']([a-z_][a-z0-9_]*)["\']', src)
    )


# ════════════════════════════════════════════════════════════════
# 一、财报字段名契约
# ════════════════════════════════════════════════════════════════
def test_fmap_produces_correctly_spelled_undistr_profit():
    """★ 拼写守卫：必须产出 ``undistr_profit``，绝不能是 ``undistr_porfit``。

    Altman Z-Score 的 RE（留存收益）项读的就是这个键，拼错会让 RE 恒为 0。
    """
    produced = _produced_statement_keys()
    assert "undistr_profit" in produced
    assert "undistr_porfit" not in produced, "未分配利润字段名拼写错误（应为 undistr_profit）"


def test_fmap_produces_hldr_equity_keys_not_total_equity():
    """★ 权益口径守卫：产出含少数股东权益键，且不再产出 ``total_equity``。"""
    produced = _produced_statement_keys()
    assert "total_hldr_eqy_inc_min_int" in produced
    assert "total_hldr_eqy_exc_min_int" in produced
    assert "total_equity" not in produced, "生产 balance 不应出现 Tushare 旧键 total_equity"


@pytest.mark.parametrize("rel_path", STATEMENT_CONSUMERS)
def test_statement_key_contract(rel_path: str):
    """★ 契约：消费方读取的每个财报键都必须由 eltdx_financial_map 生产。"""
    produced = _produced_statement_keys()
    consumed = _scan_get_keys(rel_path)
    unknown = consumed - produced - NON_STATEMENT_KEYS
    assert not unknown, (
        f"{rel_path} 读取了生产数据永远不会产出的键: {sorted(unknown)}；"
        f"若确实是新科目，请先在 eltdx_financial_map 中定标后加入映射表"
    )


def test_altman_z_uses_real_market_value():
    """★ Altman 的 MV 必须用真实权益，而不是退化成 1.0。

    构造：无 quote 快照 → 走 ``te`` 兜底；旧代码读 ``total_equity``（不存在）
    → MV=1.0 → X4=0.6*1/90≈0.007；修复后 MV=45.0 → X4=0.6*45/90=0.30。
    """
    bs = pd.DataFrame([{
        "total_assets": 100.0, "total_cur_assets": 40.0, "total_cur_liab": 30.0,
        "total_liab": 90.0, "undistr_profit": 5.0,
        "total_hldr_eqy_inc_min_int": 45.0,
    }])
    inc = pd.DataFrame([{"revenue": 20.0, "operate_profit": -1.0}])
    flags = AuditEngine().run_audit(
        balance_df=bs, cashflow_df=pd.DataFrame(), income_df=pd.DataFrame(inc),
    )
    z_flags = [f for f in flags if f.framework == "Altman Z-Score"]
    assert len(z_flags) == 1
    # Z = 1.2*(40-30)/100 + 1.4*5/100 + 3.3*(-1)/100 + 0.6*45/90 + 1.0*20/100
    #   = 0.12 + 0.07 - 0.033 + 0.30 + 0.20 = 0.657
    # 若 MV 退化成 1.0，Z 会是 0.357 —— 两者都低于灰色区，此处锁定 MV 已生效
    z_value = float(z_flags[0].value)
    assert z_value == pytest.approx(0.657, abs=0.01), (
        f"Z={z_value}：MV 未使用真实权益（旧实现恒为 1.0 会得到 0.357）"
    )


# ════════════════════════════════════════════════════════════════
# 二、quote 字典契约
# ════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("rel_path", QUOTE_CONSUMERS)
def test_quote_key_contract(rel_path: str):
    """★ 契约：消费方从 quote 读取的键必须存在于 get_realtime_quote 的产出中。"""
    consumed = _scan_quote_keys(rel_path)
    unknown = consumed - QUOTE_KEYS
    assert not unknown, (
        f"{rel_path} 读取了 quote 中不存在的键: {sorted(unknown)}；"
        f"生产 quote 键集合见 EltdxCollector.get_realtime_quote"
    )


def test_main_force_reads_turnover_ratio():
    """★ 换手率口径守卫：主力引擎必须读 ``turnover_ratio``。

    对倒自成交（wash trading）判据依赖换手率：同一场景下
      * 传 ``turnover_ratio=15.0`` → 判据应触发；
      * 传旧的错误键 ``turnover=15.0`` → 引擎读不到，判据不应触发。
    后者正是审计前生产环境的真实状态（换手率恒 0）。
    """
    engine = MainForceStateEngine(persistence_window=2)
    # 25 根 K 线，今日放量 1.7 倍（20 日均量 20000 → 今日 34000）
    records = [{"high": 25.0, "low": 20.0, "close": 23.0, "vol": 20000.0} for _ in range(25)]
    records[0]["vol"] = 34000.0
    daily_df = pd.DataFrame(records)

    base_quote = {
        "close": 24.50, "open": 23.80, "high": 24.80, "low": 23.60,
        "pct_chg": 0.5, "amount": 180_000_000.0,
    }

    dec_ok = engine.evaluate(
        "000001.SZ", current_price=24.50,
        quote={**base_quote, "turnover_ratio": 15.0},
        daily_df=daily_df, microstructure={}, momentum={},
    )
    assert dec_ok.anti_spoofing.wash_trading_detected is True, (
        "换手率 15% + 量比 1.7x + 涨跌 0.5% 的低 Amihud 应判定为对倒自成交"
    )

    dec_legacy = engine.evaluate(
        "000001.SZ", current_price=24.50,
        quote={**base_quote, "turnover": 15.0},   # 旧错误键：生产数据里根本不存在
        daily_df=daily_df, microstructure={}, momentum={},
    )
    assert dec_legacy.anti_spoofing.wash_trading_detected is False, (
        "错误键 'turnover' 不应被识别 —— 若被识别说明又回到了兜底读旧键的老路"
    )


# ════════════════════════════════════════════════════════════════
# 三、AI 节点档位单向阀（P0-2）
# ════════════════════════════════════════════════════════════════
def _mk_node(module: str, verdict: str | None, *, with_evidence: bool = True):
    """构造一个"可用"的节点 AIEnrichment（带证据 → 不是弃权）。"""
    from core.ai_enrichment import AIEnrichment, EvidenceRef

    evidence = (EvidenceRef(source="metrics", quote="实测：净利同比 +32%，OCF/NI=1.2"),) if with_evidence else ()
    return AIEnrichment(
        module=module, judgment=verdict, verdict=verdict, analysis={},
        evidence=evidence, nominations=(), abstained=not with_evidence,
        confidence=70.0,
    )


@pytest.mark.parametrize("module,rule,ai,expected", [
    # AI 想升级 → 一律拦截，回退规则
    ("node_decision", "回避", "核心仓", "回避"),
    ("node_decision", "等证据临界(观察)", "期权仓(小)", "等证据临界(观察)"),
    ("node_state", "↓变差", "↑变好+证据确认", "↓变差"),
    ("node_odds", "买完完美未来", "便宜(有余地)", "买完完美未来"),
    ("node_path", "高尾险·不可承受", "可承受", "高尾险·不可承受"),
    # AI 想降级 → 采纳（只能变保守）
    ("node_decision", "核心仓", "回避", "回避"),
    ("node_state", "↑变好+证据确认", "横盘", "横盘"),
    ("node_odds", "便宜(有余地)", "已被价格计入", "已被价格计入"),
    ("node_path", "可承受", "高尾险·不可承受", "高尾险·不可承受"),
])
def test_node_verdict_valve(module: str, rule: str, ai: str, expected: str):
    """★ 五节点 verdict 级单向阀：只能降级，不能升级。"""
    from core.ai_coprocessor.guard import apply_verdict_downgrade_only

    assert apply_verdict_downgrade_only(rule, _mk_node(module, ai), module) == expected


def test_node_verdict_valve_abstains_without_evidence():
    """★ 无证据即弃权：AI 不得在没引用证据的情况下改动任何节点判定。"""
    from core.ai_coprocessor.guard import apply_verdict_downgrade_only

    assert apply_verdict_downgrade_only(
        "核心仓", _mk_node("node_decision", "回避", with_evidence=False), "node_decision"
    ) == "核心仓"
    # None / 弃权同理
    assert apply_verdict_downgrade_only("核心仓", None, "node_decision") == "核心仓"


def test_node_verdict_valve_abstains_when_rule_outside_domain():
    """★ 规则判定不在取值域内（如「未核验(微观缺失)」）→ 无法比较序值 → 回退规则。"""
    from core.ai_coprocessor.guard import apply_verdict_downgrade_only

    assert apply_verdict_downgrade_only(
        "未核验(微观缺失)", _mk_node("node_path", "可承受"), "node_path"
    ) == "未核验(微观缺失)"


def test_pillar5_recomputes_cap_after_ai_downgrade():
    """★ 002273 型指令冲突：档位被 AI 降级后，仓位必须按新档位重算。

    规则给「核心仓 + 20% 仓位」（主力给足、微观未降级）。AI 降级到
    「等证据临界(观察)」后，仓位必须跟着归零 —— 旧实现档位改了、仓位不动，
    报告就会出现「档位: 期权仓(小) + 仓位: 0%」这种自相矛盾的指令。
    """
    from core.types import (
        OddsVerdict, PathVerdict, QualityVerdict, SingleStockContext, StateVerdict,
    )
    from core.pillars.pillar5_decision import build_pillar_5_decision

    ctx = SingleStockContext(
        ticker="002273.SZ", name="水晶光电", trade_date="20261029",
        quote={"close": 10.0}, microstructure={"smart_buy_ratio": 60.0, "smart_sell_ratio": 40.0},
    )
    q = QualityVerdict(verdict="好", pillar_text="", sub_verdicts=[], fatal_flags=[], is_fatal=False)
    s = StateVerdict(verdict="↑变好+证据确认", pillar_text="", critical_wait="无", is_tech=False)
    o = OddsVerdict(verdict="合理", pillar_text="", sotp_ps=9.0, dcf_ps=11.0,
                    derivation={}, anchor_range={}, reverse_dcf={}, ni_is_verified=True)
    p = PathVerdict(
        verdict="可承受", pillar_text="", is_micro_degraded=False,
        mf_stage_code="STAGE_4_MARKUP", mf_stage="主升浪", mf_behavior="", mf_override=None,
        mf_cap=0.20, mf_conf=80.0, is_trans=False, depth_to_sotp=10.0, profit_chip_pct=80.0,
    )
    kwargs = dict(
        ctx=ctx, q_verdict=q, s_verdict=s, o_verdict=o, p_verdict=p,
        stock_track="TRACK_A_THEME", is_market_ice=False, macro_res=None,
        ret_10d=15.0, is_gem_star=False, is_bse=False, overhead_chips=15.0,
        ma5=9.8, ma20=9.2, support_lvl=9.5, resistance_lvl=10.5,
    )

    base = build_pillar_5_decision(**kwargs)
    assert base.decision_gear == "核心仓"
    assert base.position_cap > 0.0

    # AI 只能降级 —— 升级诉求一律无效
    upgrade = build_pillar_5_decision(**kwargs, nodes={"node_decision": _mk_node("node_decision", "核心仓")})
    assert upgrade.decision_gear == "核心仓"

    down = build_pillar_5_decision(
        **kwargs, nodes={"node_decision": _mk_node("node_decision", "等证据临界(观察)")},
    )
    assert down.decision_gear == "等证据临界(观察)"
    assert down.position_cap == 0.0, "档位降级为观察后，仓位必须同步归零"


# ════════════════════════════════════════════════════════════════
# 四、全市场宏观闸门（P0-1）
# ════════════════════════════════════════════════════════════════
def _mk_macro(*, open_: bool, spec_regime: str = "震荡轮动试盘", cap_pct: int = 40):
    """构造一个 MacroRegimeResult 形态的闸门结果（不依赖真实行情）。"""
    from types import SimpleNamespace

    return SimpleNamespace(
        is_gate_open=open_,
        macro_regime_label="【大盘破位阴跌 + 局部妖股逆势抱团】" if not open_ else "【大盘与短线情绪共振主升】",
        composite_score=32.0 if not open_ else 78.0,
        resonance_type="DIVERGENCE_SPECULATIVE_CLING" if not open_ else "RESONANCE_BULL",
        speculative_regime=spec_regime,
        suggested_position_cap_pct=cap_pct,
        gate_description="闸门测试描述",
        risk_warnings=["测试警示"],
    )


def test_macro_gate_closes_market():
    """★ 闸门收紧 → 今日不交易：buyable 全部改写，单票上限归零。"""
    from screener.market_gate import GATE_BLOCKED_ACTION, apply_macro_gate, single_name_cap_pct

    picks = [
        {"code": "000001", "action": "buyable", "playbook": object()},
        {"code": "000002", "action": "wait_reseal", "playbook": object()},
    ]
    gate = apply_macro_gate(picks, _mk_macro(open_=False))

    assert gate["status"] == "CLOSED"
    assert single_name_cap_pct(_mk_macro(open_=False)) == 0.0
    assert picks[0]["action"] == GATE_BLOCKED_ACTION
    assert picks[0]["playbook"] is None, "闸门收紧时不得再输出进场挂单剧本"
    assert picks[0]["macro_single_name_cap_pct"] == 0.0
    assert gate["buyable_rewritten"] == 1
    assert "今日不交易" in gate["market_note"]
    # 非 buyable 的动作不被改写
    assert picks[1]["action"] == "wait_reseal"


def test_macro_gate_halves_cap_in_speculative_regime():
    """★ 闸门放行但处于投机期 → 单票上限减半（常规档 20% → 10%）。"""
    from screener.market_gate import apply_macro_gate, single_name_cap_pct

    normal = single_name_cap_pct(_mk_macro(open_=True, spec_regime="震荡轮动试盘"))
    speculative = single_name_cap_pct(
        _mk_macro(open_=True, spec_regime="高位共振放量分歧 (筹码集中派发)")
    )
    assert normal == pytest.approx(20.0)
    assert speculative == pytest.approx(10.0)

    picks = [{"code": "000001", "action": "buyable"}]
    gate = apply_macro_gate(picks, _mk_macro(open_=True, spec_regime="弱市妖股逆势抱团 (流动性避险博傻)"))
    assert gate["status"] == "OPEN"
    assert picks[0]["action"] == "buyable", "闸门放行时不得改写动作"
    assert picks[0]["macro_single_name_cap_pct"] == pytest.approx(10.0)


def test_macro_gate_unverified_is_not_open():
    """★ 闸门未核验 ≠ 放行：不写仓位额度，状态标 UNVERIFIED。"""
    from screener.market_gate import apply_macro_gate, single_name_cap_pct

    assert single_name_cap_pct(None) is None
    picks = [{"code": "000001", "action": "buyable"}]
    gate = apply_macro_gate(picks, None)

    assert gate["status"] == "UNVERIFIED"
    assert gate["is_gate_open"] is None
    assert "macro_single_name_cap_pct" not in picks[0], "未核验不得假装给了仓位额度"
    assert "严禁视为" in gate["market_note"]


def test_gear_badge_covers_all_six_gears():
    """★ P1-13：顶部标签必须认识 pillar5 的全部六档，不得把「期权仓(小)」画成回避。"""
    from core.ai_enrichment import NODE_VERDICT_DOMAIN
    from presentation.html_renderer import GEAR_BADGE, gear_display

    for gear in NODE_VERDICT_DOMAIN["node_decision"]:
        assert gear in GEAR_BADGE, f"档位 {gear} 缺少顶部标签映射"

    cls, label = gear_display("期权仓(小)", 0.05)
    assert "回避" not in label and "空仓" not in label, (
        f"「期权仓(小)」是可小仓试错档，不得显示成回避/空仓（002273 事故）: {label}"
    )
    assert cls == "badge-buy"

    # 未知档位按仓位兜底：有仓位就不是回避档
    assert "回避" in gear_display("某种新档位", 0.0)[1]
    assert "回避" not in gear_display("某种新档位", 0.05)[1]


# ════════════════════════════════════════════════════════════════
# 五、追踪账本 T+1 口径（P0-4）
# ════════════════════════════════════════════════════════════════
class _FakeCollector:
    """给定代码的日 K（含选出日与其后一个交易日）。"""

    def __init__(self, bars: dict[str, list[dict[str, Any]]]):
        self._bars = bars

    def get_daily(self, code: str, count: int = 20, adjust: str | None = None):
        import pandas as pd

        rows = self._bars.get(code)
        return pd.DataFrame(rows if rows else [])


def _bars(pick_date: str, *, open_: float, close: float, high: float | None = None, low: float | None = None):
    """构造 [选出日, T+1] 两根 K 线。"""
    return [
        {"trade_date": pick_date, "open": 10.0, "high": 10.5, "low": 9.5, "close": 10.0},
        {
            "trade_date": "20990101",
            "open": open_,
            "high": high if high is not None else max(open_, close) * 1.02,
            "low": low if low is not None else min(open_, close) * 0.98,
            "close": close,
        },
    ]


def test_tracker_uses_next_open_not_pick_close(tmp_path, monkeypatch):
    """★ 基准必须是次日开盘价：选出日收盘价是"看后视镜开车"，不可作为成交价。"""
    import screener.tracker as tracker

    monkeypatch.setattr(tracker, "TRACKER_PATH", tmp_path / "t.jsonl")
    tracker.record_screen_picks(
        [{"code": "000001", "name": "A", "close": 10.0, "pct_chg": 5.0, "action": "buyable"}],
        mode="close", track="TRACK_A", trade_date="20260101",
    )
    # 次日开盘 10.8（高开 8%），收盘 11.0 —— 旧口径 (11.0-10.0)/10.0 = +10.0%
    # 正确口径 (11.0-10.8)/10.8 = +1.85%，扣双边成本 ≈0.10%（佣金 25×2 + 印花税 50 + 过户费 2）后 ≈ +1.75%
    coll = _FakeCollector({"000001": _bars("20260101", open_=10.8, close=11.0)})
    res = tracker.evaluate_tracker_performance(coll)

    detail = res["details"][0]
    assert detail["status"] == "COMPLETED"
    assert detail["next_open"] == 10.8
    assert detail["t1_return_gross_pct"] == pytest.approx(1.85, abs=0.01)
    assert detail["t1_return_pct"] < detail["t1_return_gross_pct"], "净收益必须扣费"
    assert detail["t1_return_pct"] == pytest.approx(1.75, abs=0.02)
    assert detail["t1_fee_pct"] == pytest.approx(0.102, abs=0.001)


def test_tracker_excludes_unfillable_one_word_board(tmp_path, monkeypatch):
    """★ 一字板买不到 → 标记 UNFILLABLE 并剔出胜率分母（不许算赢也不许算输）。"""
    import screener.tracker as tracker

    monkeypatch.setattr(tracker, "TRACKER_PATH", tmp_path / "t.jsonl")
    tracker.record_screen_picks(
        [
            {"code": "000001", "name": "一字涨停", "close": 10.0, "action": "buyable"},
            {"code": "000002", "name": "正常下跌", "close": 10.0, "action": "buyable"},
        ],
        mode="close", track="TRACK_A", trade_date="20260101",
    )
    coll = _FakeCollector({
        # 一字涨停：开=高=低=收
        "000001": _bars("20260101", open_=11.0, close=11.0, high=11.0, low=11.0),
        # 正常：开盘 10.0 收盘 9.8 → 亏
        "000002": _bars("20260101", open_=10.0, close=9.8),
    })
    res = tracker.evaluate_tracker_performance(coll)

    assert res["unfillable"] == 1
    assert res["evaluated_samples"] == 1, "不可成交样本不得进入胜率分母"
    assert res["win_rate_pct"] == 0.0
    one_word = next(d for d in res["details"] if d["code"] == "000001")
    assert one_word["status"] == "UNFILLABLE"
    assert one_word["t1_return_pct"] is None


def test_tracker_dedupes_and_splits_by_track(tmp_path, monkeypatch):
    """★ 同一 (report_id, code) 只记一次；四轨分账各自统计胜率。"""
    import screener.tracker as tracker

    monkeypatch.setattr(tracker, "TRACKER_PATH", tmp_path / "t.jsonl")
    picks = [{"code": "000001", "name": "A", "close": 10.0, "action": "buyable"}]

    assert tracker.record_screen_picks(picks, mode="close", track="TRACK_A", trade_date="20260101") == 1
    # 同一天同一报告重复落账 → 去重
    assert tracker.record_screen_picks(picks, mode="close", track="TRACK_A", trade_date="20260101") == 0
    # 另一轨道（不同 track 标签）仍要入账
    tracker.record_screen_picks(
        [{"code": "000002", "name": "B", "close": 10.0, "action": "buyable"}],
        mode="close", track="TRACK_D", trade_date="20260101",
    )
    assert len(tracker.load_tracker_records()) == 2

    coll = _FakeCollector({
        "000001": _bars("20260101", open_=10.0, close=10.5),   # 赢
        "000002": _bars("20260101", open_=10.0, close=9.5),    # 输
    })
    res = tracker.evaluate_tracker_performance(coll)
    assert set(res["by_track"]) == {"TRACK_A", "TRACK_D"}
    assert res["by_track"]["TRACK_A"]["win_rate_pct"] == 100.0
    assert res["by_track"]["TRACK_D"]["win_rate_pct"] == 0.0


# ════════════════════════════════════════════════════════════════
# 六、P1 快修：阈值 / 口径 / 板块识别 / 单位换算
# ════════════════════════════════════════════════════════════════
def test_track_b_rejects_crash_not_pullback():
    """★ P1-1：弱转强要的是**浅回调**，跌 9% 属破位，不得当洗盘接飞刀。"""
    import screener.tracks as T

    cands = [
        {"code": "600001", "full_code": "sh600001", "change_pct": -2.0, "amount": 3.0e8},
        {"code": "600002", "full_code": "sh600002", "change_pct": -9.0, "amount": 3.0e8},
    ]
    kept, dropped = T.prefilter_track_b(cands, broken_codes=set())
    assert {c["code"] for c in kept} == {"600001"}
    assert dropped.get(T.B_TOO_WEAK_TODAY) == 1
    # 炸板行天然豁免（它才是"弱"的来源），即使跌幅大也保留
    kept2, _ = T.prefilter_track_b(cands, broken_codes={"600002"})
    assert {c["code"] for c in kept2} == {"600001", "600002"}


def test_board_prefix_covers_302_and_689():
    """★ P1-12：深市 302 / 沪市 689 必须按双创 20% 弹性算，不得退回主板 10%。"""
    from core.youzi_personas import extract_tape_features

    def _strong(ts_code: str, pct: float) -> bool | None:
        f = extract_tape_features(
            quote={"close": 10.0, "pct_chg": pct, "amount": 3.0e8, "turnover_ratio": 5.0, "ts_code": ts_code},
            momentum={"is_bullish_ma": True},
            market_cap=50e8,
            theme_info={"concepts": ["题材"], "leader_rank": 1, "breadth_pct": 70.0},
        )
        return f["strong"]

    # 5% 涨幅：主板(10%)→ strong(≥4%) 成立；双创(20%)→ strong(≥8%) 不成立
    assert _strong("600001.SH", 5.0) is True
    assert _strong("302132.SZ", 5.0) is False, "302 段漏判会把它按主板 10% 弹性算"
    assert _strong("689009.SH", 5.0) is False, "689 段漏判会把它按主板 10% 弹性算"
    assert _strong("301001.SZ", 5.0) is False
    # 北交所 30% 弹性
    assert _strong("830799.BJ", 5.0) is False


def test_tape_features_abstain_instead_of_fabricating():
    """★ P1-8：取不到的字段必须弃权（None），不得用 3.0 / 1 / 65.0 / price*1e8 造数。"""
    from core.youzi_personas import extract_tape_features

    f = extract_tape_features(
        quote={"close": 10.0, "pct_chg": 2.0, "amount": 3.0e8},   # 无 turnover_ratio
        momentum={},                                               # 无 volume_ratio
        market_cap=0.0,                                            # 市值不可得
        theme_info={"concepts": ["题材"]},                          # 无龙头位/热度
    )
    assert f["active"] is None, "换手率与量比都不可核验时必须弃权，不得默认活跃"
    assert f["leader"] is None, "无龙头位不得自封龙头（旧实现默认 1）"
    assert f["breadth"] is None, "无题材热度不得自封热度（旧实现默认 65.0）"
    assert f["small_cap"] is None, "市值不可得不得用 price*1e8 反推"
    assert f["risk_off"] is None, "市场级 risk_off 未观测到时不得恒 False"
    assert f["sample_low"] is None
    # 给了真值就必须原样生效
    f2 = extract_tape_features(
        quote={"close": 10.0, "pct_chg": 2.0, "amount": 3.0e8, "turnover_ratio": 5.0},
        momentum={}, market_cap=50e8,
        theme_info={"concepts": ["题材"], "leader_rank": 1, "breadth_pct": 70.0},
        market_risk_off=True, sample_low=True,
    )
    assert f2["active"] is True and f2["leader"] is True and f2["small_cap"] is True
    assert f2["risk_off"] is True and f2["sample_low"] is True


def test_overhead_chip_is_labeled_as_volume_proxy():
    """★ P1-4：「上方套牢盘」的真实口径必须被标明是 60 日量能代理，不能冒充真筹码。"""
    import pandas as pd

    from core.game_features import GameFeatureExtractor

    n = 60
    df = pd.DataFrame({
        "trade_date": [f"2026{i:04d}" for i in range(n)],
        # 前 30 天高价放量（形成"上方套牢量"），后 30 天低价
        "close": [20.0] * 30 + [10.0] * 30,
        "vol": [1000.0] * n,
        "pct_chg": [0.0] * n,
    })
    m = GameFeatureExtractor().extract_momentum(df)

    assert m["overhead_chip_pct"] == pytest.approx(50.0, abs=0.5)
    # 语义明确的别名与口径标记
    assert m["overhead_volume_pct_60d"] == m["overhead_chip_pct"]
    assert m["overhead_chip_basis"] == "volume_proxy_60d"


def test_life_line_uses_real_pre_close():
    """★ P1-7：生命线必须是真实昨收，不能是"当前价的 98%"这种盘中不存在的价位。"""
    from core.types import (
        OddsVerdict, PathVerdict, QualityVerdict, SingleStockContext, StateVerdict,
    )
    from core.pillars.pillar5_decision import build_pillar_5_decision

    ctx = SingleStockContext(
        ticker="000001.SZ", name="测试", trade_date="20261029",
        quote={"close": 10.0, "pre_close": 9.50},   # 昨收 9.50；旧实现会算成 10*0.98=9.80
        ladder_info={"board_level": 3, "is_leader": True},
    )
    q = QualityVerdict(verdict="好", pillar_text="", sub_verdicts=[], fatal_flags=[], is_fatal=False)
    s = StateVerdict(verdict="↑变好但仅注意力·未确认", pillar_text="", critical_wait="无", is_tech=False)
    o = OddsVerdict(verdict="合理", pillar_text="", sotp_ps=9.0, dcf_ps=11.0,
                    derivation={}, anchor_range={}, reverse_dcf={}, ni_is_verified=True)
    p = PathVerdict(
        verdict="可承受", pillar_text="", is_micro_degraded=False,
        mf_stage_code="STAGE_4_MARKUP", mf_stage="主升浪", mf_behavior="", mf_override=None,
        mf_cap=0.20, mf_conf=80.0, is_trans=False, depth_to_sotp=10.0, profit_chip_pct=80.0,
    )
    d = build_pillar_5_decision(
        ctx=ctx, q_verdict=q, s_verdict=s, o_verdict=o, p_verdict=p,
        stock_track="TRACK_A_THEME", is_market_ice=False, macro_res=None,
        ret_10d=15.0, is_gem_star=False, is_bse=False, overhead_chips=15.0,
        ma5=9.8, ma20=9.2, support_lvl=9.5, resistance_lvl=10.5,
    )
    assert "9.50元" in d.invalidation_line, f"生命线应为真实昨收 9.50 元: {d.invalidation_line}"
    assert "9.80元" not in d.invalidation_line


def test_life_line_degrades_explicitly_when_pre_close_missing():
    """★ 前收盘缺失 → 如实标注未核验，绝不用现价折算冒充昨收。"""
    from core.types import (
        OddsVerdict, PathVerdict, QualityVerdict, SingleStockContext, StateVerdict,
    )
    from core.pillars.pillar5_decision import build_pillar_5_decision

    ctx = SingleStockContext(
        ticker="000001.SZ", name="测试", trade_date="20261029", quote={"close": 10.0},
        ladder_info={"board_level": 3, "is_leader": True},
    )
    q = QualityVerdict(verdict="好", pillar_text="", sub_verdicts=[], fatal_flags=[], is_fatal=False)
    s = StateVerdict(verdict="↑变好但仅注意力·未确认", pillar_text="", critical_wait="无", is_tech=False)
    o = OddsVerdict(verdict="合理", pillar_text="", sotp_ps=9.0, dcf_ps=11.0,
                    derivation={}, anchor_range={}, reverse_dcf={}, ni_is_verified=True)
    p = PathVerdict(
        verdict="可承受", pillar_text="", is_micro_degraded=False,
        mf_stage_code="STAGE_4_MARKUP", mf_stage="主升浪", mf_behavior="", mf_override=None,
        mf_cap=0.20, mf_conf=80.0, is_trans=False, depth_to_sotp=10.0, profit_chip_pct=80.0,
    )
    d = build_pillar_5_decision(
        ctx=ctx, q_verdict=q, s_verdict=s, o_verdict=o, p_verdict=p,
        stock_track="TRACK_A_THEME", is_market_ice=False, macro_res=None,
        ret_10d=15.0, is_gem_star=False, is_bse=False, overhead_chips=15.0,
        ma5=9.8, ma20=9.2, support_lvl=9.5, resistance_lvl=10.5,
    )
    assert "未核验(前收盘价缺失)" in d.invalidation_line


def test_capital_matrix_converts_wan_to_yi_correctly():
    """★ P1-11：万元 → 亿元是 /10000（旧代码 /100，金额被放大 100 倍）。"""
    from core.capital_matrix import CapitalMatrixRadar

    res = CapitalMatrixRadar().evaluate(
        quote={"close": 10.0, "pe": 20.0, "pb": 2.0, "turnover_ratio": 5.0, "total_mv": 50e8},
        momentum={"overhead_chip_pct": 20.0, "current_drawdown": -3.0},
        flags=[], trap_warnings=[], matched_personas=[], concepts=["题材"],
        ladder_info={"is_leader": False, "board_level": 1},
        money_flow={"main_net_wan": 5000.0, "super_large_net_wan": 3000.0},
        lhb_records=[],
    )
    hm = next(d for d in res.dimensions if d.dimension_id == "hot_money")
    # 5000 万元 = 0.5 亿元；旧实现会显示成 50 亿元
    assert "0.5 亿元" in hm.summary
    assert "50.0 亿元" not in hm.summary


# ════════════════════════════════════════════════════════════════
# 七、P1-10 金融业门控 / P1-9 补排雷 / §3.3 复权
# ════════════════════════════════════════════════════════════════
def test_manufacturing_calibrated_models_abstain_for_financials():
    """★ P1-10：金融业门控必须覆盖全部制造业校准模型，而不止 Beneish / Altman。"""
    import pandas as pd

    from core.audit_engine import AuditEngine

    flags = AuditEngine().run_audit(
        balance_df=pd.DataFrame(), cashflow_df=pd.DataFrame(), income_df=pd.DataFrame(),
        governance_info={"industry": "金融"},
    )
    abstained = {f.title.split(" 模型不适用")[0] for f in flags if "主动弃权" in f.title}
    assert abstained == {"Piotroski F-Score", "Beneish M-Score", "Altman Z-Score",
                         "DuPont 分解", "Buffett 质量检查", "Sloan 应计异象"}
    # 弃权必须是"无分值"的告知，绝不能顺手给出分数
    assert all(f.value is None for f in flags if "主动弃权" in f.title)


def test_industry_keywords_cover_life_and_property_insurers():
    """★ P1-10：「中国人寿」「中国财险」这类简称里没有"保险"二字，必须也能识别。"""
    from core.industry import INDUSTRY_FINANCIAL, classify_industry

    assert classify_industry(name="中国人寿") == INDUSTRY_FINANCIAL
    assert classify_industry(name="中国财险") == INDUSTRY_FINANCIAL
    assert classify_industry(name="新华保险") == INDUSTRY_FINANCIAL


def test_funnel_rebate_keeps_conservation():
    """★ P1-9：被截断的标的重新纳入排雷时，必须回冲截断计数，否则归因矩阵重复计数。"""
    from screener.funnel_audit import FunnelAudit

    a = FunnelAudit()
    a.record_input("AUDIT", 10)
    a.record_drop("AUDIT", "QUEUE_TRUNCATED", 6)     # 10 只里截掉 6 只
    a.record_drop("AUDIT", "VETO", 1)
    a.record_output("AUDIT", 3)
    assert a.violations() == []

    # 尾部再拉 2 只回来排雷：1 只通过、1 只被否决
    a.rebate_drop("AUDIT", "QUEUE_TRUNCATED", 2)
    a.record_drop("AUDIT", "VETO", 1)
    a.record_output("AUDIT", 4)                      # 3 + 1
    assert a.violations() == [], a.violations()


def test_audit_queue_returns_tail_for_refill():
    """★ P1-9：限流截断时尾部必须随队列返回（供精选池补位），不得直接丢弃。"""
    import config

    import screener.pipeline as pipe
    from screener.funnel_audit import FunnelAudit
    from screener.pipeline import ScreenerPipeline

    cands = [{"code": f"{i:06d}", "board_level": 1, "amount": float(i)} for i in range(10)]
    audit = FunnelAudit()
    audit.record_input(pipe.STAGE_AUDIT, len(cands))

    old = getattr(config, "UNIVERSE_MAX_AUDIT_QUEUE")
    try:
        config.UNIVERSE_MAX_AUDIT_QUEUE = 4
        queue, tail = pipe.ScreenerPipeline.__dict__["_cap_audit_queue"](
            ScreenerPipeline.__new__(ScreenerPipeline), cands, audit
        )
    finally:
        config.UNIVERSE_MAX_AUDIT_QUEUE = old

    assert len(queue) == 4 and len(tail) == 6
    assert audit.stage(pipe.STAGE_AUDIT).dropped.get(pipe.REASON_AUDIT_QUEUE_TRUNCATED) == 6


def test_get_daily_exposes_adjust_without_changing_default():
    """★ §3.3：复权口径必须由调用方显式指定，默认保持不复权（真实成交价）。"""
    import inspect

    from data.eltdx_collector import EltdxCollector

    sig = inspect.signature(EltdxCollector.get_daily)
    assert "adjust" in sig.parameters
    assert sig.parameters["adjust"].default is None, "默认必须是不复权，避免静默改变既有调用方口径"


# ════════════════════════════════════════════════════════════════
# 八、P1-2/P1-3 估值口径（单期 → 年化 / 真实报告期）
# ════════════════════════════════════════════════════════════════
def _snapshot(**kw):
    from screener.finance_batch import FinanceSnapshot

    base = dict(full_code="sz000333", code="000333", eps=1.0, bvps=20.0,
                net_profit=1.0e9, equity=2.0e10, operating_cash_flow=1.5e9,
                total_assets=5.0e10, total_liabilities=2.0e10)
    base.update(kw)
    return FinanceSnapshot(**base)


def test_pe_and_roe_are_annualized_by_report_period():
    """★ P1-2：一季报 EPS/净利必须年化 —— 否则 PE 虚高 4 倍、ROE 虚低 4 倍。"""
    # 年报口径：EPS 4.0 → PE = 20/4 = 5；ROE = 4e9/2e10 = 20%
    annual = _snapshot(eps=4.0, net_profit=4.0e9, report_period="20251231")
    assert annual.pe(20.0) == pytest.approx(5.0)
    assert annual.roe_pct() == pytest.approx(20.0)

    # 一季报口径：EPS 1.0（只赚了 1/4 年）→ 年化 EPS 4.0 → PE 仍是 5（不再是 20）
    q1 = _snapshot(eps=1.0, net_profit=1.0e9, report_period="20250331")
    assert q1.pe(20.0) == pytest.approx(5.0), "一季报 PE 必须按年化 EPS 算"
    assert q1.roe_pct() == pytest.approx(20.0), "一季报 ROE 必须年化，否则被低估 4 倍"

    # 半年报 ×2 / 三季报 ×4÷3
    assert _snapshot(eps=2.0, net_profit=2.0e9, report_period="20250630").pe(20.0) == pytest.approx(5.0)
    assert _snapshot(eps=3.0, net_profit=3.0e9, report_period="20250930").roe_pct() == pytest.approx(20.0)


def test_valuation_abstains_when_report_period_unknown():
    """★ P1-2/P1-3：报告期不可核验 → 不给 PE/ROE（弃权），绝不拿单期值冒充年度值。"""
    unknown = _snapshot(eps=1.0, net_profit=1.0e9)      # 无 report_period
    assert unknown.pe(20.0) is None
    assert unknown.roe_pct() is None
    assert unknown.pe_basis() == "single_period_unverified"
    assert unknown.roe_basis() == "single_period_unverified"


def test_track_d_passes_unknown_report_period_but_marks_it():
    """★ P1-2：报告期未知时**放行**（不做年度阈值否决），但必须标记 UNVERIFIED。"""
    import screener.tracks as T

    c = {"code": "000333", "full_code": "sz000333", "name": "N000333", "close": 100.0,
         "amount": 2.0e9, "change_pct": 1.0, "board_kind": "main"}
    # 单期 EPS 0.5 → 若不年化，PE=200（远超 30）会被误杀；报告期未知 → 放行
    res = T.screen_track_d([c], {"sz000333": _snapshot(eps=0.5, net_profit=5.0e8)})
    assert len(res.passed) == 1
    assert res.passed[0]["valuation_unverified"] is True
    assert res.passed[0]["pe_basis"] == "single_period_unverified"
    assert res.dropped.get(T.D_PE_TOO_HIGH) is None

    # 报告期已知（年报）→ 该否决就必须否决（PE = 100/0.5 = 200 > 30）
    annual = _snapshot(eps=0.5, net_profit=5.0e8, report_period="20251231")
    res2 = T.screen_track_d([c], {"sz000333": annual})
    assert res2.dropped.get(T.D_PE_TOO_HIGH) == 1


def test_report_period_is_not_updated_date():
    """★ P1-3：报告期（哪一期财报）与数据更新日期是两回事，必须分字段给出。"""
    snap = _snapshot(report_period="20250331", report_date="2026-10-29",
                     report_period_source="archive_latest")
    assert snap.report_period == "20250331"
    assert snap.report_date == "2026-10-29"
    assert snap.report_period_source == "archive_latest"
    assert snap.to_dict()["report_period"] == "20250331"


# ════════════════════════════════════════════════════════════════
# 九、P1-5 微观口径标注 / P2 快修
# ════════════════════════════════════════════════════════════════
def test_microstructure_labels_minute_bar_proxy():
    """★ P1-5：买卖占比是**分钟 K 线口径代理**，必须自曝口径，不得冒充逐笔主动方向。"""
    import datetime as dt
    from types import SimpleNamespace

    from core.microstructure import MicrostructureAnalyzer

    base = dt.datetime(2026, 10, 20, 9, 35)
    bars = [
        SimpleNamespace(time=base + dt.timedelta(minutes=5 * i), open=10.0,
                        close=10.25 if i < 20 else 12.006,
                        volume_lots=1000.0, amount=1020000.0 if i < 20 else 1200300.0)
        for i in range(100)
    ]
    prof = MicrostructureAnalyzer().analyze(bars, current_price=12.0)
    assert prof.smart_flow_basis == "minute_bar_proxy"
    assert prof.smart_flow_is_verified is False


def test_supplement_api_no_plaintext_http():
    """★ P2：第三方行情补充不得走明文 http（可被中间人篡改 name/pe/pb）。"""
    src = (ROOT / "data/supplement_api.py").read_text(encoding="utf-8")
    assert "https://qt.gtimg.cn" in src
    assert "http://qt.gtimg.cn" not in src


def test_no_dead_duplicate_maps_in_collector():
    """★ 双份真相守卫：collector 不得再自带 T 码映射副本（权威只在 fmap）。"""
    src = (ROOT / "data/eltdx_collector.py").read_text(encoding="utf-8")
    for dead in ("BALANCE_MAP", "CASHFLOW_MAP", "INCOME_CODE_MAP"):
        # 只匹配"定义"（``BALANCE_MAP = {`` / ``BALANCE_MAP: dict = {``），
        # 注释里提到这些名字不算
        assert not re.search(rf"^{dead}\s*[:=]", src, flags=re.M), (
            f"{dead} 不应在 collector 中重复定义 —— 映射唯一权威是 eltdx_financial_map"
        )



# ════════════════════════════════════════════════════════════════
# 十、20261030 复核残余项闭环（N-1 / N-2 / P1-5 / P1-10 / P1-14 / §3.3）
# ════════════════════════════════════════════════════════════════
def test_n1_empty_ladder_still_evaluates_macro_gate(monkeypatch):
    """★ N-1 (P0-1残余)：连板天梯为空时仍必须评估大盘指数与广度，不得跳过 _eval_macro。"""
    from types import SimpleNamespace
    import screener.ladder_analyzer as la_mod
    from screener.ladder_analyzer import LadderAnalyzer
    from screener.market_gate import GATE_BLOCKED_ACTION, apply_macro_gate

    class _DummyClient:
        def __enter__(self):
            return SimpleNamespace(f10=SimpleNamespace(limit_board_ladder=lambda: SimpleNamespace(rows=[], trade_date="")))

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(la_mod, "open_client", lambda: _DummyClient())
    fake_coll = SimpleNamespace(
        get_daily=lambda code, count=30: pd.DataFrame([
            {"trade_date": f"202610{30 - i:02d}", "open": 3900.0, "high": 3910.0, "low": 3850.0, "close": 3860.0 - i, "pct_chg": -0.8, "amount": 8.0e11}
            for i in range(25)
        ]),
        get_market_breadth=lambda: {
            "up_count": 900, "down_count": 4200, "flat_count": 100,
            "limit_up_count": 25, "limit_down_count": 45, "total_amount": 1.5e12,
        },
    )
    ov, _, _, _ = LadderAnalyzer(collector=fake_coll).analyze()
    assert ov.macro_regime_result is not None, "天梯为空时仍必须产出 macro_regime_result"
    assert ov.trade_date == "20261030"
    assert ov.total_limit_up_count == 25
    assert ov.total_limit_down_count == 45

    # UNVERIFIED 时也必须阻断 buyable
    picks = [{"code": "000001", "action": "buyable", "playbook": SimpleNamespace(max_position_pct=20)}]
    gate = apply_macro_gate(picks, None)
    assert gate["status"] == "UNVERIFIED"
    assert picks[0]["action"] == GATE_BLOCKED_ACTION
    assert picks[0]["playbook"] is None


def test_n2_report_period_map_resolves_per_stock_period():
    """★ N-2 (P1-2回归)：不得把全局最新季报期套给所有股票，必须按股查最新已披露期。"""
    from data.eltdx_financial import report_period_map

    res = report_period_map(["601398", "688722"])
    assert isinstance(res, dict)
    for k, period in res.items():
        assert len(k) == 6
        assert isinstance(period, str) and len(period) == 8 and period.isdigit()
    # 缓存中工商银行最新为半年报 20260630，而科创板 688722 已发三季报 20260930
    if "601398" in res and "688722" in res:
        assert res["601398"] != res["688722"]


def test_p1_5_microstructure_verifies_real_trade_ticks():
    """★ P1-5 闭环：传入真实逐笔成交 (trades_today) 时，主动买卖占比切换为 trade_tick_active 并标记已核验。"""
    import datetime as dt
    from types import SimpleNamespace
    from core.microstructure import MicrostructureAnalyzer

    base = dt.datetime(2026, 10, 20, 9, 35)
    bars = [
        SimpleNamespace(time=base + dt.timedelta(minutes=5 * i), open=10.0, close=10.1, volume_lots=500.0, amount=505000.0)
        for i in range(25)
    ]
    trades = SimpleNamespace(actual_trades=[
        SimpleNamespace(time_label="09:40", price=10.1, volume=300, side="buy"),
        SimpleNamespace(time_label="09:45", price=10.0, volume=100, side="sell"),
    ])
    prof = MicrostructureAnalyzer().analyze(bars, current_price=10.1, trades_today=trades)
    assert prof.smart_flow_is_verified is True
    assert prof.smart_flow_basis == "trade_tick_active"
    assert prof.smart_buy_ratio == pytest.approx(75.0)
    assert prof.smart_sell_ratio == pytest.approx(25.0)


def test_p1_10_looks_like_financial_row_detects_real_bank_shape():
    """★ P1-10：真实银行资产负债表 T020/T038 为 None 且无工业流动资产小计，必须识别为金融表。"""
    from data.eltdx_financial_map import looks_like_financial_row

    bank_row = {"T007": 1e11, "T016": None, "T020": None, "T038": None, "T039": 5.0e12, "T053": None, "T062": 4.6e12}
    ind_row = {"T007": 1e9, "T016": 2e8, "T020": 5e9, "T038": 5e9, "T039": 1e10, "T053": 3e9, "T062": 4e9}
    assert looks_like_financial_row(bank_row) is True
    assert looks_like_financial_row(ind_row) is False


def test_p1_14_filter_liquidity_scales_thresholds_in_noon_mode():
    """★ P1-14：午盘模式 (noon) 下成交额与最低换手率门槛动态折半。"""
    from screener.filter_liquidity import filter_liquidity

    rows = [{"code": "000001", "full_code": "sz000001", "name": "测试股", "board_level": 1}]
    # 主板门槛 5 亿、换手率门槛 8%：成交额 3 亿、换手率 5% 在收盘模式淘汰，在午盘模式（门槛 2.5 亿 / 4%）放行
    quotes = {"sz000001": {"close": 10.0, "pct_chg": 9.9, "amount": 3.0e8, "turnover_ratio": 5.0}}
    kept_close = filter_liquidity(rows, quotes, mode="close")
    kept_noon = filter_liquidity(rows, quotes, mode="noon")
    assert len(kept_close) == 0
    assert len(kept_noon) == 1


def test_sec33_kline_batch_defaults_to_qfq():
    """★ §3.3：全市场日 K 批量拉取默认使用前复权 (qfq)，避免除权缺口制造假破位。"""
    import inspect
    from screener.kline_batch import fetch_daily_bars

    sig = inspect.signature(fetch_daily_bars)
    assert "adjust" in sig.parameters
    assert sig.parameters["adjust"].default == "qfq"
