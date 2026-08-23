"""Slow-moving, course-scoped facts about a student."""

from __future__ import annotations

from sqlmodel import SQLModel, Field


class StudentProfile(SQLModel, table=True):
    student_id: str = Field(primary_key=True)
    course_id: str = Field(primary_key=True)
    # Seeds a never-attempted skill's mastery so cold start isn't blind.
    global_ability: float = Field(default=0.5)
    hint_reliance: float = Field(default=0.0)
