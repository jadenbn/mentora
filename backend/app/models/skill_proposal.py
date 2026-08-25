"""A skill a model proposed that the course taxonomy does not yet have.

Proposals are quarantine. Question generation runs on the read path and can
name skills the course has never heard of; writing those straight into Skill
made the taxonomy an append-only log authored by a model, keyed by slug
equality on names the model chose. Selection never sees a proposal, so no
amount of proposing can move what a student is served.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum

from sqlmodel import JSON, Column, Field, SQLModel, UniqueConstraint


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ProposalStatus(str, Enum):
    PENDING = "pending"
    PROMOTED = "promoted"  # became a Skill in its own right
    MERGED = "merged"  # judged the same as an existing skill
    REJECTED = "rejected"


class SkillProposal(SQLModel, table=True):
    __table_args__ = (UniqueConstraint("course_id", "slug"),)

    id: str = Field(default_factory=lambda: uuid.uuid4().hex, primary_key=True)
    course_id: str = Field(index=True)
    # The normalized, course-prefixed id this proposal would claim.
    slug: str = Field(index=True)

    name: str
    description: str
    difficulty_band: float
    prereqs: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    keywords: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    question_forms: list[str] = Field(default_factory=list, sa_column=Column(JSON))

    # How many distinct generated problems proposed this skill. One model
    # inventing a name once is noise; the same gap named repeatedly is signal.
    observations: int = Field(default=1)

    status: ProposalStatus = Field(default=ProposalStatus.PENDING, index=True)
    # Set when the proposal is judged to be an existing skill under another
    # name, so the same proposal isn't re-litigated on every review.
    resolved_skill_id: str | None = Field(default=None)

    first_seen: datetime = Field(default_factory=_utcnow)
    last_seen: datetime = Field(default_factory=_utcnow)
