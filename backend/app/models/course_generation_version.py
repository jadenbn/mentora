"""Per-course content signature of the last LLM-generated skill batch.

Lets automatic generation on upload skip re-calling the model when a
course's document set hasn't actually changed since the last generation
pass — the emergent-skill loop stays out of this table entirely, since it
proposes one skill at a time in response to a specific gap rather than
re-reading the whole course.
"""

from __future__ import annotations

from sqlmodel import Field, SQLModel


class CourseGenerationVersion(SQLModel, table=True):
    course_id: str = Field(primary_key=True)
    content_hash: str
