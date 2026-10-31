"""Pillar 4 Builder: 主力行为生命周期与路径承载 (结合 Main Force Engine & 微观结构). 显式标识降级."""
from __future__ import annotations

from datetime import date as _date
from typing import Any
import pandas as pd

from core.types import PathVerdict, SingleStockContext


def build_signal_freshness_banner(
    is_micro_degraded: bool, mf_conf: float, is_stale: bool = False
) -> str:
    """时效性声明恒非空。"""
    if is_micro_degraded:
        return "⚠️ 【微观数据降级】高频分时与委托队列数据缺失，防伪审计未核验，风控严禁建仓！\n"
    day_word = "生成日" if is_stale else "当日"
    return (
        f"⏱️ 【信号时效】本判定基于**{day_word}盘中微观切片**（主力阶段/聪明钱成本/筹码分布"
        f"均为日内横截面口径，非跨日沉淀成本），仅对{day_word}有效；"
        f"下一交易日须以新数据重新复核，不得跨日沿用（当前置信度 {mf_conf:.1f}%）\n"
    )


def build_signal_staleness_note(trade_date: str | None) -> str:
    """信号 TTL —— 决断卡数据与当前日期跨日时，微观结论显式降权。"""
    if not trade_date:
        return ""
    today = _date.today()
    try:
        card_date = _date.fromisoformat(str(trade_date)[:10])
    except (TypeError, ValueError):
        return ""
    age_days = (today - card_date).days
    if age_days <= 0:
        return ""
    if age_days >= 3:
        return (
            f"🕒 【信号已失效】本卡基于 {card_date.isoformat()} 数据，距今 {age_days} 天；"
            f"主力阶段/聪明钱成本/筹码分布等微观结论**已过期失效**，"
            f"严禁据此交易，须以最新数据重跑（基本面与估值结论不受影响）\n"
        )
    return (
        f"🕒 【信号待复核】本卡基于 {card_date.isoformat()} 数据，距今 {age_days} 天；"
        f"微观资金面结论为日内切片，跨日后须以最新数据重新确认\n"
    )


def compute_chip_peak_and_divergence(
    daily_df: pd.DataFrame | None,
    price: float,
    smart_vwap: float,
) -> tuple[float | None, float | None, bool]:
    """计算近 20 日筹码密集峰价格、现价距 Smart VWAP 动态乖离率以及是否假突破。"""
    if daily_df is None or not hasattr(daily_df, "empty") or daily_df.empty or len(daily_df) < 5 or price <= 0:
        return None, None, False

    try:
        # 取最近 20 根 K 线
        recent_df = daily_df.tail(20)
        closes = recent_df["close"].astype(float)
        vols = recent_df["vol"].astype(float) if "vol" in recent_df.columns else recent_df["amount"].astype(float)

        min_p = float(closes.min())
        max_p = float(closes.max())
        if max_p <= min_p or min_p <= 0:
            return None, None, False

        # 简单构建 10 个价格箱体的成交量加权直方图寻找密集峰
        bins = 10
        step = (max_p - min_p) / bins
        box_vols = [0.0] * bins
        for c, v in zip(closes, vols):
            idx = min(int((c - min_p) / step), bins - 1)
            box_vols[idx] += v

        max_idx = box_vols.index(max(box_vols))
        chip_peak_price = round(min_p + (max_idx + 0.5) * step, 2)

        vwap_divergence_pct = round(((price - smart_vwap) / smart_vwap) * 100.0, 1) if smart_vwap > 0 else 0.0

        # 假突破判据：现价突破密集峰，但主力知情成本线 Smart VWAP 显著滞后 (>3.0%)
        is_false_breakout = (price > chip_peak_price) and (vwap_divergence_pct > 3.0)
        return chip_peak_price, vwap_divergence_pct, is_false_breakout
    except Exception:
        return None, None, False


