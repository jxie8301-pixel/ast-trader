"""7709 行情主站候选解析的离线回归。

对应问题：eltdx 对 7727（扩展行情）有四层可覆盖配置，对 7709（主站）却只有
包内 `tdx_server.json` 一条来源。`data/tdx_hosts.py` 把 7709 补齐到对称。

本套测试**全离线**：不发起任何网络请求、不连接真实主站。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

import config
from data import tdx_hosts
from data.tdx_hosts import resolve_quote_hosts

ELTDX_POOL = ["116.205.183.150:7709", "111.230.186.52:7709", "129.204.230.128:7709"]


@pytest.fixture
def isolated_sources(monkeypatch, tmp_path):
    """把来源隔离到受控值，避免读到开发者真实环境。"""
    monkeypatch.setattr(tdx_hosts, "_eltdx_defaults", lambda: list(ELTDX_POOL))

    def _files(config_path=None):
        # 显式给了路径就照用，否则指向一个不存在的文件以隔离真实环境
        if config_path is not None:
            return [Path(config_path)]
        return [tmp_path / "does_not_exist.json"]

    monkeypatch.setattr(tdx_hosts, "_candidate_files", _files)
    return monkeypatch


# ---------------------------------------------------------------- 历史节点池已删除
def test_legacy_host_pool_is_removed():
    """★ 历史那 5 台固定 IP 已删除，默认值一律掉到 eltdx 的 43 台池。"""
    assert not hasattr(config, "DEFAULT_TDX_HOSTS")


def test_module_has_no_legacy_source():
    assert not hasattr(tdx_hosts, "_from_legacy_config")


# ---------------------------------------------------------------- ① 显式参数
def test_explicit_host_is_returned_verbatim(isolated_sources):
    """显式指定 = 用户明确意图，原样返回，绝不掺入别的机器。"""
    assert resolve_quote_hosts("10.0.0.1:7709") == ["10.0.0.1:7709"]


def test_explicit_host_gets_default_port(isolated_sources):
    assert resolve_quote_hosts("10.0.0.1") == ["10.0.0.1:7709"]


def test_explicit_hosts_list_beats_everything(isolated_sources, monkeypatch):
    monkeypatch.setenv("AST_TDX_HOSTS", "9.9.9.9:7709")
    assert resolve_quote_hosts(hosts=["1.1.1.1:7709", "2.2.2.2:7709"]) == [
        "1.1.1.1:7709", "2.2.2.2:7709",
    ]


def test_explicit_hosts_accepts_delimited_string(isolated_sources):
    assert resolve_quote_hosts(hosts="1.1.1.1:7709;2.2.2.2:7709") == [
        "1.1.1.1:7709", "2.2.2.2:7709",
    ]


# ---------------------------------------------------------------- ② 环境变量
def test_env_beats_file(isolated_sources, tmp_path):
    path = tmp_path / "tdx_servers.json"
    path.write_text(json.dumps({"hosts": ["5.5.5.5:7709"]}), encoding="utf-8")
    out = resolve_quote_hosts(env={"AST_TDX_HOSTS": "8.8.8.8:7709"}, config_path=path)
    assert out[0] == "8.8.8.8:7709"


def test_env_empty_falls_through_to_eltdx_pool(isolated_sources):
    assert resolve_quote_hosts(env={"AST_TDX_HOSTS": "   "}) == ELTDX_POOL


def test_env_invalid_entries_are_skipped(isolated_sources):
    out = resolve_quote_hosts(env={"AST_TDX_HOSTS": "8.8.8.8:7709,,,   ,7.7.7.7:7709"})
    assert out[:2] == ["8.8.8.8:7709", "7.7.7.7:7709"]


def test_env_prepended_and_eltdx_pool_appended_as_failover(isolated_sources):
    """★ 既有偏好在前，43 台池兜底在后 —— 永远不会只有 1 台可连。"""
    out = resolve_quote_hosts(env={"AST_TDX_HOSTS": "8.8.8.8:7709"})
    assert out[0] == "8.8.8.8:7709"
    assert set(ELTDX_POOL).issubset(set(out))


# ---------------------------------------------------------------- ③ 配置文件
def test_file_dict_form_beats_eltdx_pool(isolated_sources, tmp_path):
    path = tmp_path / "tdx_servers.json"
    path.write_text(json.dumps({"hosts": ["5.5.5.5:7709"]}), encoding="utf-8")
    assert resolve_quote_hosts(config_path=path)[0] == "5.5.5.5:7709"


def test_file_bare_array_form_supported(isolated_sources, tmp_path):
    path = tmp_path / "tdx_servers.json"
    path.write_text(json.dumps(["5.5.5.5", "6.6.6.6:7709"]), encoding="utf-8")
    assert resolve_quote_hosts(config_path=path)[:2] == ["5.5.5.5:7709", "6.6.6.6:7709"]


def test_corrupt_file_degrades_to_next_source(isolated_sources, tmp_path):
    """★ 配置文件损坏必须降级，绝不让系统起不来。"""
    path = tmp_path / "tdx_servers.json"
    path.write_text("{ 这不是 JSON", encoding="utf-8")
    assert resolve_quote_hosts(config_path=path) == ELTDX_POOL


def test_file_missing_hosts_key_degrades(isolated_sources, tmp_path):
    path = tmp_path / "tdx_servers.json"
    path.write_text(json.dumps({"something": 1}), encoding="utf-8")
    assert resolve_quote_hosts(config_path=path) == ELTDX_POOL


# ---------------------------------------------------------------- 输出形态
def test_output_is_unique_preserving_order(isolated_sources):
    out = resolve_quote_hosts(hosts=["1.1.1.1:7709", "1.1.1.1", "2.2.2.2:7709"])
    assert out == ["1.1.1.1:7709", "2.2.2.2:7709"]


def test_every_entry_has_host_port_form(isolated_sources):
    for h in resolve_quote_hosts():
        assert re.fullmatch(r"[\w.]+:\d+", h), h


def test_duplicates_between_preferred_and_tail_are_collapsed(isolated_sources, monkeypatch):
    monkeypatch.setattr(tdx_hosts, "_eltdx_defaults", lambda: ["1.1.1.1:7709", "9.9.9.9:7709"])
    out = resolve_quote_hosts(env={"AST_TDX_HOSTS": "1.1.1.1:7709"})
    assert out == ["1.1.1.1:7709", "9.9.9.9:7709"]


def test_no_source_at_all_returns_empty_instead_of_crashing(monkeypatch):
    monkeypatch.setattr(tdx_hosts, "_eltdx_defaults", lambda: [])
    monkeypatch.setattr(tdx_hosts, "_candidate_files", lambda *a, **k: [])
    assert resolve_quote_hosts() == []


# ---------------------------------------------------------------- 真实环境兜底
def test_real_default_pool_is_non_empty():
    """不隔离任何东西：真实环境下必须至少解析出 eltdx 的 43 台池。"""
    out = resolve_quote_hosts()
    assert len(out) >= 40


# ---------------------------------------------------------------- 历史 Bug 回归
def test_eltdx_client_does_not_pass_port_kwarg():
    """★ TdxClient 没有 port 参数，历史代码 `TdxClient(host=, port=)` 必然 TypeError。

    这条测试守住该缺陷不再复发。
    """
    src = (
        Path(__file__).resolve().parents[1] / "data" / "eltdx_client.py"
    ).read_text(encoding="utf-8")
    assert "port=port" not in src
    assert re.search(r"TdxClient\(\s*host\s*=\s*\w+\s*,\s*port\s*=", src) is None


def test_tdxclient_accepts_hosts_kwarg():
    """构造不得因参数名非法而抛错（不联网，仅校验签名）。"""
    import inspect

    from eltdx import TdxClient

    params = inspect.signature(TdxClient.__init__).parameters
    assert "hosts" in params
    assert "port" not in params
