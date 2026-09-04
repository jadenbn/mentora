from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.problems import ProblemContext


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Space(StrictModel):
    id: str
    course_id: str
    title: str
    problem: ProblemContext | None = None
    created_at: datetime
    updated_at: datetime


class SpaceCreate(StrictModel):
    title: str | None = Field(default=None, max_length=200)
    problem_id: str | None = Field(default=None, min_length=1)


class SpaceUpdate(StrictModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