def build_pillar_4_path(
    ctx: SingleStockContext,
    price: float,
    overhead_chips: float,
    sotp_ps: float,
    microstructure: dict[str, Any] | None,
    is_fatal: bool,
    trade_date: str | None = None,
    nodes: dict[str, Any] | None = None,
) -> PathVerdict:
    """支柱 ❹: 主力行为生命周期与路径承载 (结合 Main Force Engine & 微观结构). 显式标识降级."""
    micro = microstructure or {}
    is_micro_degraded = bool(micro.get("is_degraded", False))
    mf_stage_code = micro.get("stage_code", "")
    if mf_stage_code == "STAGE_UNVERIFIED":
        is_micro_degraded = True
    mf_stage = micro.get("main_force_stage", "【⏳ 存量震荡/等待方向期】")
    mf_behavior = micro.get("main_force_behavior", "")
    mf_override = micro.get("decision_gear_override")
    mf_cap = micro.get("suggested_pos_cap")
    if is_micro_degraded:
        mf_cap = 0.0
        mf_override = "观察"
    mf_conf = micro.get("main_force_confidence", 80.0 if not is_micro_degraded else 0.0)
    is_trans = micro.get("is_transitional", False)
    anti_spoofing_list = micro.get("anti_spoofing_summary", [])

    smart_q = micro.get("smart_q")
    smart_vwap = micro.get("smart_vwap", price)
    auc_chg = micro.get("auction_open_chg_pct", 0.0)
    auc_amt = micro.get("auction_open_amt_wan", 0.0)

    profit_chip_pct = round(100.0 - overhead_chips, 1)
    depth_to_sotp = round((price - sotp_ps) / price * -100.0, 1) if (price > 0 and sotp_ps > 0) else None
    depth_sotp_str = f"{depth_to_sotp:.1f}%" if depth_to_sotp is not None else "未核验"

    # 计算 20 日筹码密集峰与 Smart VWAP 乖离率
    chip_peak_price, vwap_div_pct, is_false_breakout = compute_chip_peak_and_divergence(
        ctx.daily_df, price, smart_vwap
    )
    if is_false_breakout and not is_micro_degraded:
        # 命中假突破诱多对倒特征：扣减置信度
        mf_conf = max(0.0, mf_conf - 20.0)

    flow_parts = []
    if smart_q is not None and smart_q > 0:
        flow_parts.append(f"聪明钱 Q={smart_q:.3f} (知情成本 {smart_vwap:.2f}元 vs 现价 {price:.2f}元)")
    if auc_amt > 1000:
        flow_parts.append(f"早盘竞价抢筹 {auc_amt:.0f}万元 ({auc_chg:+.2f}%)")
    elif auc_amt > 0:
        flow_parts.append(f"早盘竞价平稳 ({auc_chg:+.2f}%, {auc_amt:.0f}万)")

    if is_micro_degraded:
        path_verdict = "未核验(微观缺失)"
    elif is_fatal or mf_stage_code in ("STAGE_6_DISTRIBUTION", "STAGE_7_PASSIVE_DRIFT"):
        # ★ 20261030 修复 P1-4：移除 overhead_chips >= 55.0 硬触发「高尾险·不可承受」的清仓权。
        #   overhead_chips 仅为 60 日价格量能代理，不可单独作为清仓/一票否决依据；高尾险只保留致命红旗与主力出货/阴跌硬阶段触发。
        path_verdict = "高尾险·不可承受"
    else:
        path_verdict = "可承受"

    if nodes:
        _node = nodes.get("node_path")
        _nv = getattr(_node, "verdict", None) if _node else None
        if _nv and not is_fatal:
            # ★ 20261029 审计 P0-2：原为裸覆写 —— 「高尾险·不可承受」可被 AI 抬成
            #   「可承受」，直接绕过清仓类判据。现走降级单向阀（只能变得更差）。
            #   注意：规则侧「未核验(微观缺失)」不在节点取值域内，阀会直接回退规则。
            from core.ai_coprocessor import apply_verdict_downgrade_only as _apply_verdict
            path_verdict = _apply_verdict(path_verdict, _node, "node_path")

    stale_note = build_signal_staleness_note(trade_date)
    deg_banner = build_signal_freshness_banner(
        is_micro_degraded, mf_conf, is_stale=bool(stale_note)
    )

    # ★ 20261029 审计 P1-4：旧文案写「上方套牢盘 X%」，读者（与下游判据）会以为这是
    #   真实筹码分布。它的真实口径是「60 日量能代理」（见 game_features 的说明），
    #   呈现层必须如实标注口径，绝不能把代理指标说成筹码。
    chip_line = (
        f"  • 筹码沉淀承载 (口径: 60日量能代理, 非真实成本分布): "
        f"获利盘 {profit_chip_pct:.1f}% / 上方套牢量占比 {overhead_chips:.1f}% "
        f"(跌回 SOTP 保守底座左尾深度: {depth_sotp_str})"
    )
    if chip_peak_price is not None:
        chip_line += f"；近20日沉淀密集峰位于 {chip_peak_price:.2f}元"

    pillar_path_summary = (
        f"{deg_banner}"
        f"{stale_note}"
        f"判定: 【{path_verdict}】 (主力阶段: {mf_stage}，置信度 {mf_conf:.1f}%{'，多空过渡区' if is_trans else ''})\n"
        f"  • 微观盘口防伪: {'；'.join(flow_parts) if flow_parts else ('未核验(数据降级)' if is_micro_degraded else '盘口维持常规博弈')}\n"
        f"{chip_line}"
    )
    if is_false_breakout:
        pillar_path_summary += f"\n  • ⚠️ 假突破与对倒警示: 现价突破20日筹码密集峰({chip_peak_price:.2f}元)，但主力成本线({smart_vwap:.2f}元)滞后且乖离率达{vwap_div_pct:+.1f}%，呈现脉冲诱多对倒特征"

    if mf_behavior:
        pillar_path_summary += f"\n  • 操盘透视: {mf_behavior}"
    mf_transition = micro.get("transition_note", "")
    if mf_transition:
        pillar_path_summary += f"\n  • 状态迁移: {mf_transition}"
    if anti_spoofing_list:
        filtered_audits = [a for a in anti_spoofing_list if "未检测到明显反常" not in a and "数据暂缺" not in a]
        if filtered_audits:
            pillar_path_summary += f"\n  • 反伪装穿透: {' | '.join(filtered_audits)}"

    return PathVerdict(
        verdict=path_verdict,
        pillar_text=pillar_path_summary,
        is_micro_degraded=is_micro_degraded,
        mf_stage_code=mf_stage_code,
        mf_stage=mf_stage,
        mf_behavior=mf_behavior,
        mf_override=mf_override,
        mf_cap=mf_cap,
        mf_conf=mf_conf,
        is_trans=is_trans,
        depth_to_sotp=depth_to_sotp,
        profit_chip_pct=profit_chip_pct,
        chip_peak_price=chip_peak_price,
        vwap_divergence_pct=vwap_div_pct,
        is_false_breakout=is_false_breakout,
    )
