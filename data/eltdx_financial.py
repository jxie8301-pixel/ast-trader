"""eltdx_financial —— 专业财务 zip（通路 A）的下载 / 缓存 / 取数。

## 为什么单独一个模块

专业财务 zip 是**利润表的唯一数据源**（F10 的 `lrb`/`zysz`/`zycwzb` 经实测全部
只返回 3 列元数据，见 `reports/m3_fields_probe.log` ⑥）。但它有两个和别处都不同的
脾气，必须集中处理：

1. **取一只股票也要下载整个市场**：每期 zip 是全市场约 5578 只 × 584 个 float32，
   5~6 MB。所以缓存粒度必须是**报告期**而不是公司，否则一次全量采集要下十遍同样的包。
2. **失败是静默的**：路径写错时 `download_archive` 返回 **0 字节且不抛异常**
   （M0 第五轮实测）。不主动校验字节数，就会拿到一个空结果还以为"这家公司没数据"。

## 五个已记录的坑，全部在这里守卫

| 坑 | 守卫位置 |
|---|---|
| zip 路径必须带 `tdxfin/` 前缀（列表返回 basename，下载要前缀） | `_with_prefix()` |
| 最新期可能是 164 字节空壳（报告期在未来） | `MIN_ARCHIVE_BYTES` + `filesize` 双筛 |
| 下载返回 0 字节不抛异常 | `_download()` 下载后校验字节数 |
| 单公司也下全市场包 | 报告期级磁盘缓存（zip 原样 + 解析结果） |
| float32 精度导致数值反查撞车 | **不在本模块定科目** —— 映射只由 `eltdx_financial_map` 负责 |

## 分层

`zip 字节`（保真，可复现） → `dat` → `FinancialPeriod`（codes + matrix）。
解析结果另存一份 npz，避免每次重解 5578×584。两层缓存都在 `config.CACHE_DIR/eltdx_fin/`。
"""
from __future__ import annotations

import io
import re
import sys
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

import config
from . import eltdx_client as ec
from . import eltdx_units as un

# ---------------------------------------------------------------- 常量
TDXFIN_PREFIX = "tdxfin/"

# 空壳 zip 实测 164 字节（`gpcw20261231.zip`，报告期在未来）；正常期 5~6 MB。
# 取 100 KB 是**刻意留的余量**：这条守卫要挡的是"空壳"，不是"小期"，
# 定成 1 MB 有把数据少的早期报告期误杀的风险 —— 误杀比漏挡更难发现。
MIN_ARCHIVE_BYTES = 100_000

_REPORT_DATE_RE = re.compile(r"(\d{8})")


class EltdxFinancialError(Exception):
    """专业财务取数失败（路径守卫 / 空壳 / 解析失败统一归一）。"""


@dataclass
class FinancialPeriod:
    """某一报告期的全市场专业财务数据。

    `codes` 是六位代码（与 `matrix` 行序一致），`matrix` 是 `(n, field_count)` 的
    float32 矩阵。**本类不知道任何字段的业务含义** —— 下标 → 科目的翻译只在
    `eltdx_financial_map` 里做，这里只负责把它取出来。
    """

    period: str
    codes: list[str]
    matrix: "np.ndarray"
    by_code: dict[str, int] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        if not self.by_code:
            self.by_code = {c: i for i, c in enumerate(self.codes)}

    @property
    def field_count(self) -> int:
        return int(self.matrix.shape[1]) if self.matrix.ndim == 2 else 0

    def fields_of(self, ts_code: str) -> tuple[float, ...] | None:
        """取某只股票的 584 个字段；没有这只股票返回 None（不是抛异常）。"""
        code = un.code6(ts_code)
        row = self.by_code.get(code)
        if row is None:
            return None
        return tuple(float(v) for v in self.matrix[row])


# ---------------------------------------------------------------- 缓存路径
def _cache_dir() -> Path:
    d = Path(config.CACHE_DIR) / "eltdx_fin"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _zip_path(period: str) -> Path:
    return _cache_dir() / f"gpcw{period}.zip"


def _npz_path(period: str) -> Path:
    return _cache_dir() / f"gpcw{period}.npz"


