"""Data health, interface tracking and exception audit for AST-Trader.
Strictly records interface call status, latency, exceptions and information gaps.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any
import traceback


@dataclass
class InterfaceCallRecord:
    name: str                        # 接口名称，如 "资产负债表 (F10 zcfzb)"
    channel: str                     # 通道/来源，如 "TDX L2 / eltdx.f10"
    status: str                      # "SUCCESS" | "FAILED" | "EMPTY" | "DEGRADED"
    record_count: int = 0            # 成功获取的记录数
    error_type: str | None = None    # 异常类型名
    error_message: str | None = None # 异常详细报错
    trace_snippet: str | None = None # 异常简要堆栈
    note: str = ""                   # 业务影响与数据降级说明

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class DataHealthTracker:
    """数据源健康度与接口异常追踪器。"""

    def __init__(self) -> None:
        self.records: list[InterfaceCallRecord] = []

    def record_success(self, name: str, channel: str, count: int = 1, note: str = "") -> None:
        """记录接口调用成功。"""
        self.records.append(InterfaceCallRecord(
            name=name,
            channel=channel,
            status="SUCCESS",
            record_count=count,
            note=note or f"正常返回 {count} 条记录",
        ))

    def record_empty(self, name: str, channel: str, note: str = "") -> None:
        """记录接口联通但返回空数据（真无记录，非报错）。"""
        self.records.append(InterfaceCallRecord(
            name=name,
            channel=channel,
            status="EMPTY",
            record_count=0,
            note=note or "接口联通但返回空数据集",
        ))

    def record_failure(
        self,
        name: str,
        channel: str,
        exc: Exception,
        note: str = "",
        fatal: bool = False,
    ) -> None:
        """记录接口异常失败，严禁静默 pass。"""
        err_type = type(exc).__name__
        err_msg = str(exc) or err_type
        tb_lines = traceback.format_exception(type(exc), exc, exc.__traceback__)
        snippet = "".join(tb_lines[-2:]).strip() if tb_lines else err_msg

        self.records.append(InterfaceCallRecord(
            name=name,
            channel=channel,
            status="FAILED",
            record_count=0,
            error_type=err_type,
            error_message=err_msg,
            trace_snippet=snippet,
            note=note or f"取数遭遇异常: [{err_type}] {err_msg}",
        ))

    @property
    def has_errors(self) -> bool:
        return any(r.status == "FAILED" for r in self.records)

    @property
    def failed_records(self) -> list[InterfaceCallRecord]:
        return [r for r in self.records if r.status == "FAILED"]

    def summary(self) -> dict[str, Any]:
        """生成数据链路健康度总结报告。"""
        total = len(self.records)
        success = sum(1 for r in self.records if r.status == "SUCCESS")
        failed = sum(1 for r in self.records if r.status == "FAILED")
        empty = sum(1 for r in self.records if r.status == "EMPTY")
        return {
            "total_interfaces": total,
            "success_count": success,
            "failed_count": failed,
            "empty_count": empty,
            "has_errors": self.has_errors,
            "failed_details": [r.to_dict() for r in self.failed_records],
            "all_records": [r.to_dict() for r in self.records],
        }
