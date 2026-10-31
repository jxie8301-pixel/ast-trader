"""Unit tests for ReportAuditor and smart natural sentence cutoff."""
from __future__ import annotations

from core.agents.report_auditor import ReportAuditor
from presentation.plain_language import smart_natural_cutoff


def test_smart_natural_cutoff_avoids_truncated_words():
    """测试智能自然断句在标点处完整闭合，避免残句断尾."""
    raw_text = (
        "所有时间窗均锚定『下一份尚未披露的定期报告』= 2026 年年报（报告期 20261231，全年累计口径；本报告已披露的最新期为 2026 三季报）。"
        "逐条可核销：①【经营现金流门槛】若 2026 年报披露的全年经营活动现金流量净额 < 0，触发退出复核。"
        "②【减值门槛】若 2026 年报披露的减值损失合计 ≥ 10 亿元，触发退出复核。"
    )
    # 原先的 [:100] 会切在 "若 2026 年报。" 造成断尾
    # smart_natural_cutoff 必须在第一句的句号处闭合完整
    result = smart_natural_cutoff(raw_text, max_chars=110)
    assert result.endswith("。")
    assert "若 2026 年报。" not in result
    assert "本报告已披露的最新期为 2026 三季报）。" in result


def test_report_auditor_heals_dangling_headers_and_conflicts():
    """测试总编审自动补全空悬标题与消除仓位打架."""
    auditor = ReportAuditor()
    card = {
        "ticker": "002850",
        "name": "科达利",
        "position_cap": 0.0,
        "decision_gear": "观察",
        "main_force_risk": "",  # 模拟悬空字段
        "core_contradiction": "大模型裁定需等证据核销落袋：这是证据已到临界但尚未落袋的形态。加之退出门槛严格。",
        "capital_matrix": {"verdict": "❄️ 资金观望整理态势 (缺乏主导合力，动能尚未聚集，维持中性底仓)"},
        "tactical_odds": {"stop_price": 139.68},
    }
    
    healed = auditor.audit_and_heal_report(card)
    
    assert healed["chief_auditor_passed"] is True
    assert healed["main_force_risk"] != ""
    assert "139.68" in healed["main_force_risk"]
    assert "维持中性底仓" not in healed["capital_matrix"]["verdict"]
    assert "保持空仓防御，严禁底仓开仓" in healed["capital_matrix"]["verdict"]
