"""证据层回归：PDF 页码定位、section 抽取、截断标注、公告分类。

对应计划 P3。核心是锁死三件事：
1. **页码必须真实可换算** —— 没有页码就没有"可引用证据"。
2. **截断必须显式标注** —— 上游静默截断 8000 字的缺陷不得复发。
3. **解析失败必须暴露** —— 加密/空文本不能被当成"没有这个内容"。

PDF 解析函数全部以 `PdfDoc.pages`（字符串列表）为输入，
因此本文件**完全离线确定**，不需要真实 PDF 文件。
"""
from __future__ import annotations

import pytest

from data import pdf_reader
from data.announcement_corpus import Announcement, classify, select


# ---------------------------------------------------------------- 页码
def test_locate_page_from_markers():
    doc = pdf_reader.from_pages(["第一页内容", "第二页内容", "第三页内容"])
    full = pdf_reader._build_full(doc.pages)
    assert pdf_reader.locate_page(full, 0) == 1
    pos_page3 = full.index("第三页内容")
    assert pdf_reader.locate_page(full, pos_page3) == 3
    assert pdf_reader.locate_page(full, -1) is None


def test_locate_page_matches_each_page_start():
    doc = pdf_reader.from_pages([f"P{i}" for i in range(1, 21)])
    full = pdf_reader._build_full(doc.pages)
    for i in range(1, 21):
        assert pdf_reader.locate_page(full, full.index(f"P{i}")) == i


# ---------------------------------------------------------------- section
def _annual_report_pages() -> list[str]:
    """构造一份"有目录 + 有正文"的年报页文本。"""
    return [
        "目录\n第一节 释义 ......... 2\n第三节 管理层讨论与分析 ......... 10",
        "第二节 公司简介",
        "第三节 管理层讨论与分析\n一、报告期内公司所处行业情况\n营收同比增长 12%，毛利率 31%",
        "第四节 公司治理\n董事会运作规范",
    ]


def test_section_prefers_body_over_toc():
    """目录页在正文之前 —— 只取首个 match 会误判成「只命中目录」。"""
    doc = pdf_reader.from_pages(_annual_report_pages())
    sec = pdf_reader.find_sections(doc, names=["mda"])["mda"]
    assert sec.found is True, sec.note
    assert sec.kind == "body"
    assert sec.start_page == 3, "正文在第 3 页，不是目录所在的第 1 页"


def test_section_reports_missing_when_absent():
    doc = pdf_reader.from_pages(["第一节 释义", "第二节 公司简介"])
    sec = pdf_reader.find_sections(doc, names=["mda"])["mda"]
    assert sec.found is False and sec.kind == "missing"
    assert sec.text == ""


def test_section_marks_toc_only():
    """只有目录、没有正文时，必须诚实标注 kind=toc，而不是假装 found。"""
    doc = pdf_reader.from_pages(["目录\n第三节 管理层讨论与分析 ......... 10"])
    sec = pdf_reader.find_sections(doc, names=["mda"])["mda"]
    assert sec.found is False
    assert sec.kind == "toc"


def test_section_text_strips_page_markers():
    doc = pdf_reader.from_pages(_annual_report_pages())
    sec = pdf_reader.find_sections(doc, names=["mda"])["mda"]
    assert "__PAGE_" not in sec.text
    assert "营收同比增长" in sec.text


def test_truncation_is_flagged_and_annotated():
    """★ 上游静默截断的缺陷不得复发：必须同时有标志与文本标注。"""
    long_body = "管理层讨论与分析\n" + "业务描述。" * 3000
    doc = pdf_reader.from_pages(["第一节 释义", long_body, "第四节 公司治理"])
    sec = pdf_reader.find_sections(doc, names=["mda"], max_chars=1000)["mda"]
    assert sec.truncated is True
    assert pdf_reader.TRUNCATION_NOTE in sec.text
    assert sec.chars <= 1000 + len(pdf_reader.TRUNCATION_NOTE) + 2


def test_no_truncation_under_limit():
    doc = pdf_reader.from_pages(_annual_report_pages())
    sec = pdf_reader.find_sections(doc, names=["mda"], max_chars=8000)["mda"]
    assert sec.truncated is False
    assert pdf_reader.TRUNCATION_NOTE not in sec.text


def test_end_anchor_stops_at_next_section():
    doc = pdf_reader.from_pages(_annual_report_pages())
    sec = pdf_reader.find_sections(doc, names=["mda"])["mda"]
    assert "董事会运作规范" not in sec.text


# ---------------------------------------------------------------- 检索
def test_search_text_returns_page_numbers():
    doc = pdf_reader.from_pages(["无相关内容", "本期营业收入下降", "再次提到营业收入"])
    hits = pdf_reader.search_text(doc, "营业收入")
    assert [h.page for h in hits] == [2, 3]
    assert all(h.snippet for h in hits)


def test_search_text_respects_max_hits():
    doc = pdf_reader.from_pages(["质押"] * 10)
    assert len(pdf_reader.search_text(doc, "质押", max_hits=4)) == 4


def test_search_text_treats_pattern_as_regex():
    doc = pdf_reader.from_pages(["质押 85%", "质押 12%"])
    hits = pdf_reader.search_text(doc, r"质押\s*\d+%")
    assert len(hits) == 2


# ---------------------------------------------------------------- PdfDoc 状态
def test_pdfdoc_empty_distinguished_from_missing():
    """扫描件：页面存在但无文字 —— 必须能被识别，不能被当成「没有这节内容」。"""
    doc = pdf_reader.from_pages(["", "   ", ""])
    assert doc.pages and doc.empty is True


def test_read_pdf_missing_file_reports_error():
    doc = pdf_reader.read_pdf("__nonexistent__.pdf")
    assert doc.error and not doc.ok


def test_read_pdf_non_pdf_reports_error(tmp_path):
    bad = tmp_path / "bad.pdf"
    bad.write_text("not a pdf at all", encoding="utf-8")
    doc = pdf_reader.read_pdf(bad)
    assert doc.error and not doc.ok


# ---------------------------------------------------------------- 公告分类
@pytest.mark.parametrize(
    "title,typename,expected",
    [
        ("关于回复上海证券交易所重大资产重组草案信息披露问询函的公告", "收到监管部门函件及回复", "regulatory"),
        ("2025年度审计报告", "年报", "audit"),
        ("关于控股股东股份减持计划的预披露公告", "其他重大事项", "reduction"),
        ("关于控股股东部分股份质押的公告", "其他重大事项", "pledge"),
        ("发行股份购买资产暨关联交易报告书", "其他重大事项", "restructure"),
    ],
)
def test_classify_real_titles(title, typename, expected):
    assert expected in classify(Announcement(title=title, typename=typename))


def test_classify_returns_empty_for_irrelevant():
    assert classify(Announcement(title="关于召开2025年年度股东大会的通知", typename="股东大会决议")) == ()


def test_select_limits_per_category_and_dedupes():
    anns = [
        Announcement(rec_id=f"r{i}", title=f"监管函{i}", categories=("regulatory",))
        for i in range(10)
    ] + [Announcement(rec_id="x", title="年报审计报告", categories=("audit",))]
    picked = select(anns, ("regulatory", "audit"), limit=6, per_category=3)
    assert len(picked) == 4                       # regulatory 限 3 + audit 1
    assert sum(1 for a in picked if "regulatory" in a.categories) == 3


def test_select_dedupes_multi_category_announcement():
    ann = Announcement(rec_id="same", title="问询函回复", categories=("regulatory", "restructure"))
    picked = select([ann], ("regulatory", "restructure"), limit=5)
    assert len(picked) == 1
