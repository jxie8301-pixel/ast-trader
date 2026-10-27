"""Tests for data health tracking, interface exception audit, and gap disclosure."""
import pytest
from data.data_health import DataHealthTracker, InterfaceCallRecord
from core.judgment_chain import JudgmentChainRunner
from presentation.html_renderer import render_decision_card_html
from presentation.terminal_view import print_decision_card


def test_data_health_tracker_basic():
    tracker = DataHealthTracker()
    assert not tracker.has_errors
    assert tracker.summary()["total_interfaces"] == 0

    # 1. Success
    tracker.record_success(name="实时行情", channel="TDX", count=1, note="正常返回")
    assert not tracker.has_errors
    assert tracker.summary()["success_count"] == 1

    # 2. Empty
    tracker.record_empty(name="龙虎榜", channel="TDX F10", note="今日无上榜数据")
    assert not tracker.has_errors
    assert tracker.summary()["empty_count"] == 1

    # 3. Failure (严禁 pass，必须捕获)
    try:
        raise ConnectionResetError("TDX 主机主动断开 TCP 链路")
    except Exception as e:
        tracker.record_failure(
            name="股东变动减持计划",
            channel="TDX F10",
            exc=e,
            note="大股东在途减持数据缺失，需降级警示",
        )

    assert tracker.has_errors
    summary = tracker.summary()
    assert summary["total_interfaces"] == 3
    assert summary["success_count"] == 1
    assert summary["empty_count"] == 1
    assert summary["failed_count"] == 1

    failed = summary["failed_details"][0]
    assert failed["name"] == "股东变动减持计划"
    assert failed["error_type"] == "ConnectionResetError"
    assert "TDX 主机主动断开" in failed["error_message"]
    assert "大股东在途减持数据缺失" in failed["note"]


def test_judgment_chain_surfaces_data_gap():
    tracker = DataHealthTracker()
    try:
        raise TimeoutError("F10 股东减持查询超时")
    except Exception as e:
        tracker.record_failure(
            name="股东增减持计划 (F10 share_change_plans)",
            channel="TDX F10",
            exc=e,
            note="减持数据暂无法核验",
        )

    runner = JudgmentChainRunner()
    quote = {
        "code": "000001",
        "close": 15.0,
        "pct_chg": 2.0,
        "total_mv": 100e8,
        "circ_mv": 80e8,
        "pe": 10.0,
        "pb": 1.2,
        "turnover_ratio": 3.0,
    }
    momentum = {"ma5": 14.8, "ma20": 14.2}
    flags = []

    card = runner.run(
        ticker="000001",
        name="平安银行",
        trade_date="20261028",
        quote=quote,
        momentum=momentum,
        flags=flags,
        matched_youzi=[],
        trap_warnings=[],
        data_health=tracker.summary(),
    )

    # 验证 card 中包含了 data_health
    assert "data_health" in card
    assert card["data_health"]["failed_count"] == 1

    # 验证质地五问中管理层问题识别到了减持接口异常
    sub_v = card.get("sub_verdicts_quality", [])
    mgmt_q = next((q for q in sub_v if "管理层" in q["question"]), None)
    assert mgmt_q is not None
    assert "减持计划接口取数异常" in mgmt_q["evidence"]
    assert mgmt_q["judgment"] in ("⚠️", "✗")


def test_html_and_terminal_render_data_health(tmp_path):
    tracker = DataHealthTracker()
    tracker.record_success("实时五档盘口", "TDX L2", count=1)
    tracker.record_empty("龙虎榜席位", "TDX F10", note="今日未上榜")
    try:
        raise RuntimeError("网络超时或被阻断")
    except Exception as e:
        tracker.record_failure("利润表 (F10 lrb)", "eltdx.f10", exc=e, note="降级采用估算数据")

    card = {
        "ticker": "600838",
        "name": "上海九百",
        "price": 10.5,
        "pct_chg": 3.2,
        "decision_gear": "观察",
        "position_cap": 0.2,
        "data_health": tracker.summary(),
    }

    # 1. 终端打印无异常
    print_decision_card(card)

    # 2. HTML 离线报告渲染
    html_file = str(tmp_path / "test_report.html")
    saved = render_decision_card_html(card, output_path=html_file)
    assert saved == html_file

    with open(html_file, "r", encoding="utf-8") as f:
        content = f.read()

    assert "数据接口状态与信息缺口审计" in content
    assert "利润表 (F10 lrb)" in content
    assert "RuntimeError" in content
    assert "网络超时或被阻断" in content
    assert "实时五档盘口" in content
    assert "龙虎榜席位" in content