# ---------------------------------------------------------------- 路径守卫
def _with_prefix(filename: str) -> str:
    """补全 `tdxfin/` 前缀。

    ★ `list_archive_files()` 返回的 `filename` **只有 basename**（`gpcw20251231.zip`），
    但 `download_archive()` 必须传 `tdxfin/gpcw20251231.zip` —— eltdx 文档
    `FINANCIAL.md:29` 声称列表返回的是带前缀的形式，与实际不符（SDK 文档缺陷，
    M0 第四轮实测）。**路径错时下载返回 0 字节且不抛异常**，所以这个补全必须存在。
    """
    name = (filename or "").strip()
    if not name:
        raise EltdxFinancialError("zip 文件名为空")
    if name.startswith(TDXFIN_PREFIX):
        return name
    # 只接受 basename，避免 'foo/bar.zip' 被拼成 'tdxfin/foo/bar.zip'
    return TDXFIN_PREFIX + name.split("/")[-1]


def _period_of(filename: str) -> str | None:
    """从文件名抽 8 位报告期。`download_records` 的报告期也取自这里。"""
    m = _REPORT_DATE_RE.search(filename or "")
    return m.group(1) if m else None


# ---------------------------------------------------------------- 列清单
def list_archives() -> list[dict]:
    """列出计算服务器上可用的财报 zip，按报告期降序。

    已做两件事：① filename 补成带 `tdxfin/` 前缀的可下载形式；
    ② 按 `filesize` 滤掉空壳期（报告期在未来，实测 164 字节）。

    返回 `[{period, filename, filesize}]`。网络失败抛 `EltdxFetchError`。
    """
    from eltdx.financial import list_archive_files

    def _fetch():
        with ec.open_calc() as client:
            return list_archive_files(client)

    try:
        raw = ec.with_retry(_fetch, what="financial.list_archive_files")
    except ec.EltdxFetchError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise ec.EltdxFetchError(f"列出财报清单失败: {type(exc).__name__}: {exc}") from exc

    out: list[dict] = []
    skipped: list[str] = []
    for item in raw or ():
        name = getattr(item, "filename", None) or ""
        size = int(getattr(item, "filesize", 0) or 0)
        period = _period_of(name)
        if not period:
            continue
        if size < MIN_ARCHIVE_BYTES:
            skipped.append(f"{period}({size}B)")
            continue
        out.append({"period": period, "filename": _with_prefix(name), "filesize": size})

    if skipped:
        import logging
        logging.getLogger('ast_trader.eltdx').debug(
            f'[eltdx] 财报清单跳过 {len(skipped)} 个空壳期: {skipped[:3]}'
        )
    out.sort(key=lambda d: d["period"], reverse=True)
    return out


def available_periods(*, annual_only: bool = False) -> list[str]:
    """可用报告期列表（降序）。`annual_only=True` 时只要 1231 结尾的年报期。"""
    periods = [d["period"] for d in list_archives()]
    if annual_only:
        periods = [p for p in periods if p.endswith("1231")]
    return periods


# ---------------------------------------------------------------- 下载与解析
def _download(period: str) -> bytes:
    """下载某一报告期的 zip 字节，落盘缓存。

    ★ 下载后**必须校验字节数**：路径前缀写错时返回 0 字节且不抛异常，
    这是本模块最重要的守卫。
    """
    filename = _with_prefix(f"gpcw{period}.zip")

    def _fetch() -> bytes:
        from eltdx.financial import download_archive
        with ec.open_calc() as client:
            return download_archive(client, filename)

    payload = ec.with_retry(_fetch, what=f"financial.download_archive {filename}")
    if not payload:
        raise EltdxFinancialError(
            f"{filename} 下载返回空内容 —— 先怀疑路径前缀（必须是 "
            f"'{TDXFIN_PREFIX}' 开头），eltdx 在路径错误时静默返回 0 字节"
        )
    if len(payload) < MIN_ARCHIVE_BYTES:
        raise EltdxFinancialError(
            f"{filename} 只有 {len(payload)} 字节，小于 {MIN_ARCHIVE_BYTES} "
            f"—— 大概率是空壳期（报告期在未来）"
        )

    path = _zip_path(period)
    try:
        path.write_bytes(payload)
    except OSError as exc:
        # 缓存写失败不阻断取数（内存里已经有数据了）
        ec.log_fail(f"财报 zip 缓存写入失败 {path}", exc)
    return payload


