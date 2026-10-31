"""degraded — 缺值语义集中声明。

**为什么要有这一层**：本项目确立 NFR-02 血律 —— 「缺失字段严格置 `None`，
严禁填充默认值 `0`，缺失特征的规则自动弃权，不伪装成有效信号」。

道理很硬：`pledge_ratio` 曾因兜底成 `0.0` 而**伪造了"无质押"这一事实**，
与数据真实缺失不可区分；`_safe_float(row.get(k)) or 0` 会让 Altman Z 在
缺字段时算出一个"看起来正常"的分值 —— 这类错**不报错，只在印出假结论时才发现**。

但"置 None"如果只是散落各处地写 `None`，就丢失了**为什么缺失**的信息，
下游无法区分"接口不提供"与"这次没取到"。所以借鉴上游的 `DEGRADED` 思路：
**把缺值语义集中声明在一处**，取数侧声明原因，报告侧一次性列出。

★ 与上游的差别（不照抄）：上游 `DEGRADED` 只是一条注释字典，靠人工维护；
这里做成可调用的声明接口，声明动作本身即产出 `None`，**让"忘记声明"比
"声明"更麻烦**，从而保证纪律可执行、可测试。

用法（取数侧）：
    from data import degraded
    turnover = degraded.missing("turnover_rate_f", "eltdx 该口径未提供，绝不猜")

用法（报告/自检侧）：
    for field, why in degraded.degraded_notes().items():
        print(f"{field}: {why}")
"""
from __future__ import annotations

import math
import threading
from typing import Any

__all__ = [
    "missing", "as_missing", "is_missing", "note", "degraded_notes", "reset",
]

_LOCK = threading.Lock()
_NOTES: dict[str, str] = {}


def is_missing(value: Any) -> bool:
    """判定是否为"缺值"。

    覆盖三种最常见的伪装形态：
    · `None`（真正的缺）
    · `float('nan')`（pandas 空值的默认形态）
    · 空字符串（文本字段取到空壳）
    ★ 注意 `0` 与 `0.0` **不算缺值** —— 它是真实取到的数。
    """
    if value is None:
        return True
    if isinstance(value, float) and math.isnan(value):
        return True
    if isinstance(value, str) and not value.strip():
        return True
    return False


def missing(field: str, reason: str) -> None:
    """声明 `field` 缺失并返回 `None`。

    返回 `None` 而非抛异常 —— 缺值是**常态**，不该中断整条流水线；
    但必须留下原因，供门控与报告侧回溯。
    """
    if not reason or not reason.strip():
        raise ValueError(f"声明缺失必须给出原因，否则与静默填 0 无异: {field}")
    with _LOCK:
        _NOTES[field] = reason.strip()
    return None


def as_missing(field: str, value: Any, reason: str) -> Any:
    """值若为空则声明缺失并返回 `None`；否则原样返回。

    用于把"取到了空壳"与"取到了真值"收敛到同一条路径上，
    避免调用方写出 `x if x else 0` 这类又回到填充默认值的写法。
    """
    if is_missing(value):
        return missing(field, reason)
    return value


def note(field: str) -> str | None:
    """取某个字段的缺失原因；未声明过则返回 `None`。"""
    with _LOCK:
        return _NOTES.get(field)


def degraded_notes() -> dict[str, str]:
    """返回全部缺失声明的快照（field → reason）。"""
    with _LOCK:
        return dict(_NOTES)


def reset() -> None:
    """清空全部声明。仅供测试隔离与新一轮 run 开始时调用。"""
    with _LOCK:
        _NOTES.clear()
