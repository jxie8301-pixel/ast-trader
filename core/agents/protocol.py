"""A2A (Agent-to-Agent) Protocol & Shared Blackboard for AST-Trader.
Inspired by Nous Research Hermes Agent architecture.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class AgentRole(str, Enum):
    """投研多智能体角色定义."""
    BULL_THESIS = "BullThesisAgent"           # 多头推演：发掘催化剂、订单增量与估值弹性
    RISK_CHALLENGER = "RiskChallengerAgent"   # 空头证伪：财务红旗排雷、周期拐点、下行陷阱
    CAPITAL_MICRO = "CapitalMicroAgent"       # 资金盘口：筹码密集峰、微观大单意图、主力行为
    DATA_AUDITOR = "ChiefDataAuditorAgent"     # 数据保真：事实核验底座、防范幻觉打脸
    CIO_LEAD = "CIOLogicArbiterAgent"         # 投决会主席：仲裁冲突、全篇战术仓位锁定


class MessageType(str, Enum):
    """协议消息类型."""
    PROPOSAL = "PROPOSAL"             # 提出初始观点/红旗提名
    CHALLENGE = "CHALLENGE"           # 对立智能体提出质询
    FACT_DEFENSE = "FACT_DEFENSE"     # 以底层客观事实驳回质询或伪红旗
    CONCESSION = "CONCESSION"         # 修正或让步
    CONSENSUS = "CONSENSUS"           # 达成共识
    OVERRIDE = "OVERRIDE"             # 投决会主席行使最终强制裁定权


@dataclass
class ProtocolMessage:
    """A2A 结构化通信消息帧."""
    sender: AgentRole
    recipient: AgentRole | str
    msg_type: MessageType
    topic: str
    content: str
    data_payload: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "sender": self.sender.value,
            "recipient": self.recipient.value if isinstance(self.recipient, AgentRole) else self.recipient,
            "msg_type": self.msg_type.value,
            "topic": self.topic,
            "content": self.content,
            "data_payload": self.data_payload,
            "timestamp": self.timestamp,
        }


class SharedBlackboard:
    """智能体投决会共享黑板 (Shared Memory Blackboard)."""

    def __init__(self, ground_truth: dict[str, Any] | None = None) -> None:
        self.ground_truth: dict[str, Any] = ground_truth or {}
        self.messages: list[ProtocolMessage] = []
        self.proposals: dict[str, Any] = {}
        self.active_red_flags: list[Any] = []
        self.intercepted_hallucinations: list[dict[str, Any]] = []
        self.consensus_verdicts: dict[str, Any] = {}

    def post_message(self, msg: ProtocolMessage) -> None:
        self.messages.append(msg)

    def register_ground_truth(self, key: str, value: Any) -> None:
        self.ground_truth[key] = value

    def get_ground_truth(self, key: str, default: Any = None) -> Any:
        return self.ground_truth.get(key, default)

    def intercept_flag(self, flag_title: str, reason: str, evidence: str) -> None:
        self.intercepted_hallucinations.append({
            "title": flag_title,
            "reason": reason,
            "evidence": evidence,
            "timestamp": time.time(),
        })
