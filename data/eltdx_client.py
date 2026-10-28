"""eltdx_client — eltdx 连接层：客户端生命周期、异常归一、退避重试。
Strictly aligned with Ashare-researchreport/scripts/eltdx_client.py.
"""
from __future__ import annotations

import logging
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any

from eltdx import TdxClient
from eltdx.exceptions import EltdxError, ProtocolError, ResourceFormatError, TransportError

import config

logger = logging.getLogger("ast_trader.data.client")


class EltdxUnavailable(EltdxError):
    """环境未就绪：eltdx 没装，或 Rust 原生扩展缺失。降级，不重试。"""


class EltdxFetchError(EltdxError):
    """取数失败且重试已耗尽。调用方可降级为空表并告警。"""


class EltdxFormatError(EltdxFetchError):
    """数据格式非法（zip 损坏 / 协议解不开）。**不可重试**。"""


def code6(code: str) -> str:
    """提取 6 位纯数字代码。"""
    cleaned = "".join(c for c in code if c.isdigit())
    if len(cleaned) < 6:
        raise ValueError(f"代码长度不足 6 位: {code}")
    return cleaned[-6:]


def normalize_code(code_str: str) -> tuple[str, str]:
    """标准化股票代码，返回 (eltdx_code, ts_code)。例如 '002273' -> ('sz002273', '002273.SZ')。"""
    c = code_str.strip()
    num = ""
    pref = ""
    for ch in c:
        if ch.isdigit():
            num += ch
        elif ch.isalpha():
            pref += ch

    if len(num) < 6:
        raise ValueError(f"无法识别股票代码: {code_str}")
    num = num[-6:]

    if not pref:
        if num.startswith(("60", "68", "90")):
            pref = "SH"
        elif num.startswith(("00", "30")):
            pref = "SZ"
        elif num.startswith(("4", "8", "9")):
            pref = "BJ"
        else:
            pref = "SZ"

    pref = pref.upper()
    eltdx_code = f"{pref.lower()}{num}"
    ts_code = f"{num}.{pref}"
    return eltdx_code, ts_code


@contextmanager
def open_client(timeout: float = 6.0, host: str | None = None, port: int | None = None) -> Iterator[TdxClient]:
    """打开一个 TdxClient 连接，并在退出时自动关闭。优先选用 DEFAULT_TDX_HOSTS 节点池。"""
    client = None
    if host and port:
        client = TdxClient(host=host, port=port, timeout=timeout)
    else:
        hosts = getattr(config, "DEFAULT_TDX_HOSTS", [])
        if hosts:
            h, p = hosts[0]
            try:
                client = TdxClient(host=h, port=p, timeout=timeout)
            except Exception:
                client = TdxClient(timeout=timeout)
        else:
            client = TdxClient(timeout=timeout)
    try:
        yield client
    finally:
        try:
            if client:
                client.close()
        except Exception as e:
            logger.debug("Client close exception (safe to ignore): %s", e)


@contextmanager
def open_calc(*, timeout: float = 12.0) -> Iterator[Any]:
    """建一个指向计算服务器的客户端（专业财务 zip 走这条）。
    必须用 eltdx.financial.open_calc_client。
    """
    from eltdx.financial import open_calc_client

    client = open_calc_client(timeout=timeout)
    try:
        yield client
    finally:
        try:
            client.close()
        except Exception:
            pass


def _is_retryable(exc: BaseException) -> bool:
    """只有传输类错误值得重试；格式/协议错误重试没有意义。"""
    names = {type(exc).__name__}
    names.update(c.__name__ for c in type(exc).__mro__)
    retryable = {"TransportError", "ResponseTimeoutError", "ConnectionClosedError",
                 "PoolBusyError", "TimeoutError", "OSError", "ConnectionError"}
    return bool(names & retryable)


def with_retry(
    fn: Callable[[], Any],
    *,
    what: str = "取数",
    max_retries: int = 3,
    retry_delay: float = 0.5,
    **kwargs: Any,
) -> Any:
    """带指数退避地执行 fn，支持关键字参数 what。"""
    last_err: Exception | None = None
    retries = kwargs.get("retries", max_retries)
    for attempt in range(retries):
        try:
            return fn()
        except (TransportError, OSError, TimeoutError) as exc:
            last_err = exc
            logger.warning(f"{what} 网络传输异常 (第 {attempt+1}/{retries} 次重试): {exc}")
            time.sleep(retry_delay * (2 ** attempt))
        except Exception as exc:
            if _is_retryable(exc):
                last_err = exc
                time.sleep(retry_delay * (2 ** attempt))
            else:
                raise
    raise last_err if last_err else RuntimeError(f"{what} 重试已耗尽")


def log_fail(msg: str, exc: Exception | None = None) -> None:
    """记录客户端或下层模块失败日志，防止上层 AttributeError。"""
    if exc is not None:
        logger.error(f"{msg}: {type(exc).__name__}: {exc}", exc_info=True)
    else:
        logger.error(msg)
