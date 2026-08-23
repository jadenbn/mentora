"""A student's live mastery estimate for one skill."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlmodel import SQLModel, Field, Column, JSON


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class SkillState(SQLModel, table=True):
    student_id: str = Field(primary_key=True)
    skill_id: str = Field(primary_key=True)
    course_id: str = Field(index=True)
    mastery: float = Field(default=0.5)
    attempts: int = Field(default=0)
    correct_unassisted: int = Field(default=0)
    streak: int = Field(default=0)
    misconception_counts: dict[str, int] = Field(default_factory=dict, sa_column=Column(JSON))
    last_seen: datetime = Field(default_factory=_utcnow)
