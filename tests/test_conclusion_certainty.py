"""结论确定性分层与时效性治理（P1）—— 对应规格
``docs/SPEC_CONCLUSION_CERTAINTY_LAYERING.md``。

起因：第三方评审指出研报「把某一时间切片的微观交易信号，以过高的确定性
固化成了行动指令」，具体三条：

  · 时效性偏误（日内切片被当成持续趋势）
  · 估值框架傲慢（DCF/SOTP 区间被冠以「合理价」，隐含宣称市场价错误）
  · 缺少「事实 / 判断 / 指令」确定性分层（且置信度越高越不提示）

本文件覆盖验收标准 A-1 ~ A-6。★ 本批次**不改任何计算**，只改表达方式，
因此用例全部断言**文本契约**，不断言数值。
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from core.execution_playbook import (
    DISTRIBUTION_STAGES,
    PlaybookBuilder,
    reversal_invalidation_suffix,
)
from core.judgment_chain import (
    JudgmentChainRunner,
    _build_signal_freshness_banner,
    _build_signal_staleness_note,
    _build_valuation_assumption_note,
)
from core.main_force_engine import AntiSpoofingAudit, MainForceStateEngine, StageCode
from presentation.plain_language import plain


# ────────────────────────────────────────────── 构造 derivation / anchor 夹具
def _full_derivation() -> dict:
    """一份字段齐全的 derivation，用于验证假设要点被完整提取。"""
    return {
        "sotp": {
            "segments": [{"name": "金属结构件", "profit": 17.6, "multiple": 20.0,
                          "value": 352.0, "basis": "对标同业合理倍数",
                          "falsify": "订单增速未达预期"}],
            "net_debt": 0.0,
            "enterprise_value": 352.0,
            "equity_value": 352.0,
            "per_share": 79.3,
        },
        "dcf": {
            "discount_rate": {"components": [{"name": "无风险利率", "value": 2.5,
                                              "description": "10 年国债"}],
                              "total": 8.5},
            "scenarios": [{"name": "悲观", "p": 0.3, "cagr": 10.0, "margin": 10.0,
                           "exit_multiple": 15.0},
                          {"name": "中性", "p": 0.5, "cagr": 15.0, "margin": 14.0,
                           "exit_multiple": 18.0},
                          {"name": "乐观", "p": 0.2, "cagr": 20.0, "margin": 18.0,
                           "exit_multiple": 22.0}],
            "equity_value": 456.0,
            "per_share": 102.77,
        },
        "p_f_n": {
            "market_cap": 380.0,
            "fact": 250.0,
            "narrative": 130.0,
            "narrative_share": 0.34,
            "kind": "free_option",
            "fact_basis": "已并表成熟业务年化净利 12.50 亿元 × 基准合理市盈率 20x",
        },
    }


def _anchor(div_note: str | None = "SOTP 仅计入已兑现主业现金流 (低端保守)，"
                                   "DCF 允许温和行业成长放量 (高端乐观)") -> dict:
    return {"low": {"value": 79.3, "basis": "叙事分部 SOTP"},
            "high": {"value": 102.77, "basis": "三情景概率加权 DCF"},
            "same_direction": True,
            "divergence_note": div_note}


# ══════════════════════════════════════════ A-1 假设前提与排除项可见
def test_assumption_note_exposes_prerequisites_and_exclusions():
    """A-1：假设前提与「本估值不含」必须同时出现。"""
    note = _build_valuation_assumption_note(_full_derivation(), _anchor())

    assert "估值假设前提" in note
    assert "本估值不含" in note
    # 排除项必须点明"未盈利新业务期权价值"——这正是评审说的机器人业务溢价
    assert "未并表/未盈利新业务的期权价值" in note
    # 假设前提应把原本的裸魔数说清楚：基准 PE、折现率、增速
    assert "基准合理市盈率 20x" in note
    assert "折现率 8.5%" in note
    assert "三情景 5 年收入增速" in note


def test_assumption_note_declares_market_price_not_wrong():
    """A-1 续：排除项必须明确「市场价高于本区间 ≠ 市场错误」。

    这是「框架傲慢」的核心：原表述暗示市场价格错了，而正确表述是
    两套假设并存。
    """
    note = _build_valuation_assumption_note(_full_derivation(), _anchor())
    assert "并不代表市场错误" in note


# ══════════════════════════════════════════ A-3 divergence_note 被渲染
def test_assumption_note_renders_divergence_note():
    """A-3：``divergence_note`` 此前**生成后从未渲染**（死数据），本次接上。"""
    note = _build_valuation_assumption_note(_full_derivation(), _anchor())
    assert "两端口径差异" in note
    assert "SOTP 仅计入已兑现主业现金流" in note


def test_assumption_note_omits_divergence_when_absent():
    """``divergence_note`` 缺失时不硬凑，直接省略该行（不得输出 None 字面量）。"""
    note = _build_valuation_assumption_note(_full_derivation(), _anchor(div_note=None))
    assert "两端口径差异" not in note
    assert "None" not in note


# ══════════════════════════════════════════ A-6 缺失字段输出未核验，严禁伪造
def test_assumption_note_unverified_when_metadata_missing():
    """A-6：估值元数据缺失时输出「未核验」，**严禁**用默认值伪造假设。"""
    note = _build_valuation_assumption_note({}, _anchor())
    assert "未核验(估值元数据缺失)" in note
    # 不得凭空造出基准 PE / 折现率
    assert "基准合理市盈率" not in note
    assert "折现率" not in note


def test_assumption_note_partial_missing_does_not_fabricate():
    """部分缺失：只输出拿得到的那部分，缺的**不补默认值**。"""
    partial = {"p_f_n": {"fact_basis": "已并表成熟业务年化净利 5.00 亿元 × 基准合理市盈率 15x"}}
    note = _build_valuation_assumption_note(partial, _anchor())
    assert "基准合理市盈率 15x" in note
    assert "折现率" not in note          # dcf 缺失 ⇒ 不得造出 8.5%
    assert "净负债" not in note


# ══════════════════════════════════════════ A-4 时效性声明恒非空
@pytest.mark.parametrize("is_degraded", [True, False])
def test_freshness_banner_is_never_empty(is_degraded):
    """A-4：★ 修复前 `deg_banner` 在**非降级**时是空串。

    后果：96% 置信度的「无抵抗阴跌出清期」在报告里是**裸断言** ——
    置信度越高反而越不提示不确定性。评审的「时效性偏误」正指此处。
    """
    banner = _build_signal_freshness_banner(is_degraded, mf_conf=96.0)
    assert banner.strip() != ""


def test_freshness_banner_degraded_keeps_original_warning():
    """降级场景保留原有的严禁建仓警告（不得被新文案冲掉）。"""
    banner = _build_signal_freshness_banner(True, mf_conf=0.0)
    assert "微观数据降级" in banner
    assert "严禁建仓" in banner


def test_freshness_banner_normal_state_declares_intraday_validity():
    """非降级场景必须说明：这是**当日盘中切片**，跨日须复核。

    依据：`microstructure.py:130` 的 smart_vwap 由当日 5 分钟 K 线加权得出，
    并非跨日沉淀成本 —— 所以「主力成本」天然只有当日有效。
    """
    banner = _build_signal_freshness_banner(False, mf_conf=96.0)
    assert "信号时效" in banner
    assert "当日盘中微观切片" in banner
    assert "不得跨日沿用" in banner
    assert "96.0%" in banner


# ══════════════════════════════════════════ A-2 支柱③不再自称「合理价」
def test_pillar3_uses_conditional_anchor_not_fair_price():
    """A-2：支柱③不得再出现「合理价」，改为**条件锚点**。

    「合理价」隐含"市场价错误"的宣称；「条件锚点」才是"若相信以下假设，
    则值这个区间"的条件性判断。
    """
    runner = JudgmentChainRunner()
    summary, _verdict, _s, _d, _deriv, _a, _r, verified = runner._build_pillar_3_odds(
        price=162.98,
        total_shares_yi=2.73,
        pe_val=25.0,
        total_mv=445e8,
        derived_data={"latest_vitals": {"latest_net_income": 17.64e8}},
        is_tech=True,
        mainbz_list=[{"name": "金属结构制造业", "ratio": 99.9}],
    )
    assert verified is True, "净利为正应可核验"
    assert "合理价" not in summary, f"仍自称合理价: {summary}"
    assert "条件锚点" in summary
    # 数值契约不变：R16 依赖正文价区与 anchor_range 一致
    assert "SOTP=" in summary and "DCF=" in summary


def test_pillar3_still_carries_pfn_and_reverse_dcf():
    """回归护栏：新增假设要点**不得**挤掉原有四行内容。"""
    runner = JudgmentChainRunner()
    summary, *_ = runner._build_pillar_3_odds(
        price=162.98,
        total_shares_yi=2.73,
        pe_val=25.0,
        total_mv=445e8,
        derived_data={"latest_vitals": {"latest_net_income": 17.64e8}},
        is_tech=True,
        mainbz_list=[{"name": "金属结构制造业", "ratio": 99.9}],
    )
    assert "P=F+N 叙事拆解" in summary
    assert "反向 DCF" in summary
    assert "本估值不含" in summary


# ══════════════════════════════════════════ A-5 证伪语义不被弱化
def test_plain_keeps_falsification_semantics():
    """A-5：「证伪线」不得被弱化为单纯价格阈值「退出底线」。

    「证伪线」= 证明判断错了就必须卖（假设可被推翻）；
    「退出底线」= 一个价格阈值。后者丢掉了可推翻性。
    """
    assert plain("证伪线") == "判断错了就退"
    assert "退出底线" not in plain("证伪线：跌破 139.68 元离场")


def test_plain_one_line_uses_falsification_wording():
    """一句话结论同样保留「判断错了就退」而非「退出底线」。"""
    from presentation.plain_language import one_line_summary

    card = {
        "name": "科达利",
        "decision_gear": "回避",
        "three_part_conclusion": "好下注? 【否】",
        "invalidation_line": "跌破 139.68 元离场",
        "position_cap": 0.0,
    }
    text = one_line_summary(card)
    assert "判断错了就退" in text
    assert "退出底线" not in text


# ══════════════════════════════════════════ 护栏：本批次不得改计算
def test_no_computation_changed_by_this_batch():
    """护栏：本批次只改表达，不改任何风控阈值与计算公式。"""
    import config

    assert config.PLEDGE_FATAL_RATIO == 0.70
    assert config.PLEDGE_OWN_FATAL_RATIO == 0.95
    assert config.PLEDGE_OWN_FATAL_MIN_TOTAL == 0.20


# ═════════════════════════════════════════════════════════════════════
# 内部自洽性修复：报告自相矛盾的三处硬伤 + 置信度倒挂
# ═════════════════════════════════════════════════════════════════════

def _stage7_meta(tmp_path, price, vwap, buy=40.0, sell=60.0):
    eng = _engine(tmp_path)
    return eng._get_stage_metadata(
        stage_code=StageCode.STAGE_7_PASSIVE_DRIFT,
        current_price=price, smart_vwap=vwap, overhead_chips=64.1,
        smart_buy_ratio=buy, smart_sell_ratio=sell,
        board_level=1, price_position_60d=0.5, audit=AntiSpoofingAudit(),
    )


def test_price_relation_wording_is_derived_from_numbers(tmp_path):
    """★ 硬伤①：文案必须**从数值派生**，不得无条件断言「跌破」。

    科达利现价 162.98 高于知情均线 148.52，报告却写「现价显著跌破知情均线」，
    与同段落里的数字直接冲突。根因：动词是模板硬编码，从未读取价格关系。
    """
    # 真跌破
    assert "显著跌破" in _stage7_meta(tmp_path, 130.0, 148.52)["behavior_desc"]
    # 站上 —— 绝不能再出现「跌破」
    up = _stage7_meta(tmp_path, 162.98, 148.52)["behavior_desc"]
    assert "已站上" in up
    assert "跌破" not in up, f"现价高于知情均线却仍说跌破: {up}"
    assert "浮盈" in up
    # 贴近
    assert "贴近" in _stage7_meta(tmp_path, 150.0, 148.52)["behavior_desc"]


def test_flow_direction_matches_buy_sell_ratio(tmp_path):
    """★ 硬伤②：资金方向必须与买卖占比一致（与反伪装模块同一真值源）。

    科达利反伪装算出「中位加速接力」(买 59.8% > 卖 40.2%)，
    行为描述却说「缺乏主动承接」—— 同一份数据两个相反结论。
    """
    buy_heavy = _stage7_meta(tmp_path, 162.98, 148.52, buy=59.8, sell=40.2)["behavior_desc"]
    assert "承接迹象" in buy_heavy
    assert "无抵抗流失" not in buy_heavy

    sell_heavy = _stage7_meta(tmp_path, 130.0, 148.52, buy=40.2, sell=59.8)["behavior_desc"]
    assert "缺乏主动承接" in sell_heavy
    assert "承接迹象" not in sell_heavy


def _decide(**kw):
    """构造一次「高尾险·不可承受」档的决断，便于断言文案。"""
    base = dict(
        price=162.98, state_verdict="↑变好+证据确认", odds_verdict="已被价格计入",
        path_verdict="高尾险·不可承受", quality_verdict="部分好",
        is_fatal=False, is_market_ice=False, stock_track="B", macro_res=None,
        mf_stage_code="STAGE_7_PASSIVE_DRIFT", mf_override=None,
        is_micro_degraded=False, mf_cap=0.0, mf_confidence=49.5,
        left_tail_depth_pct=None, ni_is_verified=True, fatal_flags=[],
        ladder_info=None, ret_10d=15.6, is_gem_star=False, is_bse=False,
        overhead_chips=64.1, sotp_ps=79.30, ma5=160.0, ma20=150.0,
        support_lvl=139.68, resistance_lvl=180.0, critical_wait="",
        microstructure={"smart_buy_ratio": 59.8, "smart_sell_ratio": 40.2},
    )
    base.update(kw)
    return JudgmentChainRunner()._decide_gear(**base)


def test_stage7_does_not_use_stage6_wording():
    """★ 硬伤③：STAGE_7 不得被描述成「对倒派发出货期」。

    原逻辑把 STAGE_6/STAGE_7 合并进同一分支，文案只写了 STAGE_6 的说法，
    导致科达利顶部标签是「无抵抗阴跌出清期」、决断卡却说「对倒派发出货期」。
    """
    _gear, title, cap, contra, _tac, _inv, _reg = _decide(
        mf_stage_code="STAGE_7_PASSIVE_DRIFT")
    assert "阴跌出清防守" in title
    assert "无抵抗阴跌出清期" in contra
    assert "对倒派发" not in contra, "STAGE_7 不得套用 STAGE_6 的派发措辞"
    assert cap == 0.0                      # 仓位上限维持 0，风控不受影响


def test_stage6_keeps_distribution_wording():
    """STAGE_6 仍应保留派发措辞（拆分后两端各自对齐语义）。"""
    _gear, title, _cap, contra, _tac, _inv, _reg = _decide(
        mf_stage_code="STAGE_6_DISTRIBUTION",
        microstructure={"smart_buy_ratio": 40.0, "smart_sell_ratio": 60.0},
    )
    assert "派发出货防守" in title
    assert "对倒派发出货期" in contra


def test_low_confidence_softens_instruction_tone():
    """★ 置信度倒挂：49.5%（抛硬币）不得输出「坚决一股不买」级措辞。"""
    _g, _t, cap, _c, tactic, _i, _r = _decide(mf_confidence=49.5)
    assert "暂缓介入" in tactic
    assert "坚决一股不买" not in tactic, "低置信度不得使用极端措辞"
    assert "置信度仅 49.5%" in tactic
    assert cap == 0.0                      # 仓位不变，仅措辞降级


def test_high_confidence_keeps_firm_tone():
    """96% 置信度时保留原有刚性措辞（不得误伤）。"""
    _g, _t, _c1, _c, tactic, _i, _r = _decide(mf_confidence=96.0)
    assert "坚决一股不买" in tactic
    assert "逢反抽清仓" in tactic
    assert "暂缓介入" not in tactic


# ═════════════════════════════════════════════════════════════════════
# 阶段定性校验：交给 AI 判断层（上游范式「脚本算、LLM 判」）
# ═════════════════════════════════════════════════════════════════════

def test_mainforce_module_registered():
    """`mainforce` 必须注册进模块表，否则 enrich() 会拒绝渲染。"""
    from core.ai_enrichment import MODULES

    assert "mainforce" in MODULES


def test_mainforce_prompt_renders():
    """判据手册必须存在且可渲染 —— 判据是业务资产，不在 Python 里。"""
    from core.ai_coprocessor import prompts

    text = prompts.render(
        "mainforce",
        name="科达利", ticker="002850",
        stage_name="【📉 无抵抗阴跌出清期 (流动性枯竭)】",
        confidence="49.5", pct_chg="7.44", price="162.98",
        smart_vwap="148.52", smart_buy_ratio="59.8", smart_sell_ratio="40.2",
        vol_ratio="1.87", avg_amplitude_5d="3.5",
        price_position_60d="0.62", overhead_chips="64.1", ma_relation="MA5 上方",
    )
    assert "自洽性校验" in text
    # ★ 手册必须明令禁止绝对值一刀切（跨市值不可比）
    assert "不可比" in text and "量比" in text and "自身" in text
    assert "（未提供）" not in text


def test_ai_mainforce_noop_when_disabled(monkeypatch):
    """AI 未启用时必须返回空字典 —— 规则判定逐字不受影响。"""
    import config

    monkeypatch.setattr(config, "AI_ENABLED", False)
    out = JudgmentChainRunner()._ai_mainforce(
        ticker="002850", name="科达利",
        microstructure={"main_force_stage": "【📉 无抵抗阴跌出清期】"},
        price=162.98, quote={"pct_chg": 7.44},
        ma5=160.0, ma20=150.0, overhead_chips=64.1,
    )
    assert out == {}


def test_ai_mainforce_abstains_without_stage(monkeypatch):
    """微观未核验时无从校验，直接弃权（不得拿缺失当结论）。"""
    import config

    monkeypatch.setattr(config, "AI_ENABLED", True)
    out = JudgmentChainRunner()._ai_mainforce(
        ticker="002850", name="科达利",
        microstructure={},          # 无 main_force_stage
        price=162.98, quote={"pct_chg": 7.44},
        ma5=160.0, ma20=150.0, overhead_chips=64.1,
    )
    assert out == {}


def test_ai_mainforce_nomination_merges_into_flags(monkeypatch):
    """AI 判 ✗ 时的提名必须能并进红旗池 —— 这是它影响结论的唯一通道。"""
    import config

    import core.ai_coprocessor as ac
    from core.ai_enrichment import AIEnrichment, EvidenceRef, RedFlagNomination

    monkeypatch.setattr(config, "AI_ENABLED", True)
    fake = AIEnrichment(
        module="mainforce",
        judgment="✗",
        evidence=(EvidenceRef(source="metrics", quote="量比 1.87"),),
        nominations=(
            RedFlagNomination(
                id="nom-mainforce-liquidity", level="🟠",
                title="「流动性枯竭」定性被放量证伪",
                evidence="量比 1.87（>1，非枯竭）且买盘占优",
                node="state",
            ),
        ),
    )
    monkeypatch.setattr(ac, "enrich", lambda module, context, **kw: fake)

    out = JudgmentChainRunner()._ai_mainforce(
        ticker="002850", name="科达利",
        microstructure={
            "main_force_stage": "【📉 无抵抗阴跌出清期 (流动性枯竭)】",
            "main_force_confidence": 49.5, "smart_vwap": 148.52,
            "smart_buy_ratio": 59.8, "smart_sell_ratio": 40.2,
            "vol_ratio_20d": 1.87, "avg_amplitude_5d": 3.5,
            "price_position_60d": 0.62,
        },
        price=162.98, quote={"pct_chg": 7.44},
        ma5=160.0, ma20=150.0, overhead_chips=64.1,
    )
    assert out["mainforce"].judgment == "✗"

    flags: list[Any] = []
    JudgmentChainRunner._merge_ai_nominations(flags, out)
    assert any("枯竭" in f.title for f in flags), "AI 提名未进入红旗池"


def test_baselines_exposed_for_relative_judgment():
    """相对化基线（量比/自身振幅）必须透传到 AI 判断层。

    ★ 绝对成交额/绝对涨幅跨市值不可比，判断「枯竭」「涨跌是否显著」
      只能用相对标的自身的量。
    """
    from core.microstructure import MicrostructureProfile

    p = MicrostructureProfile(
        smart_q=1.0, smart_vwap=100.0, all_vwap=100.0,
        smart_buy_ratio=50.0, smart_sell_ratio=50.0,
        smart_phase="NEUTRAL", apm_pattern="NEUTRAL",
        am_return_pct=0.0, pm_return_pct=0.0, tail_vol_ratio=10.0,
        auction_open_amt_wan=0.0, auction_open_chg_pct=0.0,
        verdict_text="", main_force_stage="", main_force_behavior="",
        main_force_risk="", cum_turnover_20d=0.0, price_position_60d=0.5,
    )
    assert p.vol_ratio_20d == 1.0 and p.avg_amplitude_5d == 0.0

    from core.main_force_engine import MainForceDecision

    assert "baselines" in MainForceDecision.__dataclass_fields__


# ═════════════════════════════════════════════════════════════════════
# P2 批次：F-9 信号 TTL / F-10 指令失效 / F-11 STAGE_6-7 反向解禁
# ═════════════════════════════════════════════════════════════════════

def _engine(tmp_path):
    """构造一个不污染真实缓存的主力引擎。"""
    return MainForceStateEngine(cache_file=tmp_path / "mf_state.json")


# ───────────────────────────────────────────────── F-11 反向解禁
def test_f11_releases_from_stage6_when_candidate_improves(tmp_path):
    """F-11：前序 STAGE_6，本周期候选转为震荡 ⇒ 必须解禁，不得卡在熔断档。"""
    eng = _engine(tmp_path)
    eng._history_state["T.SZ"] = (StageCode.STAGE_6_DISTRIBUTION, 1)

    stage, note = eng._apply_state_machine_transition(
        ticker="T.SZ",
        candidate_stage=StageCode.STAGE_3_QUIET_WASHOUT,
        candidate_score=50.0,
        is_transitional=False,
        audit=AntiSpoofingAudit(),
    )
    assert stage == StageCode.STAGE_3_QUIET_WASHOUT
    assert "反向解禁" in note
    assert "仓位上限已恢复" in note


def test_f11_stage6_to_markup_is_not_trapped_by_hysteresis(tmp_path):
    """F-11 关键回归：STAGE_6 → STAGE_4/5 不得被规则 2 的 fallback 卡回 STAGE_6。

    规则 2 的 fallback 是 ``STAGE_3 if prior==STAGE_3 else prior_stage`` ——
    即前序为 STAGE_6 时会**回落回 STAGE_6**，即使资金面已反转,
    0 仓位熔断状态被永久卡死。解禁规则必须先于规则 2 生效。
    """
    eng = _engine(tmp_path)
    eng._history_state["T.SZ"] = (StageCode.STAGE_6_DISTRIBUTION, 1)

    # 得分 60（< 76 碾压阈值）且有扰动 ⇒ 若落到规则 2 就会被迟滞拦下
    audit = AntiSpoofingAudit()
    audit.wash_trading_penalty = 10.0
    stage, note = eng._apply_state_machine_transition(
        ticker="T.SZ",
        candidate_stage=StageCode.STAGE_4_HEALTHY_MARKUP,
        candidate_score=60.0,
        is_transitional=False,
        audit=audit,
    )
    assert stage == StageCode.STAGE_4_HEALTHY_MARKUP, "不得被卡回 STAGE_6"
    assert "反向解禁" in note


def test_f11_releases_from_stage7_as_well(tmp_path):
    """F-11：STAGE_7（无抵抗阴跌）同样需要解禁通道。"""
    eng = _engine(tmp_path)
    eng._history_state["T.SZ"] = (StageCode.STAGE_7_PASSIVE_DRIFT, 3)

    stage, note = eng._apply_state_machine_transition(
        ticker="T.SZ",
        candidate_stage=StageCode.STAGE_1_ACCUMULATION,
        candidate_score=55.0,
        is_transitional=False,
        audit=AntiSpoofingAudit(),
    )
    assert stage == StageCode.STAGE_1_ACCUMULATION
    assert "反向解禁" in note


def test_f11_no_release_note_between_non_distribution_stages(tmp_path):
    """F-11 边界：非熔断档之间的正常迁移**不得**冒出「解禁」字样（避免误报）。"""
    eng = _engine(tmp_path)
    eng._history_state["T.SZ"] = (StageCode.STAGE_3_QUIET_WASHOUT, 2)

    _stage, note = eng._apply_state_machine_transition(
        ticker="T.SZ",
        candidate_stage=StageCode.STAGE_1_ACCUMULATION,
        candidate_score=50.0,
        is_transitional=False,
        audit=AntiSpoofingAudit(),
    )
    assert "反向解禁" not in note


def test_f11_circuit_breaker_still_takes_priority(tmp_path):
    """F-11 边界：若本周期仍是高危派发，熔断优先，不得被误判为解禁。"""
    eng = _engine(tmp_path)
    eng._history_state["T.SZ"] = (StageCode.STAGE_7_PASSIVE_DRIFT, 2)

    stage, note = eng._apply_state_machine_transition(
        ticker="T.SZ",
        candidate_stage=StageCode.STAGE_6_DISTRIBUTION,
        candidate_score=75.0,
        is_transitional=False,
        audit=AntiSpoofingAudit(),
    )
    assert stage == StageCode.STAGE_6_DISTRIBUTION
    assert "快速熔断" in note
    assert "反向解禁" not in note


# ───────────────────────────────────────────────── F-10 指令失效机制
def _avoid_playbook(**kw):
    return PlaybookBuilder().build(
        quote={"close": 10.0, "pre_close": 10.0},
        momentum={"support_level": 9.0, "resistance_level": 11.0},
        matched_personas=[],
        action="AVOID",
        **kw,
    )


def test_f10_avoid_from_distribution_carries_reversal_invalidation():
    """F-10：由派发/阴跌切片触发的回避，必须附「信号反转即作废」的失效条件。"""
    pb = _avoid_playbook(fatal_flag=False, main_force_stage="STAGE_6_DISTRIBUTION")
    assert "仅对当日有效" in pb.invalidation_rule
    assert "退出派发区" in pb.invalidation_rule
    # ★ 语义边界：只追加时效描述，**不削弱否决强度**
    assert "一票否决生效" in pb.invalidation_rule
    assert pb.max_position_pct == 0


def test_f10_fatal_flag_veto_has_no_expiry():
    """F-10 边界：财务红旗导致的否决是永久性的，**不得**加时效失效条件。"""
    pb = _avoid_playbook(fatal_flag=True, main_force_stage="STAGE_6_DISTRIBUTION")
    assert "仅对当日有效" not in pb.invalidation_rule
    assert "一票否决生效" in pb.invalidation_rule


def test_f10_avoid_from_normal_stage_has_no_expiry():
    """F-10 边界：非派发档触发的回避，不加反转失效条件。"""
    pb = _avoid_playbook(fatal_flag=False, main_force_stage="STAGE_3_QUIET_WASHOUT")
    assert "仅对当日有效" not in pb.invalidation_rule


def test_f10_reduce_from_distribution_carries_reversal():
    """F-10：「逢反抽清仓」类的减仓指令同样需要失效条件。"""
    pb = PlaybookBuilder().build(
        quote={"close": 20.0, "pre_close": 19.5},
        momentum={"support_level": 19.0, "resistance_level": 22.0},
        matched_personas=[],
        action="REDUCE",
        main_force_stage="STAGE_7_PASSIVE_DRIFT",
    )
    assert "仅对当日有效" in pb.invalidation_rule


def test_f10_suffix_helper_is_pure():
    """F-10：辅助函数对非熔断档返回空串，且常量覆盖两档熔断。"""
    assert reversal_invalidation_suffix("STAGE_6_DISTRIBUTION") != ""
    assert reversal_invalidation_suffix("STAGE_7_PASSIVE_DRIFT") != ""
    assert reversal_invalidation_suffix("STAGE_3_QUIET_WASHOUT") == ""
    assert reversal_invalidation_suffix(None) == ""
    assert DISTRIBUTION_STAGES == ("STAGE_6_DISTRIBUTION", "STAGE_7_PASSIVE_DRIFT")


# ───────────────────────────────────────────────── F-9 信号 TTL
def test_f9_same_day_card_has_no_staleness_note():
    """F-9：当日数据不提示（避免正常场景噪音）。"""
    assert _build_signal_staleness_note(date.today().isoformat()) == ""


def test_f9_one_to_two_days_old_asks_for_recheck():
    """F-9：跨 1~2 日 ⇒ 待复核。"""
    for days in (1, 2):
        note = _build_signal_staleness_note((date.today() - timedelta(days=days)).isoformat())
        assert "信号待复核" in note
        assert f"距今 {days} 天" in note


def test_f9_three_days_or_more_declares_expired():
    """F-9：跨 >= 3 日 ⇒ 已失效，且明确基本面/估值不受影响。"""
    note = _build_signal_staleness_note((date.today() - timedelta(days=5)).isoformat())
    assert "信号已失效" in note
    assert "严禁据此交易" in note
    assert "基本面与估值结论不受影响" in note


def test_f9_unparsable_or_missing_date_is_silent():
    """F-9 边界：日期缺失或不可解析时**不臆断**时效，返回空串。"""
    assert _build_signal_staleness_note(None) == ""
    assert _build_signal_staleness_note("") == ""
    assert _build_signal_staleness_note("not-a-date") == ""


def test_f9_note_appears_in_pillar4_for_stale_card():
    """F-9 端到端：跨日卡片的支柱④首部必须出现时效提示。"""
    runner = JudgmentChainRunner()
    stale = (date.today() - timedelta(days=4)).strftime("%Y%m%d")
    card = runner.run(
        ticker="600838.SH", name="上海九百", trade_date=stale,
        quote={"close": 13.31, "pct_chg": 1.0, "amount": 3.9e8,
               "circ_mv": 53.4e8, "total_mv": 53.4e8, "pe": 25.0},
        momentum={"is_bullish_ma": True}, flags=[], matched_youzi=[], trap_warnings=[],
    )
    assert "信号已失效" in card.get("pillar_4_path", "")
