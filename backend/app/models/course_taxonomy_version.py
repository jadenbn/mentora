"""Per-course content hash of the seeded taxonomy.

Lets seeding notice when a data/courses/*.json file has changed and re-seed
that course, instead of skipping it forever because rows already exist.
"""

from __future__ import annotations

from sqlmodel import Field, SQLModel


class CourseTaxonomyVersion(SQLModel, table=True):
    course_id: str = Field(primary_key=True)
    content_hash: str
