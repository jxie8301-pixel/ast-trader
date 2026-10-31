"""eltdx_client — eltdx 连接层：就绪门、客户端生命周期、异常归一、退避重试。

**借鉴 Ashare-researchreport 的架构精神，但不照抄**：
上游是脚本式流水线，本项目是 Python 库 + 短线快筛，因此保留本项目的
`host/port` 直连形态与 `log_fail(msg, exc=None)` 签名，只补齐三件缺失能力：

1. **就绪门**（`extension_ready` / `require_extension`）：eltdx 的 Python 包能 import
   不代表可用 —— Rust 原生扩展缺失时绝大多数取数接口会抛 ImportError。
   以前顶层 `from eltdx import TdxClient` 会在未安装时直接 ImportError，
   连"优雅降级"的机会都没有；现在改为**延迟导入 + 显式就绪门**。
2. **异常归一**（`_raise_as_ours`）：把所有 eltdx / 底层异常转成自有的
   `EltdxFetchError` / `EltdxFormatError`，调用方只需 catch 本项目异常。
   以前 `with_retry` 重试耗尽后 `raise last_err` 抛的是**原始 SDK 异常**，
   与"归一"的契约自相矛盾。
3. **代码归一**：`normalize_code` 过去用首位数字判市场（`9` → SH），
   会把北交所 920xxx 误判成沪市。现在**委托给 `eltdx_units` 的同一套规则**，
   与上游 `eltdx_units.py:80-92` 记录的已修 bug 对齐（单一真理源）。

★ 缺值纪律（NFR-02）：本模块不产出任何"看起来正常的默认值"，
取数失败一律抛异常，由调用方决定降级为 None。
"""
from __future__ import annotations

import importlib
import importlib.util
import logging
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any

from .eltdx_units import code6, to_eltdx_code, to_ts_code  # noqa: F401  供采集层统一导入

import config

logger = logging.getLogger("ast_trader.data.client")

__all__ = [
    "EltdxError", "EltdxUnavailable", "EltdxFetchError", "EltdxFormatError",
    "extension_ready", "extension_reason", "require_extension",
    "open_client", "open_calc", "with_retry", "log_fail",
    "code6", "normalize_code", "to_eltdx_code", "to_ts_code",
]


# ---------------------------------------------------------------- 异常
class EltdxError(RuntimeError):
    """本项目 eltdx 相关错误的基类。

    ★ 刻意**不继承** SDK 的 `eltdx.exceptions.EltdxError`：
    本项目的异常应当是自有的、可被上层统一 catch 的契约，
    不随 SDK 版本漂移。
    """


class EltdxUnavailable(EltdxError):
    """环境未就绪：eltdx 没装，或 Rust 原生扩展缺失。降级，不重试。"""


class EltdxFetchError(EltdxError):
    """取数失败且重试已耗尽。调用方可降级为空表并告警。"""


class EltdxFormatError(EltdxFetchError):
    """数据格式非法（zip 损坏 / 协议解不开）。**不可重试**。"""


def _eltdx_exceptions() -> tuple[type[BaseException], ...]:
    """延迟导入 eltdx 异常类（eltdx 未安装时返回空元组，便于 `except` 使用）。"""
    try:
        from eltdx import exceptions as ex
    except ImportError:
        return ()
    return (
        ex.ProtocolError, ex.ResourceFormatError, ex.TransportError,
        ex.UnsupportedCommandError, ex.EltdxError,
    )


# ---------------------------------------------------------------- 就绪检查
# ★ 原生扩展的**模块名随 eltdx 版本变化**：
#   当前安装版是 `eltdx/_native.pyd`（经 `eltdx._native_abi.load_native()` 加载），
#   而 eltdx 技能文档写的是 `eltdx._eltdx`。只按文档硬写 `_eltdx` 会在
#   本环境误判为"扩展缺失"—— 实测踩到过（明明能连能取数，自检却报 MISSING）。
#   所以优先用 SDK 自带的加载器，它还会校验 ABI_VERSION，能额外抓到
#   「装了原生扩展但与 Python 侧版本不匹配」这类更难查的错。
_NATIVE_CANDIDATES = ("eltdx._native", "eltdx._eltdx")


