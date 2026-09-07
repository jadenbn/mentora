"""Shared FastAPI dependency factories."""

from __future__ import annotations

from functools import lru_cache
from typing import Iterator

from fastapi import Depends, HTTPException
from sqlmodel import Session

from app.config import database_path
from app.database import CourseRepository
from app.db import engine
from app.schemas.courses import Course


def get_session() -> Iterator[Session]:
    with Session(engine) as session:
        yield session


@lru_cache(maxsize=1)
def get_course_repository() -> CourseRepository:
    return CourseRepository(database_path())


def require_course(
    course_id: str,
    repository: CourseRepository = Depends(get_course_repository),
) -> Course:
    """404 on an unknown course id before the engine ever sees it.

    course_id is otherwise trusted free text everywhere downstream --
    normalize_slug bakes it straight into every skill's primary key -- so a
    typo here would silently mint a brand-new course's worth of GENERATED
    skills instead of failing loudly.
    """
    course = repository.get_course(course_id)
    if course is None:
        raise HTTPException(404, "Course was not found")
    return course
