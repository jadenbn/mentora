"""A student's live mastery estimate for one skill."""

from __future__ import annotations

from datetime import datetime

from sqlmodel import SQLModel, Field


class SkillState(SQLModel, table=True):
    student_id: str = Field(primary_key=True)
    skill_id: str = Field(primary_key=True)
    course_id: str = Field(index=True)
    mastery: float = Field(default=0.5)
    attempts: int = Field(default=0)
    correct_unassisted: int = Field(default=0)
    streak: int = Field(default=0)
    # Null until the skill is actually practised. A state created by
    # prerequisite bleed has a mastery estimate but no last-seen moment, and
    # stamping it with "now" would reset its staleness and decay clock.
    last_seen: datetime | None = Field(default=None)
