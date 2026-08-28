"""An immutable record of one student attempt. Never edited after insert."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlmodel import SQLModel, Field, Column, JSON, UniqueConstraint


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _new_id() -> str:
    return uuid.uuid4().hex


class Attempt(SQLModel, table=True):
    # One attempt per problem per student. record_attempt returns the original
    # on a repeat rather than inserting; this is the backstop for anything
    # that writes around it.
    __table_args__ = (UniqueConstraint("student_id", "problem_id"),)

    id: str = Field(default_factory=_new_id, primary_key=True)
    student_id: str = Field(index=True)
    course_id: str = Field(index=True)
    session_id: str
    problem_id: str
    expected_skills: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    difficulty: float
    correct: bool
    partial: bool = Field(default=False)
    hints_used: int = Field(default=0)
    #: A small controlled vocabulary the tutor may tag an incorrect or
    #: partial answer with (see schemas.tutor.ErrorTag). Null on a correct
    #: or uncertain grading, and on anything graded before this existed.
    #: Nothing reads this yet -- it exists to start accumulating a signal
    #: that takes weeks of usage to become useful.
    error_tag: str | None = Field(default=None)
    created_at: datetime = Field(default_factory=_utcnow)
