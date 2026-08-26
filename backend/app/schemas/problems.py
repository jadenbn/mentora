"""Generated problems and the document context that grounds them."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.schemas.taxonomy import RawSkillEntry


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class GenerateQuestionRequest(StrictModel):
    student_id: str = Field(min_length=1)
    document_id: str = Field(min_length=1)
    #: What the student typed, or empty/omitted to let the engine pick a
    #: topic (services/selection.py) and steer difficulty from it instead.
    question_request: Annotated[
        str,
        StringConstraints(strip_whitespace=True, max_length=1_000),
    ] = ""


class ProblemContext(StrictModel):
    id: str = Field(min_length=1)
    course_id: str = Field(min_length=1)
    document_id: str = Field(min_length=1)
    source: Literal["generated"] = "generated"
    prompt: str = Field(min_length=1, max_length=8_000)


class GeneratedProblem(ProblemContext):
    created_at: datetime


class GroundingChunk(StrictModel):
    chunk_id: str
    page: int = Field(ge=1)
    text: str = Field(min_length=1)


class GroundedProblem(StrictModel):
    problem: ProblemContext
    chunks: list[GroundingChunk]


class QuestionPlan(StrictModel):
    """Provider output before source IDs have been verified by the workflow.

    skills: every skill this question exercises, usually one but sometimes a
    few for a composite problem. Each entry either names an existing course
    skill (by id, offered as context) or names a new one -- see
    QuestionService._attribute_skills for how each is resolved.
    """

    prompt: str = Field(min_length=1, max_length=8_000)
    grounding_chunk_ids: list[str] = Field(min_length=1, max_length=8)
    skills: list[RawSkillEntry] = Field(min_length=1, max_length=4)


class AttributedSkill(StrictModel):
    """A persisted skill this generated problem was attributed to — enough
    for a client to show what it's practicing and to grade an attempt
    against it without a second lookup."""

    id: str
    name: str
    difficulty_band: float = Field(ge=0.0, le=1.0)


class GeneratedProblemResponse(StrictModel):
    """A generated problem plus the skill(s) it was attributed to.

    The client posts the attempt back with problem.id; expected_skills is
    still resolved server-side from problem_skills -- this is only what the
    client uses to render a badge. The client never gets to name the skills
    an attempt moves.
    """

    problem: GeneratedProblem
    skills: list[AttributedSkill]
