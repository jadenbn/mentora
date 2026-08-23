"""A skill: one addressable unit of a course's taxonomy."""

from __future__ import annotations

from sqlmodel import SQLModel, Field, Column, JSON

from app.models.enums import SkillOrigin


class Skill(SQLModel, table=True):
    id: str = Field(primary_key=True)  # "calc1.derivatives.chain-rule"
    course_id: str = Field(index=True)
    name: str
    description: str
    difficulty_band: float = Field(ge=0.0, le=1.0)
    prereqs: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    origin: SkillOrigin = Field(default=SkillOrigin.SEED)
