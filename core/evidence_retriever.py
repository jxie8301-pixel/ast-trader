"""core.evidence_retriever —— 针对性证据检索器（Targeted Evidence Retriever）。

负责根据 Pass 1 提炼的核心矛盾与关键词，向多源信源定向发起针对性补证检索：
1. 本地法定公告与交易所问询函（announcement_corpus + pdf_reader）
2. 机构调研纪要与业绩预告（supplement_api）
3. 单只股票媒体报道（supplement_api）
4. 全网研报与产业供应链搜索（bocha_client，选配）
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Sequence

import config
from core.ai_coprocessor.inquiry import ContradictionInquiry
from data.announcement_corpus import fetch_announcements, select
from data.bocha_client import search_bocha
from data.supplement_api import (
    fetch_earnings_forecast,
    fetch_institution_survey,
    fetch_single_stock_news,
)

logger = logging.getLogger("ast_trader.core.evidence_retriever")


@dataclass
class EvidenceSnippet:
    """一条结构化证据切片。"""

    id: str                               # "S1", "S2", ...
    inquiry_id: str                       # 对应的矛盾编号: "C1", "C2"
    source_type: str                      # "announcement" | "survey" | "forecast" | "news" | "bocha"
    title: str                            # 证据标题
    content: str                          # 引文精粹（一般 80~200 字）
    citation_tag: str                     # 标准引用标签
    url: str = ""                         # 原文链接
    page: int | None = None               # 页码
    date: str = ""                        # 发生日期

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "inquiry_id": self.inquiry_id,
            "source_type": self.source_type,
            "title": self.title,
            "content": self.content,
            "citation_tag": self.citation_tag,
            "url": self.url,
            "page": self.page,
            "date": self.date,
        }


@dataclass
class EvidencePackage:
    """单只股票的证据合集。"""

    ts_code: str
    stock_name: str
    inquiries: list[ContradictionInquiry] = field(default_factory=list)
    snippets: list[EvidenceSnippet] = field(default_factory=list)

    def format_for_prompt(self, max_chars: int = 3000) -> str:
        """为大模型 Pass 2 裁决组装可解释的证据文本。"""
        if not self.snippets:
            return "【定向证据检索结果】: 经检索，未检索到与核心矛盾匹配的针对性客观披露文件（请如实标记未核验）。"

        lines = ["【针对核心矛盾检索到的针对性客观证据】:"]
        for s in self.snippets:
            tag = s.citation_tag
            text = s.content[:250].replace("\n", " ").strip()
            lines.append(f"- 编号 {s.id} (对应 {s.inquiry_id}) | {tag}: “{text}”")

        out = "\n".join(lines)
        if len(out) > max_chars:
            out = out[:max_chars] + "...\n（部分长证据已截断）"
        return out

    def get_citation_tags(self) -> set[str]:
        return {s.citation_tag for s in self.snippets}


class TargetedEvidenceRetriever:
    """定向证据检索编排器。"""

    def __init__(self) -> None:
        pass

    def retrieve(
        self,
        ts_code: str,
        stock_name: str,
        inquiries: Sequence[ContradictionInquiry],
    ) -> EvidencePackage:
        num_code = ts_code.split(".")[0]
        pkg = EvidencePackage(ts_code=ts_code, stock_name=stock_name, inquiries=list(inquiries))
        s_count = 1

        # 1. 本地公告与问询函检索 (announcement_corpus)
        try:
            anns = fetch_announcements(ts_code)
            if anns:
                # 遍历核心矛盾
                for inq in inquiries:
                    # 匹配公告
                    matched = select(
                        anns,
                        categories=("regulatory", "audit", "reduction", "pledge", "guidance"),
                        limit=3,
                    )
                    for a in matched:
                        if s_count > 6:
                            break
                        c_tag = f"[公告 {a.issue_date} {a.title[:20]}]"
                        snippet = EvidenceSnippet(
                            id=f"S{s_count}",
                            inquiry_id=inq.id,
                            source_type="announcement",
                            title=a.title,
                            content=f"公告类型: {a.typename or '法定披露'} | 标题: {a.title}",
                            citation_tag=c_tag,
                            url=a.url,
                            date=a.issue_date,
                        )
                        pkg.snippets.append(snippet)
                        s_count += 1
        except Exception as e:
            logger.warning("检索公告语料异常 (%s): %s", ts_code, e)

        # 2. 机构调研纪要与业绩预告 (supplement_api)
        try:
            surveys = fetch_institution_survey(num_code, limit=3)
            for sv in surveys:
                if s_count > 8:
                    break
                org = sv.get("org_name") or "机构调研"
                dt = sv.get("survey_date") or sv.get("notice_date") or ""
                cont = sv.get("main_content") or ""
                if cont:
                    c_tag = f"[机构调研 {dt} {org[:15]}]"
                    pkg.snippets.append(EvidenceSnippet(
                        id=f"S{s_count}",
                        inquiry_id=inquiries[0].id if inquiries else "C1",
                        source_type="survey",
                        title=f"{dt} 投资者关系活动记录",
                        content=cont[:220],
                        citation_tag=c_tag,
                        date=dt,
                    ))
                    s_count += 1

            forecasts = fetch_earnings_forecast(num_code, limit=2)
            for fc in forecasts:
                if s_count > 10:
                    break
                p_type = fc.get("predict_type") or "业绩展望"
                cont = fc.get("predict_content") or f"预计净利润同比 {fc.get('increase_pct', 0.0):+.1f}%"
                dt = fc.get("notice_date") or ""
                c_tag = f"[业绩预告 {dt} {p_type}]"
                pkg.snippets.append(EvidenceSnippet(
                    id=f"S{s_count}",
                    inquiry_id=inquiries[0].id if inquiries else "C1",
                    source_type="forecast",
                    title=f"{dt} 业绩预告 ({p_type})",
                    content=cont[:220],
                    citation_tag=c_tag,
                    date=dt,
                ))
                s_count += 1
        except Exception as e:
            logger.warning("检索调研与业绩预告异常 (%s): %s", ts_code, e)

        # 3. 单股新闻 (supplement_api)
        try:
            news_items = fetch_single_stock_news(num_code, limit=3)
            for nw in news_items:
                if s_count > 12:
                    break
                t = nw.get("title") or ""
                c = nw.get("content") or ""
                d = nw.get("date") or ""
                m = nw.get("media") or "主流媒体"
                if t:
                    c_tag = f"[媒体报道 {d[:10]} {m[:8]}]"
                    pkg.snippets.append(EvidenceSnippet(
                        id=f"S{s_count}",
                        inquiry_id=inquiries[-1].id if inquiries else "C1",
                        source_type="news",
                        title=t,
                        content=f"{t}。{c[:180]}",
                        citation_tag=c_tag,
                        url=nw.get("url") or "",
                        date=d[:10],
                    ))
                    s_count += 1
        except Exception as e:
            logger.warning("检索个股新闻异常 (%s): %s", ts_code, e)

        # 4. 博查 AI 搜索 (bocha_client，选配)
        if config.BOCHA_ENABLED:
            try:
                for inq in inquiries:
                    if s_count > 15:
                        break
                    query = f"{stock_name} {' '.join(inq.keywords[:2])}"
                    results = search_bocha(query, count=2)
                    for item in results:
                        c_tag = f"[博查研报 {item.get('date', '')} {item['title'][:16]}]"
                        pkg.snippets.append(EvidenceSnippet(
                            id=f"S{s_count}",
                            inquiry_id=inq.id,
                            source_type="bocha",
                            title=item["title"],
                            content=item["snippet"][:220],
                            citation_tag=c_tag,
                            url=item["url"],
                            date=item.get("date", ""),
                        ))
                        s_count += 1
            except Exception as e:
                logger.warning("博查 AI 搜索补证异常: %s", e)

        logger.info(
            "针对性补证检索完成 (%s): 提炼 %d 个矛盾，收集 %d 条针对性证据 (Bocha: %s)",
            ts_code, len(inquiries), len(pkg.snippets), "启用" if config.BOCHA_ENABLED else "未启用",
        )
        return pkg
