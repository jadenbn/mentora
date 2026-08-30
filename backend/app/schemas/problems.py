"""Generated problems and the document context that grounds them."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class GenerateQuestionRequest(StrictModel):
    document_id: str = Field(min_length=1)
    question_request: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=1_000),
    ]


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
    """Provider output before source IDs have been verified by the workflow."""

    prompt: str = Field(min_length=1, max_length=8_000)
    grounding_chunk_ids: list[str] = Field(min_length=1, max_length=8)
