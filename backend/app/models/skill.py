"""A skill: one addressable unit of a course's taxonomy."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlmodel import SQLModel, Field, Column, JSON

from app.models.enums import SkillOrigin


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Skill(SQLModel, table=True):
    id: str = Field(primary_key=True)  # "calc1.derivatives.chain-rule"
    course_id: str = Field(index=True)
    name: str
    description: str
    difficulty_band: float = Field(ge=0.0, le=1.0)
    prereqs: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    # Retrieval vocabulary (words a textbook uses that the name does not) and
    # the question shapes this skill can take. Both optional in course JSON.
    keywords: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    question_forms: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    origin: SkillOrigin = Field(default=SkillOrigin.SEED)
    # merge_generated never rewrites this on update, so it stays the moment
    # the skill first appeared — what the dashboard uses to flag a skill as
    # freshly emerged rather than part of the original taxonomy.
    created_at: datetime = Field(default_factory=_utcnow)
