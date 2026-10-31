"""announcement_corpus —— 公告语料池：筛选 → 下载 → 抽文本 → 产出**带页码**的引用。

为什么要有这一层
----------------
`f10.announcements` 给的是**公告目录**（title / issue_date / url），
正文是 PDF。没有这一层，系统就只能拿标题做字符匹配 —— 这正是用户指出的
「模块四 审计监管文本挖掘」当前最大的盲区：交易所问询函、非标审计意见
这些**最硬的排雷信号**全在 PDF 正文里，目录里只有一句标题。

设计纪律
--------
1. **失败即声明缺失**（NFR-02）：取不到 / 下不动 / 抽不出文本，一律记进
   `data.degraded`，返回空语料，**绝不编造文本或编造页码**。
2. **精准取，不贪多**：按公告类型关键词筛，只下真正需要的几份
   （问询函回复、审计说明通常只有几页），避免 200 页年报拖垮延迟与上下文。
3. **每份都带 url 与页码**，使下游（AI 结论 / 报告）可逐条核验。

数据源：eltdx `f10.announcements`（`CWSearch.tzx_rcache`），
字段 `rec_id` / `title` / `issue_date` / `url` / `typename`。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Sequence

import config

from . import degraded, pdf_reader
from .eltdx_client import EltdxError, code6, open_client
from .pdf_reader import Hit, PdfDoc

__all__ = [
    "Announcement", "CorpusDoc", "Corpus",
    "CATEGORY_KEYWORDS", "fetch_announcements", "classify", "select",
    "build_corpus", "CACHE_DIR",
]

CACHE_DIR: Path = config.CACHE_DIR / "announcements"

#: 公告类别 → 命中关键词。命中即归入该类别（一份公告可同时属于多类）。
#: 关键词来自 eltdx 公告 `typename` 与 `title` 的实际取值（已实测存在
#: 「收到监管部门函件及回复」「年度审计报告」等类型）。
CATEGORY_KEYWORDS: dict[str, tuple[str, ...]] = {
    "regulatory": ("问询", "关注函", "监管", "立案", "处罚", "警示", "整改", "自律监管"),
    "audit": ("审计", "非标", "保留意见", "无法表示意见", "强调事项", "内部控制"),
    "reduction": ("减持", "股份减持", "拟减持"),
    "pledge": ("质押", "解除质押"),
    "restructure": ("重组", "重大资产", "购买资产", "发行股份", "资产置换", "收购", "要约"),
    "guidance": ("业绩预告", "业绩快报", "业绩预增", "业绩预减"),
    "holding_change": ("权益变动", "控制权", "增持"),
}


@dataclass
class Announcement:
    """一条公告目录条目。"""

    rec_id: str = ""
    title: str = ""
    issue_date: str = ""
    url: str = ""
    typename: str = ""
    categories: tuple[str, ...] = ()

    @property
    def key(self) -> str:
        """稳定的去重键：优先 rec_id，回落到 url。"""
        return self.rec_id or self.url or self.title


@dataclass
class CorpusDoc:
    """一份已抽取的公告语料。"""

    ann: Announcement
    doc: PdfDoc
    sections: dict[str, Any] = field(default_factory=dict)
    hits: list[Hit] = field(default_factory=list)
    error: str = ""

    @property
    def ok(self) -> bool:
        return not self.error and self.doc.ok

    def citation(self, hit_index: int = 0) -> dict[str, Any] | None:
        """把一次关键词命中转成证据引用（可直接喂给 `EvidenceRef`）。"""
        if hit_index >= len(self.hits):
            return None
        h = self.hits[hit_index]
        return {
            "source": "announcement",
            "url": self.ann.url,
            "page": h.page,
            "quote": h.snippet,
            "title": self.ann.title,
            "issue_date": self.ann.issue_date,
        }


@dataclass
class Corpus:
    """一只股票的公告语料集合。"""

    code: str
    docs: list[CorpusDoc] = field(default_factory=list)
    total_announcements: int = 0
    selected: int = 0

    @property
    def ok_docs(self) -> list[CorpusDoc]:
        return [d for d in self.docs if d.ok]

    def citations(self, limit: int = 20) -> list[dict[str, Any]]:
        """汇总全部证据引用（按文档顺序，每文档取前若干条）。"""
        out: list[dict[str, Any]] = []
        for d in self.ok_docs:
            for i in range(len(d.hits)):
                c = d.citation(i)
                if c:
                    out.append(c)
                if len(out) >= limit:
                    return out
        return out


def _rows_of(resp: Any) -> list[dict[str, Any]]:
    """从 F10Response 取行。不同 SDK 版本字段位置不同，此处只认 `rows`。"""
    rows = getattr(resp, "rows", None)
    return list(rows) if rows else []


def fetch_announcements(code: str) -> list[Announcement]:
    """拉取公告目录。失败返回空列表并登记缺失原因（NFR-02）。"""
    try:
        with open_client() as c:
            resp = c.f10.announcements(code6(code))
    except EltdxError as exc:
        degraded.missing(f"announcements[{code}]", f"eltdx 取数失败: {type(exc).__name__}: {exc}")
        return []
    except Exception as exc:                                # noqa: BLE001
        degraded.missing(f"announcements[{code}]", f"未知失败: {type(exc).__name__}: {exc}")
        return []

    rows = _rows_of(resp)
    if not rows:
        degraded.missing(f"announcements[{code}]", "接口返回空表（该标的无公告或接口未提供）")
        return []

    out: list[Announcement] = []
    for r in rows:
        title = str(r.get("title") or "")
        typename = str(r.get("typename") or r.get("type") or "")
        ann = Announcement(
            rec_id=str(r.get("rec_id") or ""),
            title=title,
            issue_date=str(r.get("issue_date") or ""),
            url=str(r.get("url") or ""),
            typename=typename,
        )
        ann.categories = classify(ann)
        out.append(ann)
    return out


def classify(ann: Announcement) -> tuple[str, ...]:
    """按标题与类型名判定公告所属类别。"""
    blob = f"{ann.title} {ann.typename}"
    return tuple(
        cat for cat, kws in CATEGORY_KEYWORDS.items()
        if any(k in blob for k in kws)
    )


def select(
    anns: Sequence[Announcement],
    categories: Sequence[str] = ("regulatory", "audit", "reduction", "restructure"),
    *,
    limit: int = 6,
    per_category: int = 3,
) -> list[Announcement]:
    """按类别挑选公告，**每类限流**以免某个类别（如"其他重大事项"）挤满名额。

    同一份公告可能属于多个类别，用 `key` 去重，保留首次出现序。
    """
    buckets: dict[str, list[Announcement]] = {c: [] for c in categories}
    for a in anns:
        for cat in a.categories:
            if cat in buckets and len(buckets[cat]) < per_category:
                buckets[cat].append(a)

    seen: set[str] = set()
    out: list[Announcement] = []
    for cat in categories:
        for a in buckets[cat]:
            if a.key in seen:
                continue
            seen.add(a.key)
            out.append(a)
            if len(out) >= limit:
                return out
    return out


def _download(url: str, cache_dir: Path, key: str) -> Path | None:
    """下载 PDF 到缓存目录；已存在直接复用。失败返回 None 并登记原因。"""
    if not url:
        return None
    cache_dir.mkdir(parents=True, exist_ok=True)
    dest = cache_dir / f"{key}.pdf"
    if dest.is_file() and dest.stat().st_size > 0:
        return dest
    try:
        import requests

        r = requests.get(url, timeout=config.ANNOUNCEMENT_TIMEOUT)
        if r.status_code != 200:
            degraded.missing(f"pdf[{url}]", f"下载失败 HTTP {r.status_code}")
            return None
        if not r.content:
            degraded.missing(f"pdf[{url}]", "下载内容为空")
            return None
        dest.write_bytes(r.content)
        return dest
    except Exception as exc:                                # noqa: BLE001
        degraded.missing(f"pdf[{url}]", f"下载异常: {type(exc).__name__}: {exc}")
        return None


def build_corpus(
    code: str,
    *,
    categories: Sequence[str] = ("regulatory", "audit", "reduction", "restructure"),
    limit: int = 6,
    max_hits_per_doc: int = 30,
    cache_dir: Path | None = None,
    with_pdf: bool = True,
) -> Corpus:
    """构建公告语料池。

    with_pdf=False 时只返回目录级语料（不联网下 PDF），
    供离线测试与「只要标题序列」的场景使用。
    """
    cache = Path(cache_dir) if cache_dir else CACHE_DIR
    anns = fetch_announcements(code)
    corpus = Corpus(code=code, total_announcements=len(anns))
    if not anns:
        return corpus

    picked = select(anns, categories, limit=limit)
    corpus.selected = len(picked)

    for ann in picked:
        if not with_pdf:
            corpus.docs.append(CorpusDoc(ann=ann, doc=PdfDoc(source=ann.url),
                                         error="未启用 PDF 下载"))
            continue

        path = _download(ann.url, cache, f"{code6(code)}_{ann.key}")
        if path is None:
            corpus.docs.append(CorpusDoc(ann=ann, doc=PdfDoc(source=ann.url),
                                         error="PDF 下载失败"))
            continue

        doc = pdf_reader.read_pdf(path)
        if not doc.ok:
            corpus.docs.append(CorpusDoc(ann=ann, doc=doc, error=doc.error or "PDF 解析失败"))
            continue
        if doc.empty:
            corpus.docs.append(CorpusDoc(ann=ann, doc=doc, error="PDF 无可抽取文本（扫描件？）"))
            continue

        # 关键词检索：用该公告所属类别的关键词定位正文段落，避免全量投喂
        keywords: list[str] = []
        for cat in ann.categories:
            keywords.extend(CATEGORY_KEYWORDS.get(cat, ()))
        hits: list[Hit] = []
        seen_lines: set[tuple[int, int]] = set()
        for kw in keywords:
            for h in pdf_reader.search_text(doc, kw, max_hits=max_hits_per_doc):
                if (h.page, h.line_no) in seen_lines:
                    continue
                seen_lines.add((h.page, h.line_no))
                hits.append(h)
        hits.sort(key=lambda h: (h.page, h.line_no))

        corpus.docs.append(CorpusDoc(ann=ann, doc=doc, hits=hits[:max_hits_per_doc]))
    return corpus
