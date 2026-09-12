"""How one student is doing on one topic: a rolling window, not an estimate.

Deliberately not an ability estimate. The engine is infrastructure the tutor
consults, not a feature students see, and a window of recent outcomes is
simpler to reason about, to explain, and to get right than a fitted model --
which matters here because nothing surfaces it directly to a student anyway.
"""

from __future__ import annotations

from datetime import datetime

from sqlmodel import JSON, Column, Field, SQLModel

#: How many recent attempts count toward accuracy. Old outcomes age out on
#: their own rather than needing a decay function.
RECENT_WINDOW = 8


class SkillState(SQLModel, table=True):
    student_id: str = Field(primary_key=True)
    skill_id: str = Field(primary_key=True)
    course_id: str = Field(index=True)
    attempts: int = Field(default=0)
    hints_used: int = Field(default=0)
    #: Most recent RECENT_WINDOW scores (see services/accuracy.py),
    #: oldest first. Empty means never attempted.
    recent_outcomes: list[float] = Field(default_factory=list, sa_column=Column(JSON))
    #: When this topic was last *graded*. Drives staleness.
    last_seen: datetime | None = Field(default=None)
    #: When this topic was last *served* -- stamped at question generation,
    #: before the student has done anything. Drives the recency penalty, so
    #: an abandoned question still stops the engine re-serving that topic
    #: forever. A served topic that is never marked moves this and nothing
    #: else.
    last_served: datetime | None = Field(default=None)
