"""Shared FastAPI dependency factories."""

from __future__ import annotations

from functools import lru_cache

from app.config import database_path
from app.database import CourseRepository


@lru_cache(maxsize=1)
def get_course_repository() -> CourseRepository:
    return CourseRepository(database_path())
