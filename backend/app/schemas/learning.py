"""Request/response contracts for the learning engine's HTTP-facing pieces.

There is no student-facing "what do I know" or "what's next" endpoint here --
the engine is consulted implicitly during question generation and grading.
Everything in this module either records an attempt or serves the dev
dashboard, the engine's only observability.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import SkillOrigin
from app.schemas.tutor import TutorResponse


class StrictModel(BaseModel):
    """Reject fields that are not part of the contract."""

    model_config = ConfigDict(extra="forbid")


class AttemptCreate(StrictModel):
    student_id: str
    session_id: str
    problem_id: str
    expected_skills: list[str]
    difficulty: float = Field(ge=0.0, le=1.0)
    correct: bool
    partial: bool = False
    hints_used: int = Field(default=0, ge=0)
    total_time_ms: int | None = None


class AttemptResult(StrictModel):
    attempt_id: str
    updated_skills: dict[str, float]


class SkillOverviewOut(StrictModel):
    skill_id: str
    skill_name: str
    description: str
    difficulty_band: float
    keywords: list[str]
    question_forms: list[str]
    origin: SkillOrigin
    created_at: datetime
    is_recent: bool
    accuracy: float | None
    attempts: int
    has_signal: bool


class SkillsOverviewResponse(StrictModel):
    """Every topic in a course with this student's attempt history.

    Dev dashboard only.
    """

    student_id: str
    course_id: str
    skills: list[SkillOverviewOut]


class WorkResponse(StrictModel):
    """What POST /work returns: the tutor's reading, and what it recorded.

    `attempt` is null when nothing was recorded -- a hint request rather than
    a mark, a canvas the tutor could not read, a problem with no skills, or a
    repeat of a problem already attempted.
    """

    tutor: TutorResponse
    attempt: AttemptResult | None = None
