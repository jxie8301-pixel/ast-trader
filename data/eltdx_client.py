"""eltdx TCP client and connection manager for AST-Trader."""
from __future__ import annotations

import logging
import re
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any

from eltdx import TdxClient
from eltdx.exceptions import TransportError
from eltdx.financial import open_calc_client

import config

logger = logging.getLogger("ast_trader.data.client")


class EltdxFetchError(Exception):
    """网络或底层数据获取异常。"""


class EltdxFormatError(Exception):
    """格式解析异常。"""


def log_fail(what: str, exc: Exception) -> None:
    logger.warning(f"[eltdx][FAIL] {what}: {exc}")


@contextmanager
def open_calc(timeout: float = 8.0):
    """打开计算服务器连接 (用于下载专业财务 zip)。"""
    with open_calc_client(timeout=timeout) as client:
        yield client


def normalize_code(code: str) -> tuple[str, str]:
    """标准化股票代码。
    
    返回: (eltdx_code, ts_code)
    例如: 
      '600519' -> ('sh600519', '600519.SH')
      '002273' -> ('sz002273', '002273.SZ')
      '920002' -> ('bj920002', '920002.BJ')
    """
    raw = code.strip().upper()
    # 剔除可能带的前缀/后缀
    m = re.match(r"^(SH|SZ|BJ)?(\d{6})(?:\.(SH|SZ|BJ))?$", raw)
    if m:
        num = m.group(2)
        pref = m.group(1) or m.group(3)
    else:
        num = re.sub(r"\D", "", raw)
        pref = None

    if len(num) != 6:
        raise ValueError(f"非法股票代码: {code!r}")

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
def open_client(timeout: float = 6.0) -> Iterator[TdxClient]:
    """打开一个 TdxClient 连接，并在退出时自动关闭。"""
    client = TdxClient(timeout=timeout)
    try:
        yield client
    finally:
        try:
            client.close()
        except Exception as e:
            logger.debug("Client close exception (safe to ignore): %s", e)


def with_retry(fn: Callable[[], Any], max_retries: int = 3, retry_delay: float = 0.5) -> Any:
    """执行函数并带网络传输类异常退避重试。"""
    last_err: Exception | None = None
    for attempt in range(max_retries):
        try:
            return fn()
        except (TransportError, OSError, TimeoutError) as exc:
            last_err = exc
            logger.warning(f"网络传输异常 (第 {attempt+1}/{max_retries} 次重试): {exc}")
            time.sleep(retry_delay * (2 ** attempt))
        except Exception:
            raise
    raise last_err if last_err else RuntimeError("重试已耗尽")
