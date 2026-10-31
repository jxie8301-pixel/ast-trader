"""数据层修复回归：缺值语义集中声明、代码归一、异常归一、就绪门。

对应计划 P0。要点是**锁死两类历史缺陷不再复发**：
1. `normalize_code` 用首位数字判市场，把北交所 920xxx 误判成沪市；
2. 缺值被兜底成 `0`/`0.0`，与真实数据不可区分（NFR-02）。
"""
import pytest

from data import degraded
from data.eltdx_client import (
    EltdxError,
    EltdxFetchError,
    EltdxFormatError,
    EltdxUnavailable,
    extension_ready,
    extension_reason,
    normalize_code,
    require_extension,
    with_retry,
)


def _sdk_exc(name: str) -> type[BaseException]:
    """取 eltdx SDK 的真实异常类。

    必须用真实类而非本地桩类：`_raise_as_ours` 按 **MRO 类名**判定归一目标
    （eltdx 未安装时无法 import 其异常，只能靠名字匹配），本地桩类名字对不上
    会测出假阴性。
    """
    ex = pytest.importorskip("eltdx.exceptions")
    return getattr(ex, name)


# ---------------------------------------------------------------- 缺值语义
def test_missing_returns_none_and_records_reason():
    assert degraded.missing("turnover_rate_f", "eltdx 该口径未提供") is None
    assert degraded.note("turnover_rate_f") == "eltdx 该口径未提供"


def test_missing_requires_reason():
    """不给原因的缺失声明必须被拒绝 —— 否则与静默填 0 无异。"""
    with pytest.raises(ValueError):
        degraded.missing("some_field", "   ")


def test_is_missing_distinguishes_zero_from_missing():
    """0 是真实取到的值，绝不能被当成缺失。"""
    assert degraded.is_missing(0) is False
    assert degraded.is_missing(0.0) is False
    assert degraded.is_missing(None) is True
    assert degraded.is_missing(float("nan")) is True
    assert degraded.is_missing("") is True


def test_as_missing_passes_real_value_through():
    assert degraded.as_missing("pe", 12.5, "unused") == 12.5
    assert degraded.as_missing("pe", None, "接口未提供") is None
    assert degraded.note("pe") == "接口未提供"


def test_degraded_notes_is_snapshot_and_resettable():
    degraded.reset()
    degraded.missing("a", "原因 A")
    snapshot = degraded.degraded_notes()
    snapshot["a"] = "被外部篡改"
    assert degraded.note("a") == "原因 A"      # 快照防御
    degraded.reset()
    assert degraded.degraded_notes() == {}


# ---------------------------------------------------------------- 代码归一
@pytest.mark.parametrize(
    "raw,eltdx_code,ts_code",
    [
        ("920002", "bj920002", "920002.BJ"),      # ★ 北交所迁移码段，旧实现误判为 sh
        ("900001", "sh900001", "900001.SH"),      # 沪市 B 股
        ("200011", "sz200011", "200011.SZ"),      # 深市 B 股
        ("688001", "sh688001", "688001.SH"),      # 科创板
        ("000001", "sz000001", "000001.SZ"),
        ("600519.SH", "sh600519", "600519.SH"),
        ("sh600519", "sh600519", "600519.SH"),    # 兼容历史调用方直接传 eltdx 形态
    ],
)
def test_normalize_code_market_inference(raw, eltdx_code, ts_code):
    assert normalize_code(raw) == (eltdx_code, ts_code)


def test_normalize_code_rejects_garbage():
    with pytest.raises(ValueError):
        normalize_code("")


# ---------------------------------------------------------------- 异常归一
def test_with_retry_returns_value_on_success():
    assert with_retry(lambda: 42, what="unit", retry_delay=0) == 42


def test_with_retry_normalizes_retryable_exhaustion():
    """重试耗尽必须抛本项目异常，不能把原始 SDK 异常透出去。"""
    calls = {"n": 0}

    def boom():
        calls["n"] += 1
        raise _sdk_exc("TransportError")("连接断开")

    with pytest.raises(EltdxFetchError):
        with_retry(boom, what="unit.bars", max_retries=3, retry_delay=0)
    assert calls["n"] == 3


def test_with_retry_does_not_retry_format_error():
    """格式错误重试无意义：必须一次即失败，且归一为 EltdxFormatError。"""
    calls = {"n": 0}

    def boom():
        calls["n"] += 1
        raise _sdk_exc("ResourceFormatError")("zip 损坏")

    with pytest.raises(EltdxFormatError):
        with_retry(boom, what="unit.fin", max_retries=3, retry_delay=0)
    assert calls["n"] == 1


def test_with_retry_maps_unsupported_command_to_fetch_error():
    with pytest.raises(EltdxFetchError):
        with_retry(lambda: (_ for _ in ()).throw(_sdk_exc("UnsupportedCommandError")("未迁移")),
                   what="unit.cmd", retry_delay=0)


def test_exception_hierarchy_is_self_owned():
    """异常基类必须是自有的 RuntimeError，不随 SDK 版本漂移。"""
    assert EltdxError.__mro__[1] is RuntimeError
    assert issubclass(EltdxUnavailable, EltdxError)
    assert issubclass(EltdxFetchError, EltdxError)
    assert issubclass(EltdxFormatError, EltdxFetchError)


# ---------------------------------------------------------------- 就绪门
def test_extension_gate_surface_exists():
    assert isinstance(extension_ready(), bool)
    assert isinstance(extension_reason(), str)
    if extension_ready():
        require_extension()          # 就绪时不应抛
    else:
        with pytest.raises(EltdxUnavailable):
            require_extension()
