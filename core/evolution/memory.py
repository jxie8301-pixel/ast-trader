"""Evolution Memory (进化记忆与经验库).
Maintains learned lessons, historical edge cases, and dynamic agent priors.
"""
from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger("ast_trader.core.evolution.memory")

MEMORY_DIR = Path("data/evolution")
MEMORY_FILE = MEMORY_DIR / "lessons_memory.json"

DEFAULT_SEED_LESSONS = [
    {
        "lesson_id": "LESSON_001_RESISTANCE_BOX",
        "category": "TACTICAL_PIVOTS",
        "rule": "突破压力位应锚定近20日震荡平台箱体上沿，严禁直接取60日历史极值顶导致买点严重虚高脱离实盘",
        "evidence_case": "002850 科达利历史大顶 200.56 元误设为突破买点",
        "confidence_discount": 0.0,
    },
    {
        "lesson_id": "LESSON_002_TIERED_DEFENSE",
        "category": "RISK_CONTROL",
        "rule": "强支撑与止损线重叠时必须以 20 日均线为第一动态预警线，强支撑为极限止损，消除同价重复结巴",
        "evidence_case": "002850 依托强支撑线 139.68 元或防守线 139.68 元重复结巴",
        "confidence_discount": 0.0,
    },
    {
        "lesson_id": "LESSON_003_EMPTY_POSITION_HARMONY",
        "category": "CONSISTENCY",
        "rule": "总决断仓位为0%或观望回避时，资金博弈雷达全篇严禁出现维持中性底仓字样，必须绝对同向防御",
        "evidence_case": "002850 决断卡建议仓位 0% 但资金雷达声称维持中性底仓",
        "confidence_discount": 0.0,
    },
    {
        "lesson_id": "LESSON_004_TRUTH_DEFENSE",
        "category": "AUDIT_HARMONIZATION",
        "rule": "正文已有真实毛利率净利率ROE与主营占比时，强制拦截AI语义盲审提出的数据缺失伪红旗，禁止公开打脸",
        "evidence_case": "002850 看板已计算毛利 21.8% / ROE 13.4%，排雷卡仍报告毛利未提供",
        "confidence_discount": 0.0,
    },
    {
        "lesson_id": "LESSON_005_BEAR_TRAP_DISCOUNT_ON_ICE",
        "category": "MICROSTRUCTURE_PRIOR",
        "rule": "在大盘弱势退潮且上方套牢盘密集时，主力知情资金托底买盘极易演化为真破位，假破位诱空置信度必须折价",
        "evidence_case": "退潮期大单托底常伴随阴跌补跌",
        "confidence_discount": 0.35,
    },
]


@dataclass
class LessonRecord:
    lesson_id: str
    category: str
    rule: str
    evidence_case: str
    confidence_discount: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> LessonRecord:
        return cls(**data)


class EvolutionMemory:
    """系统进化记忆库."""

    def __init__(self, memory_path: Path | str = MEMORY_FILE) -> None:
        self.memory_path = Path(memory_path)
        self.memory_path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_file()

    def _ensure_file(self) -> None:
        if not self.memory_path.exists():
            with open(self.memory_path, "w", encoding="utf-8") as f:
                json.dump(DEFAULT_SEED_LESSONS, f, ensure_ascii=False, indent=2)

    def load_all_lessons(self) -> list[LessonRecord]:
        try:
            with open(self.memory_path, "r", encoding="utf-8") as f:
                raw = json.load(f)
                return [LessonRecord.from_dict(item) for item in raw]
        except Exception as exc:
            logger.warning(f"读取经验记忆库异常: {exc}")
            return [LessonRecord.from_dict(d) for d in DEFAULT_SEED_LESSONS]

    def save_all_lessons(self, lessons: list[LessonRecord]) -> None:
        try:
            with open(self.memory_path, "w", encoding="utf-8") as f:
                json.dump([l.to_dict() for l in lessons], f, ensure_ascii=False, indent=2)
        except Exception as exc:
            logger.error(f"保存经验记忆库失败: {exc}")

    def add_lesson(self, lesson: LessonRecord) -> None:
        lessons = self.load_all_lessons()
        existing_idx = next((i for i, l in enumerate(lessons) if l.lesson_id == lesson.lesson_id), None)
        if existing_idx is not None:
            lessons[existing_idx] = lesson
        else:
            lessons.append(lesson)
        self.save_all_lessons(lessons)