def _parse(payload: bytes, period: str) -> FinancialPeriod:
    """zip 字节 → `FinancialPeriod`（纯离线解析，不联网）。"""
    from eltdx.offline.history_financial import parse_financial_dat, read_dat_from_zip

    try:
        with zipfile.ZipFile(io.BytesIO(payload)) as zf:
            dat = read_dat_from_zip(zf, source=f"gpcw{period}.zip")
    except Exception as exc:  # noqa: BLE001
        raise ec.EltdxFormatError(
            f"gpcw{period}.zip 解压失败: {type(exc).__name__}: {exc}") from exc

    try:
        rows = parse_financial_dat(dat, int(period))
    except Exception as exc:  # noqa: BLE001
        raise ec.EltdxFormatError(
            f"gpcw{period}.zip 解析失败: {type(exc).__name__}: {exc}") from exc

    if not rows:
        raise ec.EltdxFormatError(f"gpcw{period}.zip 解析出 0 条记录")

    codes: list[str] = []
    matrix = []
    for code, _market_id, _report_date, values in rows:
        codes.append(str(code))
        matrix.append(values)

    arr = np.asarray(matrix, dtype=np.float32)
    if arr.ndim != 2:
        raise ec.EltdxFormatError(f"gpcw{period}.zip 字段维度异常: {arr.shape}")
    return FinancialPeriod(period=period, codes=codes, matrix=arr)


def _save_npz(period: FinancialPeriod) -> None:
    try:
        np.savez_compressed(
            _npz_path(period.period),
            codes=np.asarray(period.codes),
            matrix=period.matrix,
        )
    except Exception as exc:  # noqa: BLE001  缓存失败只记日志
        ec.log_fail(f"财报解析结果缓存写入失败 {period.period}", exc)


def _load_npz(period: str) -> FinancialPeriod | None:
    path = _npz_path(period)
    if not path.exists():
        return None
    try:
        with np.load(path, allow_pickle=False) as data:
            codes = [str(c) for c in data["codes"].tolist()]
            matrix = data["matrix"]
            if matrix.ndim != 2 or len(codes) != matrix.shape[0]:
                raise ValueError(f"缓存形状不一致: {len(codes)} vs {matrix.shape}")
            return FinancialPeriod(period=period, codes=codes, matrix=matrix)
    except Exception as exc:  # noqa: BLE001  缓存坏了就当没有，重新解析
        ec.log_fail(f"财报缓存不可用，将重新解析 {path.name}", exc)
        return None


def load_period(period: str, *, refresh: bool = False) -> FinancialPeriod | None:
    """取某一报告期的全市场财务数据（带报告期级缓存）。

    三级：解析缓存(npz) → zip 缓存 → 网络下载。任一步失败抛 `EltdxFetchError`
    或 `EltdxFormatError`，**不返回空壳**。
    """
    period = str(period).strip()
    if not _REPORT_DATE_RE.fullmatch(period):
        raise EltdxFinancialError(f"报告期必须是 8 位日期: {period!r}")

    if not refresh:
        cached = _load_npz(period)
        if cached is not None:
            return cached

    payload: bytes | None = None
    zpath = _zip_path(period)
    if zpath.exists() and zpath.stat().st_size >= MIN_ARCHIVE_BYTES:
        payload = zpath.read_bytes()

    if payload is None:
        payload = _download(period)

    parsed = _parse(payload, period)
    _save_npz(parsed)
    return parsed


def fields_of(ts_code: str, period: str) -> tuple[float, ...] | None:
    """取某只股票在某一报告期的字段数组；无数据返回 None。"""
    fp = load_period(period)
    return fp.fields_of(ts_code) if fp is not None else None


def latest_periods(count: int = 4, *, annual_only: bool = True) -> list[str]:
    """最近 `count` 个可用报告期（默认只要年报期），降序。"""
    return available_periods(annual_only=annual_only)[:count]