def _native_status() -> tuple[bool, str]:
    """返回 (原生扩展是否就绪, 不可用时的人类可读原因)。"""
    if importlib.util.find_spec("eltdx") is None:
        return False, "eltdx 未安装 → pip install eltdx"
    try:
        from eltdx._native_abi import load_native
    except ImportError:
        load_native = None       # type: ignore[assignment]
    if load_native is not None:
        try:
            load_native()
            return True, ""
        except ImportError as exc:
            # SDK 自己报的错已经说明了是缺失还是 ABI 不匹配，直接用它的信息
            return False, str(exc)
    for name in _NATIVE_CANDIDATES:      # 老/新版本命名兜底
        try:
            importlib.import_module(name)
            return True, ""
        except ImportError:
            continue
    return False, ("Rust 原生扩展缺失（已试 "
                   f"{' / '.join(_NATIVE_CANDIDATES)}）→ 需安装与当前 Python ABI 匹配的原生 wheel")


def extension_ready() -> bool:
    """eltdx 是否可用。

    不能只 `import eltdx` 成功就判定可用 —— Python 包能 import，
    但缺原生扩展时绝大多数取数接口会抛 ImportError。
    """
    return _native_status()[0]


def extension_reason() -> str:
    """不可用时的原因串；可用时返回空串。供自检脚本打印。"""
    ok, why = _native_status()
    return "" if ok else why


def require_extension() -> None:
    """环境不就绪就抛 `EltdxUnavailable`。采集入口先调它，避免半路炸。"""
    ok, why = _native_status()
    if not ok:
        raise EltdxUnavailable(why)


# ---------------------------------------------------------------- 代码归一
def normalize_code(code_str: str) -> tuple[str, str]:
    """标准化股票代码，返回 (eltdx_code, ts_code)。例如 '002273' -> ('sz002273', '002273.SZ')。

    ★ 判定规则**不再自己实现**，一律委托 `eltdx_units`：
    旧实现按首位数字判市场（`("60","68","90")` → SH），会把北交所 920xxx
    误判为 sh920002。与 `to_ts_code` 共用同一份前缀规则可杜绝"这边判 BJ
    那边判 SH"的漂移。

    入参兼容两种形态：六位裸码 / 带 .SH/.SZ/.BJ 后缀 / 已是 eltdx 形态
    （`sh600519`，调用方历史上就这么传，必须继续接受）。
    """
    code = (code_str or "").strip()
    if not code:
        raise ValueError(f"无法识别股票代码: {code_str!r}")

    lowered = code.lower()
    if lowered.startswith(("sh", "sz", "bj")) and lowered[2:].isdigit() and len(lowered) == 8:
        # 已是 eltdx 形态，直接反推 ts 形态即可
        return lowered, to_ts_code(lowered)

    eltdx_code = to_eltdx_code(code)
    ts_code = to_ts_code(eltdx_code)
    return eltdx_code, ts_code


# ---------------------------------------------------------------- 客户端
@contextmanager
def open_client(
    timeout: float | None = None,
    host: str | None = None,
    port: int | None = None,
    *,
    require_ready: bool = True,
) -> Iterator[Any]:
    """打开一个 TdxClient 连接，并在退出时自动关闭。

    候选主机由 `data.tdx_hosts.resolve_quote_hosts` 解析（环境变量
    `AST_TDX_HOSTS` > `tdx_servers.json` > 历史配置 > eltdx 默认 43 台池）。
    `close()` 必须被调用 —— 它会连带关闭资金流与竞价的专用会话，
    只 `del` 客户端不会释放。

    ★ `TdxClient` **没有 `port` 参数**（端口必须写在 host 串里）。
      历史实现传了 `port=`，必然抛 `TypeError`；这里改传 `hosts=` 列表
      以获得故障转移能力，不再手工只取第一台。

    require_ready=False 时跳过就绪门（仅自检/诊断场景用，取数路径请保持 True）。
    """
    if require_ready:
        require_extension()

    from eltdx import TdxClient          # 延迟导入：模块本身可在无 eltdx 环境被 import

    from data.tdx_hosts import resolve_quote_hosts

    timeout = timeout if timeout is not None else config.ELTDX_TIMEOUT
    explicit = f"{host}:{port or 7709}" if host else None
    candidates = resolve_quote_hosts(explicit)

    client = None
    try:
        if candidates:
            # probe_hosts 默认关闭：open_client 在采集层被高频调用，
            # 每次扇出 43 台 TCP 探测会把取数拖垮。eltdx 的连接池会自动套用
            # 已持久化的排名（tdx_server_ranking.json），无需每次重测。
            client = TdxClient(
                hosts=candidates,
                timeout=timeout,
                probe_hosts=getattr(config, "ELTDX_PROBE_HOSTS", False),
            )
            logger.debug("行情主站候选 %d 台，首选项 %s", len(candidates), candidates[0])
        else:
            client = TdxClient(timeout=timeout)
    except Exception as exc:            # noqa: BLE001  归一为本项目异常
        _raise_as_ours(exc, "连接行情主站")
    try:
        yield client
    finally:
        try:
            if client:
                client.close()
        except Exception as exc:        # noqa: BLE001  关闭失败不能盖掉真正的业务异常
            logger.debug("Client close exception (safe to ignore): %s", exc)


