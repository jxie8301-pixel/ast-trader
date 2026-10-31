"""种子验证套件的全局夹具。

只提供三样东西：副作用隔离、产物目录、跨用例的摘要汇聚点。
不引入任何网络会话级连接，避免改变既有测试的运行时行为。
"""

from __future__ import annotations

from typing import Any, Iterator

import pytest

import config
from helpers_seed import report_dir_for, today_str


@pytest.fixture(autouse=True)
def _ai_disabled_in_tests(monkeypatch: pytest.MonkeyPatch) -> None:
    """★ 测试一律关闭 AI 判断层 —— 这是确定性的最后一道保险。

    开发者本地 `.env` 里完全可能写了 `AST_AI_ENABLED=1`（那是给命令行用的），
    而 `config` 在 import 时就会读 `.env`。若不加这道强制关闭：
    · 测试会突发网络调用与 ~100s/标的 的延迟；
    · 判定变得不可复现，全部回归断言失去意义。

    AI 的行为由 `tests/test_ai_guard.py` / `test_ai_wiring.py` 用**注入**
    的 `AIEnrichment` 单独覆盖，不依赖真实开关。
    """
    monkeypatch.setattr(config, "AI_ENABLED", False)


@pytest.fixture(scope="session")
def seed_run_date() -> str:
    """本批跑批的日期戳，同时用于报告目录与摘要文件名。"""
    return today_str()


@pytest.fixture(scope="session")
def seed_report_dir(seed_run_date: str) -> Any:
    """``reports/seed_validation/<date>``，与既有研报目录隔离。"""
    return report_dir_for(seed_run_date)


@pytest.fixture(scope="session")
def isolated_cli(tmp_path_factory: Any) -> Iterator[Any]:
    """把 ``cli`` 中的微观分析器替换为「状态机缓存指向临时目录」的版本。

    三轮重构后 ``MainForceStateEngine`` 会持久化跨日状态；跑批若复用生产缓存，
    测试态会污染次日真实分析。这里只替换 ``cli.MicrostructureAnalyzer``，
    不动 ``config.CACHE_DIR``，以免把财报 zip 缓存一起搬走触发重下载。
    """
    import cli

    original = cli.MicrostructureAnalyzer
    tmp_file = tmp_path_factory.mktemp("mainforce") / "mainforce_history_state.json"

    from core.main_force_engine import MainForceStateEngine
    from core.microstructure import MicrostructureAnalyzer

    def _factory() -> MicrostructureAnalyzer:
        return MicrostructureAnalyzer(engine=MainForceStateEngine(cache_file=tmp_file))

    cli.MicrostructureAnalyzer = _factory  # type: ignore[assignment]
    try:
        yield cli
    finally:
        cli.MicrostructureAnalyzer = original  # type: ignore[assignment]


@pytest.fixture(scope="session")
def seed_entries() -> list[dict[str, Any]]:
    """跨用例汇聚每只种子的摘要条目，供聚合用例落盘与统计。"""
    return []
