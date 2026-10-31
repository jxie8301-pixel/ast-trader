"""pdf_reader —— 公告 / 年报 PDF 精读，产出**带物理页码**的可引用语料。

借鉴上游 `scripts/pdf_reader.py` 的核心手法：
· 逐页抽文本后在全文里插 `__PAGE_N__` 标记（`_build_full`）；
· 用「start 正则 + end 正则列表」的双锚点定位 section（`SECTION_PATTERNS`）；
· 用**点号引导**识别目录条目，避免把目录行当成正文（`_TOC_LEADER`）。

**修正上游的三处缺陷（这是本次移植的主要价值，不是照抄）**：
1. 上游 `end_pos = min(start_pos + 8000, len(full))` 之后**不标注被截断**，
   读者会以为读全了。这里返回 `truncated` 标志并在文本尾部显式插入 `[⚠️ 已截断]`。
2. 上游无 `is_encrypted/decrypt`，且抽页异常被 `except: return ""` 吞掉 →
   加密 PDF 会得到「全空文本但 found 全 False 却静默成功」。这里把
   `encrypted` / `empty` / `error` 显式暴露，绝不静默。
3. 上游只在 section 外层给 `start_page/end_page`。这里额外提供
   `locate_page()`，让**任意字符位置**都能换算出页码 —— 引用精度到页。

**与上游的差别（形态不同，不照抄）**：
上游为 LLM 写手产出 12 个 section 的完整 JSON（含 3 个科创板专属段）；
本项目是短线系统，只需要「按需抽取 + 页码级证据」，因此 section 表按
**排雷与催化**场景裁剪，并直接产出便于构造 `EvidenceRef` 的结构。

依赖：仅需 `pypdf`（与上游同款），无内部 import，可独立测试。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Sequence

__all__ = [
    "PdfDoc", "Section", "Hit",
    "read_pdf", "from_pages", "find_sections", "search_text", "locate_page",
    "SECTION_PATTERNS",
]

PAGE_MARKER = "__PAGE_{}__"
_PAGE_MARKER_RE = re.compile(r"__PAGE_(\d+)__")

# 目录引导：年报目录行形如「第三节 管理层讨论与分析 ......... 13」。
# 正文标题后不会有这串点号 —— 这是区分目录与正文最可靠的判据。
_TOC_LEADER = re.compile(r"[.．·…]{3,}\s*\d+")
_QUOTES = "“”「」『』‘’\"'"

#: 单段抽取上限。★ 超过即截断并**显式标注**，绝不静默。
DEFAULT_MAX_SECTION_CHARS = 8000
TRUNCATION_NOTE = "[⚠️ 已截断]"


@dataclass
class Section:
    """一个抽取出来的 section。"""

    name: str
    desc: str
    found: bool                 # 是否命中正文（False = 只命中目录或未命中）
    kind: str                   # body | toc | ref | missing
    start_page: int | None
    end_page: int | None
    text: str
    truncated: bool = False
    note: str = ""

    @property
    def chars(self) -> int:
        return len(self.text)


@dataclass
class Hit:
    """一次关键词命中，带页码 —— 可直接转成证据引用。"""

    page: int
    line_no: int
    snippet: str


@dataclass
class PdfDoc:
    """一份已解析的 PDF。

    ★ 解析失败**不返回空壳就完事**：`error` / `encrypted` / `empty` 必须被
    调用方检查，否则「读不到」会被误当成「没有这个内容」。
    """

    pages: list[str] = field(default_factory=list)
    encrypted: bool = False
    error: str = ""
    source: str = ""

    @property
    def ok(self) -> bool:
        return not self.error and bool(self.pages)

    @property
    def empty(self) -> bool:
        """页面存在但抽不出任何文字（扫描件 / CID 字体映射失败）。"""
        return bool(self.pages) and not any(p.strip() for p in self.pages)

    @property
    def page_count(self) -> int:
        return len(self.pages)


def from_pages(pages: Sequence[str], *, source: str = "") -> PdfDoc:
    """用现成页文本构造 PdfDoc（测试与离线场景用，无需真实文件）。"""
    return PdfDoc(pages=list(pages), source=source)


def _build_full(pages: Iterable[str]) -> str:
    """把逐页文本拼成带页标记的全文 —— 页码就是从这些标记反查出来的。"""
    return "\n".join(f"{PAGE_MARKER.format(i)}\n{t}" for i, t in enumerate(pages, start=1))


def locate_page(full: str, pos: int) -> int | None:
    """把全文里的字符位置换算成**物理页码**（1-based）。"""
    if pos < 0:
        return None
    # 位置 0 落在第 1 页页标记之前，此时尚无标记可数，但答案就是第 1 页
    page = 1 if full.startswith(PAGE_MARKER.format(1)) else None
    for m in _PAGE_MARKER_RE.finditer(full, 0, pos):
        page = int(m.group(1))
    return page


def _strip_markers(text: str) -> str:
    """去掉页标记，但保留 `[P.N]` 内联标注（那是给读者看的引用）。"""
    return _PAGE_MARKER_RE.sub("", text)


def read_pdf(path: str | Path, *, password: str = "") -> PdfDoc:
    """读取 PDF。异常一律转成 `PdfDoc.error`，**不向上抛**。"""
    path = Path(path)
    try:
        from pypdf import PdfReader
        from pypdf.errors import PdfReadError
    except ImportError as exc:                              # pragma: no cover
        return PdfDoc(error=f"缺少 pypdf 依赖: {exc}", source=str(path))

    if not path.is_file():
        return PdfDoc(error=f"文件不存在: {path}", source=str(path))

    doc = PdfDoc(source=str(path))
    try:
        reader = PdfReader(str(path))
    except Exception as exc:                                # noqa: BLE001
        doc.error = f"PDF 打开失败: {type(exc).__name__}: {exc}"
        return doc

    try:
        if reader.is_encrypted:
            doc.encrypted = True
            # 多数公告 PDF 是空口令加密，解密失败才真的读不了
            if reader.decrypt(password) == 0:
                doc.error = "PDF 已加密且解密失败"
                return doc
    except Exception as exc:                                # noqa: BLE001
        doc.error = f"PDF 加密状态判定失败: {type(exc).__name__}: {exc}"
        return doc

    for i, page in enumerate(reader.pages, start=1):
        try:
            doc.pages.append(page.extract_text() or "")
        except Exception as exc:                            # noqa: BLE001
            # ★ 单页失败不能让整份文档静默变空：记录并留空串，保持页码对齐
            doc.pages.append("")
            doc.error = doc.error or ""
            if not doc.error:
                doc.error = f"第 {i} 页抽取失败: {type(exc).__name__}"
    return doc


def _candidate_kind(full: str, start: int, end: int) -> str:
    """判定一次标题命中属于「目录条目 / 交叉引用 / 正文标题」。

    判据来自上游实测：**不按长度判断** —— 正文短不等于没正文
    （子公司表、勾了「不适用」的段落本来就短）。目录行必定带点号引导。
    """
    line_end = full.find("\n", end)
    if line_end == -1:
        line_end = len(full)
    if _TOC_LEADER.search(full[end:line_end]):
        return "toc"
    line_start = full.rfind("\n", 0, start) + 1
    prefix = full[line_start:start]
    suffix = full[end:end + 2]
    if any(q in prefix for q in _QUOTES) or (suffix[:1] and suffix[0] in _QUOTES):
        return "ref"
    if len(prefix.strip()) > 10:
        return "ref"
    return "body"


#: section 定义：start 为开始正则，end 为候选结束正则列表（取最早命中者）。
#: 裁剪原则：只保留**排雷与催化**真正会用到的段，不做全量移植。
SECTION_PATTERNS: dict[str, dict[str, Any]] = {
    "main_financial_data": {
        "start": (
            r"一、?\s*主要财务数据"
            r"|[一二三四五六七八九十]+、?\s*(?:近三年|公司)?\s*主要会计数据和财务指标"
            r"|(?:近三年)?主要会计数据及财务指标"
            r"|[（(]\s*一\s*[）)]\s*主要会计数据"
        ),
        "end": [r"二、?\s*股东信息", r"非经常性损益项目和金额", r"二、?\s*股东人数"],
        "desc": "核心财务数据表",
    },
    "non_recurring_items": {
        "start": r"非经常性损益项目和金额|非经常性损益",
        "end": [r"主要会计数据和财务指标发生变动", r"变动的情况及原因", r"资产负债表项目变动"],
        "desc": "非经常性损益明细（扣非质量）",
    },
    "income_statement_changes": {
        "start": r"(?:2\s*、|2\s*\.)\s*利润表项目变动|利润表项目变动的原因"
                 r"|利润表及现金流量表相关科目变动分析表|财务报表相关科目变动分析表",
        "end": [r"(?:3\s*、|3\s*\.)\s*现金流量表项目变动", r"二、?\s*股东信息",
                r"资产、负债情况分析"],
        "desc": "★ 利润表项目变动（含「变动原因」—— 业绩归因在此）",
    },
    "mda": {
        "start": r"管理层讨论与分析|经营情况讨论与分析",
        "end": [r"第四节", r"公司治理", r"重要事项", r"股份变动及股东情况"],
        "desc": "★ MD&A 经营讨论（管理层口径的业务解释）",
    },
    "risks": {
        "start": r"可能面对的风险|风险因素|公司面临的风险",
        "end": [r"第四节", r"公司治理", r"利润分配", r"重要事项"],
        "desc": "★ 风险揭示（公司自述风险，常含真实软肋）",
    },
    "top10_holders": {
        "start": r"前十名股东持股情况表|前\s*10\s*名股东持股情况|普通股股东总数",
        "end": [r"控股股东", r"实际控制人", r"第五节", r"优先股股东"],
        "desc": "十大股东结构（席位与筹码）",
    },
    "subsidiaries": {
        "start": r"主要控股参股公司分析|主要子公司及对公司净利润影响",
        "end": [r"公司控制的结构化主体", r"第四节", r"公司未来发展的讨论"],
        "desc": "主要控股参股公司（分部与并表影响）",
    },
    "audit_opinion": {
        # ★ 本项目新增：非标审计意见是排雷里最硬的信号，上游没有这一段
        "start": r"审计报告|非标准审计意见|保留意见|无法表示意见|强调事项段",
        "end": [r"财务报表附注", r"合并资产负债表", r"二、?\s*财务报表"],
        "desc": "★ 审计报告与审计意见（非标意见 / 强调事项段）",
    },
}


def find_sections(
    doc: PdfDoc,
    names: Sequence[str] | None = None,
    *,
    max_chars: int = DEFAULT_MAX_SECTION_CHARS,
) -> dict[str, Section]:
    """按 `SECTION_PATTERNS` 抽取指定 section。

    返回结构里 `kind='toc'` 表示**只命中目录**（正文可能在别处或本就没有），
    `truncated=True` 表示被 `max_chars` 截断 —— 两者都必须被上游调用方看见。
    """
    wanted = list(names) if names else list(SECTION_PATTERNS)
    full = _build_full(doc.pages)
    out: dict[str, Section] = {}

    for name in wanted:
        spec = SECTION_PATTERNS.get(name)
        if spec is None:
            continue
        # ★ 必须遍历**全部**候选再择优：标题在目录页同样会命中，
        #   而目录几乎总在正文之前 —— 只取第一个 match 会把「有正文」误判成
        #   「只命中目录」。上游实测「全文 4 个候选里只有目录页那一个带点号」。
        best: tuple[Any, str] | None = None
        for m in re.finditer(spec["start"], full):
            kind = _candidate_kind(full, m.start(), m.end())
            if kind == "body":
                best = (m, kind)
                break
            if best is None:
                best = (m, kind)          # 兜底：至少保留目录/引用命中，不静默丢弃

        if best is None:
            out[name] = Section(name, spec["desc"], False, "missing", None, None, "",
                                note="未命中任何标题")
            continue

        m, kind = best
        end_pos = len(full)
        for end_pat in spec["end"]:
            # ★ 第三参是 flags 不是 pos —— 必须先编译再用 `search(string, pos)`
            em = re.compile(end_pat).search(full, m.end())
            if em and em.start() < end_pos:
                end_pos = em.start()

        truncated = (end_pos - m.start()) > max_chars
        raw = full[m.start():min(end_pos, m.start() + max_chars)]
        text = _strip_markers(raw)
        if truncated:
            text = f"{text}\n{TRUNCATION_NOTE}"

        out[name] = Section(
            name=name,
            desc=spec["desc"],
            found=(kind == "body"),
            kind=kind,
            start_page=locate_page(full, m.start()),
            end_page=locate_page(full, end_pos - 1),
            text=text,
            truncated=truncated,
            note="只命中目录条目，正文未定位" if kind == "toc" else "",
        )
    return out


def search_text(
    doc: PdfDoc,
    keyword: str,
    *,
    max_hits: int = 50,
    snippet_chars: int = 300,
) -> list[Hit]:
    """逐页逐行检索关键词，返回带页码的命中。

    用于"检索式抽取"：长年报不必全量投喂，先按关键词定位再取周边段落。
    ★ 按行匹配，跨行短语会漏检 —— 这是已知限制，不假装有能力。
    """
    hits: list[Hit] = []
    try:
        pat = re.compile(keyword)
    except re.error:
        pat = re.compile(re.escape(keyword))
    for page_no, page in enumerate(doc.pages, start=1):
        for line_no, line in enumerate(page.splitlines(), start=1):
            if pat.search(line):
                hits.append(Hit(page=page_no, line_no=line_no, snippet=line.strip()[:snippet_chars]))
                if len(hits) >= max_hits:
                    return hits
    return hits
