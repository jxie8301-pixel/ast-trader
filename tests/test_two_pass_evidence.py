"""Tests for Two-Pass Inquiry & Targeted Evidence Retrieval (链路 2: 审问式验票与定向补证)."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

import config
from core.ai_coprocessor.inquiry import ContradictionInquiry, formulate_inquiries
from core.evidence_retriever import (
    EvidencePackage,
    EvidenceSnippet,
    TargetedEvidenceRetriever,
)
from data.bocha_client import search_bocha
from data.supplement_api import (
    fetch_earnings_forecast,
    fetch_institution_survey,
    fetch_single_stock_news,
)
from lint.validator import LintValidator


# ─────────────────────────────────────────────────────────────
# 1. supplement_api 增量取数函数测试
# ─────────────────────────────────────────────────────────────
def test_fetch_single_stock_news_mocked():
    """测试单只股票专属新闻 JSONP 解析。"""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = 'jQuery({"result":{"cmsArticleWebOld":[{"title":"<em>水晶光电</em>与大客户合作","content":"公司出货量稳定","date":"2026-10-25 10:00:00","mediaName":"证券时报","url":"http://news.com/1"}]}})'

    with patch("requests.get", return_value=mock_resp):
        items = fetch_single_stock_news("002273", limit=5)
        assert len(items) == 1
        assert items[0]["title"] == "水晶光电与大客户合作"
        assert items[0]["media"] == "证券时报"
        assert items[0]["date"] == "2026-10-25 10:00:00"


def test_fetch_institution_survey_mocked():
    """测试机构调研纪要解析。"""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "result": {
            "data": [
                {
                    "SECURITY_CODE": "002273",
                    "NOTICE_DATE": "2026-10-20 00:00:00",
                    "START_DATE": "2026-10-18",
                    "ORGANIZATION_NAME": "中信证券,华泰证券",
                    "ORG_TYPE": "券商",
                    "RECEIVE_PLACE": "公司会议室",
                    "MAIN_CONTENT": "问：越南工厂量产进展如何？答：已顺利实现小批量交付。",
                }
            ]
        }
    }

    with patch("requests.get", return_value=mock_resp):
        surveys = fetch_institution_survey("002273", limit=5)
        assert len(surveys) == 1
        assert surveys[0]["survey_date"] == "2026-10-18"
        assert "顺利实现小批量交付" in surveys[0]["main_content"]


def test_fetch_earnings_forecast_mocked():
    """测试业绩预告解析。"""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "result": {
            "data": [
                {
                    "SECURITY_CODE": "002273",
                    "NOTICE_DATE": "2026-10-14 00:00:00",
                    "REPORT_DATE": "2026-09-30 00:00:00",
                    "PREDICT_TYPE": "预增",
                    "MIN_PROFIT": 8.0e8,
                    "MAX_PROFIT": 9.0e8,
                    "ADD_YPCT": 45.0,
                    "PREDICT_CONTENT": "主要系消费电子旺季订单充足。",
                }
            ]
        }
    }

    with patch("requests.get", return_value=mock_resp):
        forecasts = fetch_earnings_forecast("002273", limit=5)
        assert len(forecasts) == 1
        assert forecasts[0]["predict_type"] == "预增"
        assert forecasts[0]["increase_pct"] == 45.0


# ─────────────────────────────────────────────────────────────
# 2. 博查 AI 搜索客户端测试
# ─────────────────────────────────────────────────────────────
def test_bocha_search_disabled_returns_empty(monkeypatch):
    """当未配置 API Key 时静默返回空，不报错。"""
    monkeypatch.setattr(config, "BOCHA_ENABLED", False)
    monkeypatch.setattr(config, "BOCHA_API_KEY", "")
    res = search_bocha("水晶光电 订单")
    assert res == []


def test_bocha_search_mocked(monkeypatch):
    """当配置 API Key 时正常解析博查响应。"""
    monkeypatch.setattr(config, "BOCHA_ENABLED", True)
    monkeypatch.setattr(config, "BOCHA_API_KEY", "test_key")

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "code": 200,
        "data": {
            "webPages": {
                "value": [
                    {
                        "name": "水晶光电深度报告：微棱镜龙头地位稳固",
                        "url": "https://research.com/report1",
                        "summary": "根据产业链调研，公司在潜望式棱镜中的一供份额超70%。",
                        "dateLastCrawled": "2026-10-15",
                    }
                ]
            }
        }
    }

    with patch("requests.post", return_value=mock_resp):
        res = search_bocha("水晶光电 棱镜份额")
        assert len(res) == 1
        assert "微棱镜龙头" in res[0]["title"]
        assert "70%" in res[0]["snippet"]
        assert res[0]["date"] == "2026-10-15"


# ─────────────────────────────────────────────────────────────
# 3. Pass 1 核心矛盾提审器测试
# ─────────────────────────────────────────────────────────────
def test_formulate_inquiries_rule_fallback():
    """测试规则版矛盾提炼：遇到存贷双高与高PE能精准提炼出证伪问题。"""
    flags = [
        SimpleNamespace(level="🔴", title="【存贷双高】货币资金与短期借款并存", detail="存在大额债务"),
        SimpleNamespace(level="🟠", title="【在建工程异常】长期未转固", detail="金额庞大"),
    ]
    quant_summary = {"pe": 65.0, "reverse_dcf_growth": 35.0}

    inquiries = formulate_inquiries("002273.SZ", "水晶光电", quant_summary, flags)
    assert len(inquiries) >= 2
    cats = {inq.category for inq in inquiries}
    assert "financial_authenticity" in cats
    assert any("存贷双高" in inq.anomaly for inq in inquiries)
    assert any(inq.keywords for inq in inquiries)


# ─────────────────────────────────────────────────────────────
# 4. 针对性定向证据检索器测试
# ─────────────────────────────────────────────────────────────
def test_evidence_retriever_mocked():
    """测试定向证据检索器能把各源证据格式化为带引用标签的切片。"""
    inquiries = [
        ContradictionInquiry(
            id="C1",
            category="financial_authenticity",
            anomaly="存货激增",
            core_question="存货真实性如何？",
            keywords=["存货", "减值"],
            evidence_type="all",
        )
    ]
    retriever = TargetedEvidenceRetriever()

    mock_news = [{"title": "新产线投产", "content": "公司宣布一期正式运转", "date": "2026-10-20", "media": "财联社", "url": "http://cls.cn/1"}]
    mock_surveys = [{"notice_date": "2026-10-18", "org_name": "中金公司", "main_content": "订单饱满"}]
    mock_forecasts = [{"notice_date": "2026-10-15", "predict_type": "预增", "increase_pct": 30.0, "predict_content": "稳步增长"}]

    with patch("core.evidence_retriever.fetch_announcements", return_value=[]), \
         patch("core.evidence_retriever.fetch_single_stock_news", return_value=mock_news), \
         patch("core.evidence_retriever.fetch_institution_survey", return_value=mock_surveys), \
         patch("core.evidence_retriever.fetch_earnings_forecast", return_value=mock_forecasts):

        pkg = retriever.retrieve("002273.SZ", "水晶光电", inquiries)
        assert isinstance(pkg, EvidencePackage)
        assert len(pkg.snippets) >= 3
        prompt_txt = pkg.format_for_prompt()
        assert "【针对核心矛盾检索到的针对性客观证据】" in prompt_txt
        tags = pkg.get_citation_tags()
        assert any("机构调研" in t for t in tags)
        assert any("业绩预告" in t for t in tags)
        assert any("媒体报道" in t for t in tags)


# ─────────────────────────────────────────────────────────────
# 5. Lint R19 证据真实性检验测试
# ─────────────────────────────────────────────────────────────
def test_lint_r19_evidence_citation_check():
    """测试 R19 规则：正文引用的信源标签如果在证据池中存在则放行，否则警告。"""
    validator = LintValidator()

    # 1. 合法引用：引用的标签存在于 evidence_citations 中
    card_ok = {
        "decision_gear": "核心仓",
        "position_cap": 0.20,
        "invalidation_line": "9.50元",
        "evidence_citations": ["[机构调研 2026-10-18 中金公司]", "[业绩预告 2026-10-15 预增]"],
        "pillar_5_decision": {
            "core_contradiction": "针对存货质疑，根据 [机构调研 2026-10-18 中金公司]，订单充足。",
            "action_tactic": "依托均线分批低吸。",
        },
    }
    passed, findings = validator.validate(card_ok, flags=[])
    r19_findings = [f for f in findings if "R19" in f]
    assert len(r19_findings) == 0

    # 2. 伪造或未定标引用：正文引用了不存在的标签
    card_hallucinated = {
        "decision_gear": "核心仓",
        "position_cap": 0.20,
        "invalidation_line": "9.50元",
        "evidence_citations": ["[机构调研 2026-10-18 中金公司]"],
        "pillar_5_decision": {
            "core_contradiction": "根据 [公告 2026-09-01 虚构问询函]，公司并无造假。",
            "action_tactic": "立即买入。",
        },
    }
    passed, findings = validator.validate(card_hallucinated, flags=[])
    r19_findings = [f for f in findings if "R19" in f]
    assert len(r19_findings) == 1
    assert "虚构问询函" in r19_findings[0]
