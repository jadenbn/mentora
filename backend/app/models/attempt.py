"""An immutable record of one student attempt. Never edited after insert."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlmodel import SQLModel, Field, Column, JSON


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


class Attempt(SQLModel, table=True):
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
    stuck_requests: int = Field(default=0)
    total_time_ms: int | None = Field(default=None)
    # Only errors that survived the expected_skills guard. See
    # student_model_service.record_attempt for why unvalidated errors from
    # grading are dropped rather than stored.
    errors: list[dict] = Field(default_factory=list, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=_utcnow)
