"""Request/response contracts for the learning engine API."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import MisconceptionTag
from app.schemas.problems import GeneratedProblem


class StrictModel(BaseModel):
    """Reject fields that are not part of the contract."""

    model_config = ConfigDict(extra="forbid")


class ErrorReport(StrictModel):
    skill_id: str
    misconception: MisconceptionTag
    step_index: int | None = None


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
    errors: list[ErrorReport] = []


class AttemptResult(StrictModel):
    attempt_id: str
    updated_skills: dict[str, float]
    dropped_errors: int


class SkillStateOut(StrictModel):
    skill_id: str
    skill_name: str
    mastery: float
    confidence: float
    attempts: int
    top_misconceptions: list[str]


class StudentModelResponse(StrictModel):
    student_id: str
    course_id: str
    skills: list[SkillStateOut]


class SkillOverviewOut(StrictModel):
    skill_id: str
    skill_name: str
    description: str
    difficulty_band: float
    prereqs: list[str]
    mastery: float
    confidence: float
    attempts: int
    unlocked: bool
    has_state: bool
    top_misconceptions: list[str]


class SkillsOverviewResponse(StrictModel):
    """Every skill in a course with this student's progress and unlock state.

    Unlike StudentModelResponse, untouched skills are included at their seed
    mastery so a dashboard can render the whole taxonomy, not just what was
    attempted. next_skill_id is what selection would pick right now.
    """

    student_id: str
    course_id: str
    skills: list[SkillOverviewOut]
    next_skill_id: str | None = None


class GenerationSpec(StrictModel):
    skill_id: str
    skill_name: str
    skill_description: str
    target_difficulty: float
    target_misconception: MisconceptionTag | None = None
    avoid_forms: list[str] = []
    retrieval_query: str = ""
    prereq_mastery: dict[str, float] = {}
    is_review: bool = False


class NextProblemResponse(StrictModel):
    """A generated problem plus the spec that produced it.

    The client posts the attempt back with the returned problem_id; the skills
    it exercised are looked up server-side from problem_skills, so the client
    never has to (and no longer can) attribute the attempt itself.
    """

    problem: GeneratedProblem
    spec: GenerationSpec
