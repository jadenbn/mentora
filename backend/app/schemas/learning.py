"""Request/response contracts for the learning engine API."""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.models.enums import MisconceptionTag


class ErrorReport(BaseModel):
    skill_id: str
    misconception: MisconceptionTag
    step_index: int | None = None


class AttemptCreate(BaseModel):
    student_id: str
    session_id: str
    problem_id: str
    expected_skills: list[str]
    difficulty: float = Field(ge=0.0, le=1.0)
    correct: bool
    partial: bool = False
    hints_used: int = Field(default=0, ge=0)
    stuck_requests: int = Field(default=0, ge=0)
    total_time_ms: int | None = None
    errors: list[ErrorReport] = Field(default_factory=list)


class AttemptResult(BaseModel):
    attempt_id: str
    updated_skills: dict[str, float]
    dropped_errors: int


class SkillStateOut(BaseModel):
    skill_id: str
    skill_name: str
    mastery: float
    confidence: float
    attempts: int
    top_misconceptions: list[str]


class StudentModelResponse(BaseModel):
    student_id: str
    course_id: str
    skills: list[SkillStateOut]


class GenerationSpec(BaseModel):
    skill_id: str
    skill_name: str
    skill_description: str
    target_difficulty: float
    target_misconception: MisconceptionTag | None = None
    avoid_forms: list[str] = Field(default_factory=list)
    prereq_mastery: dict[str, float] = Field(default_factory=dict)
    is_review: bool = False
