"""行情画像批量吞吐（L1）测试。

★ 核心守的是两件事：
1. **换手率必须有真实值**。改造前 Tier 1 的 8%~25% 换手率门槛是一条死代码 ——
   ``QuoteSnapshot`` 根本没有 ``turnover_ratio`` 字段，而 pipeline 只装了四个键。
   现在换手率由 ``stock_profile_table`` 提供，门槛才真正生效。
2. **批次失败不得静默缩小母池**。失败批次必须记为 ``PROFILE_MISSING`` 并计入
   覆盖率缺口，否则"全市场"会悄悄退化成"跑成功的那部分市场"。
"""
from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace

import pytest

import data.eltdx_client as client_mod
from screener import profile_batch as pb


def _mk_row(full_code: str, *, turnover=5.0, ipo="2013-09-18"):
    return SimpleNamespace(
        full_code=full_code, code=full_code[2:], name=f"N-{full_code}",
        exchange=full_code[:2], board="sse_main_board", category="a_share",
        last_price=10.0, pre_close_price=9.5, open_price=9.6,
        high_price=10.5, low_price=9.4, change_pct=5.26, amount=1.2e9,
        volume_hand=120000, turnover_rate=turnover,
        circulating_shares=1e8, total_shares=1.2e8,
        circulating_market_value=1.0e9, total_market_value=1.2e9,
        eps=0.5, ipo_date=ipo,
    )


# ---------------------------------------------------------------- 纯函数
def test_chunk_codes_splits_evenly_and_keeps_remainder() -> None:
    assert pb.chunk_codes([1, 2, 3, 4, 5, 6, 7], 3) == [[1, 2, 3], [4, 5, 6], [7]]


def test_chunk_codes_never_returns_empty_for_non_empty_input() -> None:
    assert pb.chunk_codes(["a"], 200) == [["a"]]
    assert pb.chunk_codes([], 200) == []


def test_opt_float_missing_becomes_none_not_zero() -> None:
    """★ NFR-02：缺失一律 None，严禁 ``or 0.0``。"""
    assert pb._opt_float(None) is None
    assert pb._opt_float("bad") is None
    assert pb._opt_float(float("nan")) is None
    assert pb._opt_float(0.0) == 0.0        # 真实的 0 必须保留
    assert pb._opt_float("1.5") == 1.5


def test_row_to_snapshot_keeps_missing_fields_as_none() -> None:
    snap = pb._row_to_snapshot(_mk_row("sh600519", turnover=None, ipo=None))
    assert snap is not None
    assert snap.full_code == "sh600519"
    assert snap.turnover_rate is None       # 不是 0.0
    assert snap.ipo_date is None
    assert snap.change_pct == pytest.approx(5.26)


def test_row_to_snapshot_rejects_row_without_full_code() -> None:
    assert pb._row_to_snapshot(SimpleNamespace(full_code=None)) is None


def test_turnover_rate_is_the_field_that_fixes_the_dead_rule() -> None:
    """换手率真实值必须进到 Tier 1 的输入字典里 —— 这是死代码修复的落点。"""
    snap = pb._row_to_snapshot(_mk_row("sz000333", turnover=0.345))
    assert snap is not None
    d = snap.to_dict()
    assert d["turnover_rate"] == pytest.approx(0.345)
    assert d["total_market_value"] > 0


# ---------------------------------------------------------------- 批量吞吐
class _FakeHelpers:
    def __init__(self, fail_calls: set[int], drop_codes: set[str] | None = None) -> None:
        self.fail_calls = fail_calls
        self.drop_codes = drop_codes or set()
        self.calls = 0

    def stock_profile_table(self, codes):
        self.calls += 1
        if self.calls in self.fail_calls:
            raise ConnectionError(f"批次 {self.calls} 连接中断")
        rows = [_mk_row(c) for c in codes if c not in self.drop_codes]
        return SimpleNamespace(rows=rows, count=len(rows))


@contextmanager
def _fake_open(client):
    yield client


@pytest.fixture
def patch_client(monkeypatch):
    def _install(fail_calls: set[int], drop_codes: set[str] | None = None):
        helpers = _FakeHelpers(fail_calls, drop_codes)
        client = SimpleNamespace(helpers=helpers)
        monkeypatch.setattr(client_mod, "open_client", lambda *a, **k: _fake_open(client))
        # 绕开真实重试（带指数退避，会让测试变慢）；异常归一不是本用例的关注点
        monkeypatch.setattr(client_mod, "with_retry", lambda fn, **k: fn())
        return helpers
    return _install


def test_fetch_profiles_success(patch_client) -> None:
    patch_client(fail_calls=set())
    mapping, stats = pb.fetch_profiles(["sh600519", "sz000333"], batch_size=2)

    assert stats["requested"] == 2
    assert stats["returned"] == 2
    assert stats["missing"] == 0
    assert stats["failed_batches"] == 0
    assert set(mapping) == {"sh600519", "sz000333"}


def test_failed_batch_is_recorded_not_silently_dropped(patch_client) -> None:
    """★ 批次失败：对应代码记为 PROFILE_MISSING，绝不静默缩小母池。"""
    patch_client(fail_calls={2})
    codes = [f"sh60{i:04d}" for i in range(6)]
    mapping, stats = pb.fetch_profiles(codes, batch_size=3)

    assert stats["failed_batches"] == 1
    assert stats["batches"] == 2
    assert stats["missing"] == 3
    assert set(stats["missing_codes"]) == set(codes[3:])
    # 成功的批次必须完整保留
    assert set(mapping) == set(codes[:3])


def test_all_batches_failing_keeps_missing_equal_to_requested(patch_client) -> None:
    patch_client(fail_calls={1, 2})
    codes = [f"sh60{i:04d}" for i in range(4)]
    mapping, stats = pb.fetch_profiles(codes, batch_size=2)

    assert mapping == {}
    assert stats["missing"] == stats["requested"] == 4


def test_empty_input_is_noop(patch_client) -> None:
    patch_client(fail_calls=set())
    mapping, stats = pb.fetch_profiles([], batch_size=10)
    assert mapping == {}
    assert stats["requested"] == 0 and stats["batches"] == 0


def test_batch_size_default_comes_from_config(patch_client) -> None:
    helpers = patch_client(fail_calls=set())
    pb.fetch_profiles([f"sh60{i:04d}" for i in range(10)])
    # 10 只 < 默认 200，应只发 1 批
    assert helpers.calls == 1


def test_health_tracker_records_degraded_on_partial_failure(patch_client) -> None:
    class _Health:
        def __init__(self) -> None:
            self.degraded = 0
            self.success = 0
            self.failures = 0

        def record_degraded(self, *a, **k) -> None:
            self.degraded += 1

        def record_success(self, *a, **k) -> None:
            self.success += 1

        def record_failure(self, *a, **k) -> None:
            self.failures += 1

    health = _Health()
    patch_client(fail_calls={1})
    pb.fetch_profiles([f"sh60{i:04d}" for i in range(4)], batch_size=2, health=health)

    assert health.failures == 1
    assert health.degraded == 1
    assert health.success == 0
