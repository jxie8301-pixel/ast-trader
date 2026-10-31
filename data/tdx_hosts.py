"""tdx_hosts —— 7709 行情主站候选解析（四级优先级 + 故障转移尾巴）。

## 为什么需要这个文件

eltdx 内建 43 台默认主站（`eltdx.hosts.DEFAULT_HOSTS`），但它对两个端口的
**可配置能力不对称**：

· 扩展行情 7727（`eltdx/ex/hosts.py:3-8`）有四层覆盖：
  显式参数 > `ELTDX_EX_HOSTS` 环境变量 > `<data_dir>/ex_servers.json` > 包内默认
· 主站 7709（`eltdx/hosts.py:238-251` 的 `load_server_config()`）
  **只有包内 tdx_server.json 一条来源**，既无环境变量也无用户配置文件覆盖。

本模块把 7709 补齐到与 7727 对称，并且**不改动 eltdx 包内任何东西**
（`site-packages` 会被升级覆盖，改了也是白改）。

默认池直接用 eltdx 包内的 43 台（更新更勤、覆盖更好）；本项目**不再自带**
任何固定 IP 名单（历史那 5 台已删除，见 `config.py` 注释）。

## 红线

★ **严禁任何远程/线上拉取主机列表**。eltdx 在 `ex/hosts.py:10-11` 明确拒绝，
  理由是「远端可下发任意 IP」的供应链风险。本模块的配置来源只有
  **本地文件与环境变量**，且永远是全离线的。
★ 缺失一律降级到下一优先级并记 warning，**绝不因配置问题让系统起不来**。
"""
from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import config

__all__ = [
    "QUOTE_HOSTS_ENV",
    "QUOTE_SERVER_FILE",
    "DEFAULT_QUOTE_PORT",
    "resolve_quote_hosts",
]

logger = logging.getLogger("ast_trader.data.tdx_hosts")

#: 环境变量名（逗号 / 分号 / 空白分隔），与 eltdx 的 ``ELTDX_EX_HOSTS`` 风格一致
QUOTE_HOSTS_ENV = "AST_TDX_HOSTS"
#: 用户配置文件名
QUOTE_SERVER_FILE = "tdx_servers.json"
#: 行情主站默认端口（host 串省略端口时补它）
DEFAULT_QUOTE_PORT = 7709

_HOST_SPLIT = re.compile(r"[,;\s]+")


# ---------------------------------------------------------------- 归一化
def _normalize(value: Any) -> str | None:
    """把任意形态的主机条目规整成 ``"host:port"``，无法识别返回 ``None``。

    同时兼容三种写法：
    · ``"116.205.183.150:7709"``  · ``"116.205.183.150"``（补 7709）
    · ``("116.205.183.150", 7709)``（``config.DEFAULT_TDX_HOSTS`` 的历史形态）

    优先复用 eltdx 的 ``normalize_host``（它还处理 IPv6 与域名），
    取不到时退回本地实现 —— 保证本模块在没有 eltdx 时也能被 import。
    """
    if isinstance(value, (tuple, list)) and len(value) == 2:
        value = f"{value[0]}:{value[1]}"
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    try:
        from eltdx.hosts import normalize_host

        return normalize_host(text)
    except Exception:                                       # noqa: BLE001
        return text if ":" in text else f"{text}:{DEFAULT_QUOTE_PORT}"


def _clean(values: Iterable[Any]) -> list[str]:
    """归一化 + 去重 + 保序。"""
    out: list[str] = []
    seen: set[str] = set()
    for v in values:
        h = _normalize(v)
        if h and h not in seen:
            seen.add(h)
            out.append(h)
    return out


# ---------------------------------------------------------------- 各级来源
def _from_env(env: Mapping[str, str] | None = None) -> list[str]:
    """② 环境变量 `AST_TDX_HOSTS`。未设置或全空白时返回空列表。"""
    env = os.environ if env is None else env
    raw = env.get(QUOTE_HOSTS_ENV, "")
    if not raw or not raw.strip():
        return []
    return _clean(x for x in _HOST_SPLIT.split(raw) if x)


def _candidate_files(config_path: str | os.PathLike[str] | None = None) -> list[Path]:
    """用户配置文件的查找位置：显式路径 > 项目根 > eltdx 数据目录。"""
    if config_path is not None:
        return [Path(config_path)]
    paths: list[Path] = []
    base = getattr(config, "BASE_DIR", None)
    if base:
        paths.append(Path(base) / QUOTE_SERVER_FILE)
    try:
        from eltdx._paths import data_dir

        paths.append(Path(data_dir()) / QUOTE_SERVER_FILE)
    except Exception:                                       # noqa: BLE001
        pass
    return paths


def _from_file(config_path: str | os.PathLike[str] | None = None) -> list[str]:
    """③ 用户配置文件 `tdx_servers.json`。

    读取失败（不存在 / 权限 / 非法 JSON / 结构不对）一律**降级**到下一优先级，
    只记 warning —— 配置问题绝不能让系统起不来。

    支持两种文件形态：
    ``{"hosts": ["ip:7709", ...]}``  或裸数组 ``["ip:7709", ...]``
    """
    for path in _candidate_files(config_path):
        try:
            if not path.is_file():
                continue
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:                            # noqa: BLE001
            logger.warning("行情主站配置文件读取失败（已跳过 %s）: %s", path, exc)
            continue
        raw = data.get("hosts") if isinstance(data, dict) else data
        if not isinstance(raw, (list, tuple)):
            logger.warning("行情主站配置文件 %s 缺少 hosts 列表（已跳过）", path)
            continue
        hosts = _clean(raw)
        if hosts:
            return hosts
    return []


def _eltdx_defaults() -> list[str]:
    """④ eltdx 包内默认池（实测 43 台）。取不到时返回空列表。"""
    try:
        from eltdx.hosts import DEFAULT_HOSTS

        return _clean(DEFAULT_HOSTS)
    except Exception as exc:                                # noqa: BLE001
        logger.warning("无法载入 eltdx 默认主站池: %s", exc)
        return []


# ---------------------------------------------------------------- 对外入口
def resolve_quote_hosts(
    host: str | None = None,
    hosts: Sequence[Any] | str | None = None,
    *,
    env: Mapping[str, str] | None = None,
    config_path: str | os.PathLike[str] | None = None,
) -> list[str]:
    """解析 7709 行情主站候选，返回**有序**的 ``"ip:port"`` 列表。

    优先级（高 → 低）：
        ① 显式参数 ``host`` / ``hosts``
        ② 环境变量 ``AST_TDX_HOSTS``
        ③ 用户配置文件 ``tdx_servers.json``（项目根或 eltdx 数据目录）
        ④ eltdx 包内 ``DEFAULT_HOSTS``（43 台）

    ★ 显式参数被当作**用户明确意图**，原样返回、不做任何替换或追加
      —— 说连哪台就连哪台，不悄悄掺别的机器。
    ★ 走 ②③④ 路径时，eltdx 默认池会作为**故障转移尾巴**追加在后面。
      这样既尊重用户偏好，又永远有多台兜底，不会出现「名单只有 1 台、
      那台挂了就全盘失效」的单点问题。

    本函数**不发起任何网络请求**，纯本地解析。
    """
    if isinstance(hosts, str):
        hosts = _HOST_SPLIT.split(hosts)
    explicit = _clean(hosts or ([host] if host else []))
    if explicit:
        return explicit

    preferred = _from_env(env) or _from_file(config_path)
    tail = [h for h in _eltdx_defaults() if h not in preferred]
    return _clean([*preferred, *tail])