@contextmanager
def open_calc(*, timeout: float | None = None, require_ready: bool = True) -> Iterator[Any]:
    """建一个指向**计算服务器**的客户端（专业财务 zip 走这条，与行情主站不同）。

    ★ 计算服务器与 7709 行情主站是**不同服务器**：用普通 `TdxClient` 去下
    `tdxfin/*` 会失败。必须用 `eltdx.financial.open_calc_client`。
    """
    if require_ready:
        require_extension()

    from eltdx.financial import open_calc_client

    timeout = timeout if timeout is not None else config.ELTDX_CALC_TIMEOUT
    try:
        client = open_calc_client(timeout=timeout)
    except Exception as exc:            # noqa: BLE001
        _raise_as_ours(exc, "连接财务计算服务器")
    try:
        yield client
    finally:
        try:
            client.close()
        except Exception:               # noqa: BLE001
            pass


# ---------------------------------------------------------------- 重试
def _is_retryable(exc: BaseException) -> bool:
    """只有传输类错误值得重试；格式/协议错误重试没有意义。"""
    names = {type(exc).__name__}
    names.update(c.__name__ for c in type(exc).__mro__)
    retryable = {"TransportError", "ResponseTimeoutError", "ConnectionClosedError",
                 "PoolBusyError", "TimeoutError", "OSError", "ConnectionError"}
    return bool(names & retryable)


def _raise_as_ours(exc: BaseException, what: str) -> None:
    """把 eltdx / 底层异常转成本项目异常后抛出。"""
    names = {c.__name__ for c in type(exc).__mro__}
    if {"ResourceFormatError", "TdxStatsDateError", "ProtocolError"} & names:
        raise EltdxFormatError(f"{what}: {type(exc).__name__}: {exc}") from exc
    if {"UnsupportedCommandError"} & names:
        raise EltdxFetchError(f"{what}: 接口未迁移（{exc}）") from exc
    raise EltdxFetchError(f"{what}: {type(exc).__name__}: {exc}") from exc


def with_retry(
    fn: Callable[[], Any],
    *,
    what: str = "取数",
    max_retries: int | None = None,
    retry_delay: float | None = None,
    **kwargs: Any,
) -> Any:
    """带指数退避地执行 `fn`，失败时把异常**归一为本项目异常**。

    `what` 是定位串，请带上接口 + 代码 + 期别（如 `"bars.get sz300308 day"`），
    日志里靠它定位，别只写 "取数失败"。

    ★ 与旧实现的关键差别：重试耗尽后**抛 `EltdxFetchError`**，
    而不是把原始 SDK 异常透出去 —— 否则调用方必须同时认识两套异常体系。
    """
    retries = kwargs.pop("retries", None)
    backoff = kwargs.pop("backoff", None)
    n = retries if retries is not None else (
        max_retries if max_retries is not None
        else getattr(config, "ELTDX_MAX_RETRIES", 3)
    )
    base_delay = backoff if backoff is not None else (
        retry_delay if retry_delay is not None
        else getattr(config, "ELTDX_RETRY_BACKOFF", 0.5)
    )
    cap = getattr(config, "ELTDX_RETRY_SLEEP_CAP", 8.0)
    n = max(1, int(n))

    last: BaseException | None = None
    for attempt in range(n):
        try:
            return fn()
        except Exception as exc:        # noqa: BLE001  统一归一
            last = exc
            if not _is_retryable(exc):
                _raise_as_ours(exc, what)
            if attempt < n - 1:
                time.sleep(min(base_delay * (2 ** attempt), cap))
    log_fail(what, last)
    _raise_as_ours(last or RuntimeError("未知失败"), what)
    raise AssertionError("unreachable")  # pragma: no cover  _raise_as_ours 必定抛出


def log_fail(msg: str, exc: Exception | None = None) -> None:
    """记录客户端或下层模块失败日志，防止上层 AttributeError。

    ★ 签名保持 `(msg, exc=None)`：既有调用方（`tests/`、采集层）依赖它。
    """
    if exc is not None:
        logger.error(f"{msg}: {type(exc).__name__}: {exc}")
    else:
        logger.error(msg)
