"""种子标的分层验证套件。

覆盖目标
--------
用 10 只跨行业、跨市值档位、跨板块、跨财务特征的真实 A 股个股驱动完整分析链路，
验证三件事：

1. **流程走得通**：每只种子都能产出结构完整的决断卡（硬失败）。
2. **风控守得住**：三轮审计沉淀的 fail-closed 契约在真实数据下依然成立（硬失败）。
3. **特征对得上**：系统给出的板块、涨跌停幅度、市值档位与个股真实属性一致（软告警）。

断言为何不做精确值比对
----------------------
本套件实时联网取数，价格、评分、红旗条目逐日变动；对这类数值做硬断言会造成
「每日假红」，反而掩盖真正的回归。因此这里只断言**不变量**，把波动量交给
评估报告做人工判断。

用法
----
::

    pytest tests/test_seed_universe.py -m seednet          # 只跑种子套件
    pytest tests/ -m "not seednet"                          # 无网环境下跳过
"""

from __future__ import annotations

from typing import Any

import pytest

import config
from helpers_seed import (
    assert_risk_contracts,
    assert_structure,
    check_directional,
    collect_evaluation_findings,
    run_seed_analysis,
    write_summary,
)
from seed_universe import SEEDS

pytestmark = pytest.mark.seednet

#: 允许的失败比例上限。实时链路存在抖动与个股停牌，全量要求 100% 成功会假红。
MAX_ERROR_RATE = 0.4

#: 写入摘要时一并冻结的风控阈值，便于评估报告对照「当时生效的规则」
_THRESHOLD_KEYS = (
    "LIQUIDITY_MAIN_MIN_AMOUNT",
    "LIQUIDITY_GEM_MIN_AMOUNT",
    "MOMENTUM_MIN_PCT_CHG",
    "MOMENTUM_MIN_TURNOVER_RATE",
    "MOMENTUM_MAX_TURNOVER_RATE",
    "PLEDGE_FATAL_RATIO",
    "SLOAN_ACCRUAL_FATAL_RATIO",
    "MAX_SINGLE_POSITION",
    "LEFT_TAIL_WARN_THRESHOLD",
)


@pytest.mark.parametrize("spec", list(SEEDS), ids=lambda s: f"{s.code}-{s.industry}")
def test_seed_full_pipeline(
    spec: Any,
    isolated_cli: Any,
    seed_report_dir: Any,
    seed_entries: list[dict[str, Any]],
) -> None:
    """单只种子：跑通全链路 → 校验结构 → 校验风控契约 → 收集方向性告警。"""
    entry, card = run_seed_analysis(spec, seed_report_dir)
    seed_entries.append(entry)

    # 执行失败：记录后判失败，但不影响其余种子继续跑
    if entry["status"] == "ERROR" or card is None:
        pytest.fail(f"{spec.code}({spec.name}) 全链路执行失败: {entry['error']}")

    # 1. 结构完整性（硬失败）
    structural = assert_structure(card)
    entry["structural_violations"] = structural
    assert not structural, f"{spec.code} 结构完整性违约: {structural}"

    # 2. 风控契约（硬失败）——这是三轮审计沉淀的核心不变量
    contracts = assert_risk_contracts(card)
    entry["contract_violations"] = contracts
    assert not contracts, f"{spec.code} 风控契约违约: {contracts}"

    # 3. 方向性特征（软告警，不判失败）
    entry["directional_warnings"] = check_directional(spec, card)
    entry["evaluation_findings"] = collect_evaluation_findings(spec, card)

    # 4. 特征漂移：探针不通过只标记并跳过方向性断言，不变量结果依然有效
    if not spec.probe(card):
        entry["status"] = "SKIPPED"
        entry["drift_note"] = f"特征探针 {spec.probe.__name__} 未通过，方向性结论仅供参考"


def test_seed_batch_summary(
    seed_entries: list[dict[str, Any]],
    seed_run_date: str,
    seed_report_dir: Any,
) -> None:
    """聚合落盘：写出结构化摘要，并按成功率判定整批是否可用。

    必须放在参数化用例之后，依赖 pytest 的文件内顺序执行保证已采集完条目。
    """
    if not seed_entries:
        pytest.skip("未采集到任何种子结果（可能已被 -k 过滤）")

    meta = {
        "run_date": seed_run_date,
        "seed_count": len(seed_entries),
        "active_thresholds": {k: getattr(config, k, None) for k in _THRESHOLD_KEYS},
        "note": "实时联网取数；摘要仅含标量字段，明细见同目录 HTML 研报。",
    }
    out_path = seed_report_dir / f"summary_{seed_run_date}.json"
    write_summary(seed_entries, out_path, meta)
    print(f"\n📄 种子跑批摘要已写入: {out_path}")

    total = len(seed_entries)
    errors = [e for e in seed_entries if e["status"] == "ERROR"]
    ok = [e for e in seed_entries if e["status"] == "OK"]

    # 全部失败通常意味着行情链路不可用，而非系统缺陷 —— 跳过而不是判红
    if not ok:
        pytest.skip(f"行情链路不可用（{total} 只全部执行失败），跳过整批判定")

    error_rate = len(errors) / total
    print(f"✅ 成功 {len(ok)}/{total}；失败 {len(errors)}；失败率 {error_rate:.0%}")
    assert error_rate <= MAX_ERROR_RATE, (
        f"种子跑批失败率 {error_rate:.0%} 超过阈值 {MAX_ERROR_RATE:.0%}: "
        + ", ".join(f"{e['code']}: {e['error']}" for e in errors)
    )
