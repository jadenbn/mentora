"""Shared FastAPI dependency factories."""

from __future__ import annotations

from functools import lru_cache
from typing import Iterator

from sqlmodel import Session

from app.config import database_path
from app.database import CourseRepository
from app.db import engine


def get_session() -> Iterator[Session]:
    with Session(engine) as session:
        yield session


@lru_cache(maxsize=1)
def get_course_repository() -> CourseRepository:
    return CourseRepository(database_path())
