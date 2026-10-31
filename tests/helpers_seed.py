"""种子跑批的执行器、不变量断言与摘要采集。

设计要点
--------
* **副作用隔离**：`MainForceStateEngine` 会把跨日状态写进
  ``config.CACHE_DIR/mainforce_history_state.json``。跑批若复用该路径，
  测试态会污染次日真实分析，因此 :func:`isolate_state_cache` 把状态机缓存
  重定向到临时目录（只重定向状态机，**不动** ``config.CACHE_DIR``，
  避免把财报 zip 缓存一起搬走触发重下载）。
* **不变量而非快照**：所有断言只针对结构完整性与风控契约，
  不对价格、评分等日变数值做精确断言。
* **单只失败不中断**：实时链路存在抖动，逐只捕获并继续，最终按成功率汇总。
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import config
from core.main_force_engine import MainForceStateEngine
from core.microstructure import MicrostructureAnalyzer
from core.red_flags import LEVEL_FATAL

from seed_universe import board_of, cap_tier_of, tier_distance

#: 决断卡必须存在的顶层字段
REQUIRED_CARD_KEYS: tuple[str, ...] = (
    "ticker",
    "name",
    "price",
    "decision_gear",
    "position_cap",
    "invalidation_line",
    "quality_verdict",
    "state_verdict",
    "odds_verdict",
    "path_verdict",
    "pillar_1_quality",
    "pillar_2_state",
    "pillar_3_odds",
    "pillar_4_path",
    "pillar_5_decision",
    "lint_ok",
)

#: 允许出现在 position_cap 的合法区间
_POS_CAP_MIN, _POS_CAP_MAX = 0.0, 1.0

_LIMIT_RE = re.compile(r"(\d+(?:\.\d+)?)\s*%涨跌停")


# ─────────────────────────────────────────────────────────────────────────────
# 副作用隔离
# ─────────────────────────────────────────────────────────────────────────────


def isolate_state_cache(monkeypatch: Any, cli_module: Any, tmp_path: Path) -> Path:
    """把状态机持久化文件重定向到临时目录，返回临时缓存路径。

    仅替换 ``cli`` 模块中的 ``MicrostructureAnalyzer``，使其构造时注入
    带临时 ``cache_file`` 的引擎，从而不触碰生产的
    ``.cache/mainforce_history_state.json``。
    """
    tmp_file = Path(tmp_path) / "mainforce_history_state.json"

    def _factory() -> MicrostructureAnalyzer:
        engine = MainForceStateEngine(cache_file=tmp_file)
        return MicrostructureAnalyzer(engine=engine)

    monkeypatch.setattr(cli_module, "MicrostructureAnalyzer", _factory)
    return tmp_file


# ─────────────────────────────────────────────────────────────────────────────
# 单只执行
# ─────────────────────────────────────────────────────────────────────────────


def run_seed_analysis(spec: Any, report_dir: Path) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """执行单只种子的全链路分析，返回 ``(摘要条目, 决断卡)``。

    永不抛出：任何异常都被捕获并记录在 ``error`` 字段，保证整批不中断；
    失败时决断卡为 ``None``。
    """
    import cli

    html_path = report_dir / f"{spec.code}_{spec.name.replace('*', '')}.html"
    entry: dict[str, Any] = {
        "code": spec.code,
        "expected_name": spec.name,
        "status": "OK",
        "error": None,
        "html_path": None,
    }
    try:
        card = cli.analyze_ticker(spec.code, html_output=str(html_path))
    except Exception as exc:  # noqa: BLE001 - 跑批必须容错
        entry["status"] = "ERROR"
        entry["error"] = f"{type(exc).__name__}: {exc}"
        return entry, None

    if not card:
        entry["status"] = "ERROR"
        entry["error"] = "analyze_ticker 返回 None（行情不可得或代码非法）"
        return entry, None

    entry["html_path"] = str(html_path) if html_path.exists() else None
    entry.update(extract_summary(spec, card))
    return entry, card


# ─────────────────────────────────────────────────────────────────────────────
# 摘要采集（只留标量，控制产物体积）
# ─────────────────────────────────────────────────────────────────────────────


def _limit_pct_of(board_name: str | None) -> float | None:
    if not board_name:
        return None
    m = _LIMIT_RE.search(board_name)
    return float(m.group(1)) if m else None


def extract_summary(spec: Any, card: dict[str, Any]) -> dict[str, Any]:
    """从决断卡抽取评估所需的关键标量。"""
    micro = card.get("microstructure") or {}
    p5 = card.get("pillar_5_decision") or {}
    flags = card.get("all_flags") or []
    fatal = [f for f in flags if f.get("level") == LEVEL_FATAL]
    health = card.get("data_health") or {}

    total_mv = card.get("total_mv")
    actual_board = board_of(spec.code)

    return {
        "actual_name": card.get("name"),
        "board_expected": spec.board,
        "board_actual": actual_board,
        "board_name_in_card": card.get("board_name"),
        "limit_pct_expected": spec.expect.get("limit_pct"),
        "limit_pct_actual": _limit_pct_of(card.get("board_name")),
        "cap_tier_expected": spec.cap_tier,
        "cap_tier_actual": cap_tier_of(total_mv),
        "total_mv_yi": round(total_mv / 1e8, 1) if total_mv else None,
        "pe": card.get("pe"),
        "decision_gear": card.get("decision_gear"),
        "decision_title": card.get("decision_title"),
        "position_cap": card.get("position_cap"),
        "triad_verdict": p5.get("triad_verdict"),
        "three_part_conclusion": p5.get("three_part_conclusion"),
        "quality_verdict": card.get("quality_verdict"),
        "state_verdict": card.get("state_verdict"),
        "odds_verdict": card.get("odds_verdict"),
        "path_verdict": card.get("path_verdict"),
        "flags_total": len(flags),
        "flags_fatal": len(fatal),
        "flag_titles": [f.get("title") for f in flags][:12],
        "lint_ok": card.get("lint_ok"),
        "lint_findings": card.get("lint_findings") or [],
        "micro_degraded": bool(micro.get("is_degraded", False))
        or micro.get("stage_code") == "STAGE_UNVERIFIED",
        "main_force_stage": card.get("main_force_stage"),
        "derivation_present": card.get("derivation") is not None,
        "anchor_present": card.get("anchor_range") is not None,
        "data_health_failed": list(health.get("failed") or [])[:12],
        "data_health_degraded": list(health.get("degraded") or [])[:12],
    }


# ─────────────────────────────────────────────────────────────────────────────
# 不变量断言
# ─────────────────────────────────────────────────────────────────────────────


def assert_structure(card: dict[str, Any]) -> list[str]:
    """结构完整性：缺字段、越界、父子结构不一致。"""
    v: list[str] = []
    for k in REQUIRED_CARD_KEYS:
        if k not in card:
            v.append(f"缺少关键字段 {k}")

    cap = card.get("position_cap")
    if cap is None:
        v.append("position_cap 为 None")
    elif not (_POS_CAP_MIN <= float(cap) <= _POS_CAP_MAX):
        v.append(f"position_cap={cap} 越出合法区间 [{_POS_CAP_MIN}, {_POS_CAP_MAX}]")

    if not card.get("invalidation_line"):
        v.append("invalidation_line 缺失（强制证伪线是强制字段）")

    p5 = card.get("pillar_5_decision") or {}
    for k in ("decision_gear", "position_cap"):
        if k in p5 and k in card and p5[k] != card[k]:
            v.append(f"pillar_5_decision.{k}={p5[k]!r} 与顶层 {k}={card[k]!r} 不一致")

    if not p5.get("three_part_conclusion"):
        v.append("pillar_5_decision.three_part_conclusion 缺失")
    return v


def assert_risk_contracts(card: dict[str, Any]) -> list[str]:
    """风控契约：三轮审计沉淀下来的 fail-closed 不变量，必须锁死。"""
    v: list[str] = []
    flags = card.get("all_flags") or []
    fatal = [f for f in flags if f.get("level") == LEVEL_FATAL]
    gear = card.get("decision_gear")
    cap = card.get("position_cap")

    # 契约 1：存在致命红旗 → 必须回避且零仓
    if fatal:
        if gear != "回避":
            v.append(f"存在 {len(fatal)} 条致命红旗，但档位为 {gear!r}（应为 回避）")
        if cap:
            v.append(f"存在致命红旗，但 position_cap={cap}（应为 0.0）")

    # 契约 2：Lint 未通过 → 必须降级并清零
    if card.get("lint_ok") is False:
        if cap:
            v.append(f"Lint 未通过，但 position_cap={cap}（应为 0.0）")
        if gear not in ("回避", "等证据临界(观察)"):
            v.append(f"Lint 未通过，但档位为 {gear!r}（应为 回避/等证据临界(观察)）")

    # 契约 3：净利润未核验（缺失 或 为负）→ 不得产生估值锚
    if str(card.get("odds_verdict") or "").startswith("未核验"):
        if card.get("derivation") is not None:
            v.append(f"净利润未核验({card.get('odds_verdict')})，却仍生成了 derivation 估值对象")
        if card.get("anchor_range") is not None:
            v.append(f"净利润未核验({card.get('odds_verdict')})，却仍生成了 anchor_range 价格锚")
        if cap:
            v.append(f"净利润未核验({card.get('odds_verdict')})，但 position_cap={cap}（应为 0.0）")

    # 契约 4：微观降级 → 不得给出仓位
    micro = card.get("microstructure") or {}
    degraded = bool(micro.get("is_degraded", False)) or micro.get("stage_code") == "STAGE_UNVERIFIED"
    if degraded and cap:
        v.append(f"微观数据降级，但 position_cap={cap}（应为 0.0）")

    # 契约 5：三分结论与仓位自洽
    concl = (card.get("pillar_5_decision") or {}).get("three_part_conclusion") or ""
    if cap and "好下注? 【是】" not in concl:
        v.append(f"position_cap={cap} > 0，但三分结论未标记 好下注? 【是】")
    elif not cap and "好下注? 【否】" not in concl:
        v.append(f"position_cap={cap} == 0，但三分结论未标记 好下注? 【否】")
    return v


def check_directional(spec: Any, card: dict[str, Any]) -> list[str]:
    """方向性特征：只收集告警，不判定失败。行业特征漂移不应让套件变红。"""
    w: list[str] = []
    actual_board = board_of(spec.code)
    if spec.board != actual_board:
        w.append(f"板块预期 {spec.board} 实际 {actual_board}")

    exp_pct = spec.expect.get("limit_pct")
    act_pct = _limit_pct_of(card.get("board_name"))
    if exp_pct is not None and act_pct is not None and abs(exp_pct - act_pct) > 1e-6:
        w.append(f"涨跌停幅度预期 {exp_pct}% 实际 {act_pct}%")

    dist = tier_distance(spec.cap_tier, cap_tier_of(card.get("total_mv")))
    if dist is not None and dist > 1:
        w.append(f"市值档位预期 {spec.cap_tier} 实际 {cap_tier_of(card.get('total_mv'))}（相差 {dist} 档）")

    if "ST" in spec.risk_tags and "ST" not in str(card.get("name") or "").upper():
        w.append("风险标签声明 ST，但证券名称不含 ST（可能已摘帽）")
    return w


def collect_evaluation_findings(spec: Any, card: dict[str, Any]) -> dict[str, Any]:
    """采集供评估报告使用的**事实**（非好坏判断），例如亏损股是否仍被估值。"""
    flags = card.get("all_flags") or []
    titles = " ".join(str(f.get("title") or "") for f in flags)
    return {
        # P0-2: 亏损股是否仍在产出估值对象（修复后应恒为 False）
        "valuation_from_negative_ni": (
            "亏损" in spec.risk_tags and card.get("derivation") is not None
        ),
        "negative_ni_verdict": (
            card.get("odds_verdict") == "未核验(净利润为负)" if "亏损" in spec.risk_tags else None
        ),
        "st_without_fatal_flag": (
            "ST" in spec.risk_tags
            and not any(f.get("level") == LEVEL_FATAL for f in flags)
        ),
        "high_pe_verdict": (card.get("odds_verdict") if "高估值" in spec.risk_tags else None),
        # P0-3: 质押未核验必须显式留痕；违规处罚记录是否命中
        "pledge_unverified_flag": "质押比例未核验" in titles,
        "governance_violation_flag": "监管违规处理记录" in titles or "违规处罚密集" in titles,
        # P0-4: 制造业校准模型是否对金融业主动弃权
        "model_abstention_flag": "主动弃权" in titles,
        # P0-1: 质地判定与三分结论是否自洽
        "quality_conclusion_consistent": (
            ("好公司? 【是】" in (card.get("pillar_5_decision") or {}).get("three_part_conclusion", ""))
            == (str(card.get("quality_verdict")) in ("好", "部分好"))
        ),
    }


# ─────────────────────────────────────────────────────────────────────────────
# 产物落盘
# ─────────────────────────────────────────────────────────────────────────────


def report_dir_for(date_str: str) -> Path:
    """返回 ``reports/seed_validation/<date>`` 并确保存在。"""
    d = Path(config.BASE_DIR) / "reports" / "seed_validation" / date_str
    d.mkdir(parents=True, exist_ok=True)
    return d


def write_summary(entries: list[dict[str, Any]], out_path: Path, meta: dict[str, Any]) -> None:
    """把整批摘要写成 JSON，供评估阶段读取。"""
    payload = {
        "meta": meta,
        "entries": entries,
        "stats": {
            "total": len(entries),
            "ok": sum(1 for e in entries if e["status"] == "OK"),
            "skipped": sum(1 for e in entries if e["status"] == "SKIPPED"),
            "error": sum(1 for e in entries if e["status"] == "ERROR"),
            "contract_violations": sum(len(e.get("contract_violations") or []) for e in entries),
            "structural_violations": sum(len(e.get("structural_violations") or []) for e in entries),
        },
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def today_str() -> str:
    return datetime.now().strftime("%Y%m%d")
