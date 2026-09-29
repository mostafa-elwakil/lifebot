"""Core data models for Lifebot."""
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from datetime import datetime
import uuid


@dataclass
class Todo:
    title: str
    category: str = "Deep Work"
    completed: bool = False
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    priority: str = "medium"  # low / medium / high
    estimate_pomodoros: int = 1
    done_pomodoros: int = 0
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def _to_int(value, default: int) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def from_dict(d: dict) -> "Todo":
        return Todo(
            title=d.get("title", ""),
            category=d.get("category", "Deep Work"),
            completed=bool(d.get("completed", False)),
            id=d.get("id") or uuid.uuid4().hex[:8],
            priority=d.get("priority", "medium"),
            estimate_pomodoros=Todo._to_int(d.get("estimate_pomodoros", 1), 1),
            done_pomodoros=Todo._to_int(d.get("done_pomodoros", 0), 0),
            created_at=d.get("created_at") or datetime.now().isoformat(),
        )


@dataclass
class FocusSession:
    task: str
    category: str = "Deep Work"
    duration_min: int = 25
    kind: str = "focus"  # focus / short_break / long_break
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> dict:
        return asdict(self)
