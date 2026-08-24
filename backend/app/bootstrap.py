"""Learning-engine startup: router registration and one-time DB seeding.

Kept out of main.py so attaching this branch's routes to the shared app is a
two-line change — an import and a call — instead of an edit to shared
startup logic that every other feature branch also touches.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from sqlmodel import Session

from app.api.dependencies import get_course_repository
from app.api.learning import router as learning_router
from app.db import engine, init_db
from app.services.taxonomy import seed_all_courses


def register_learning_engine(app: FastAPI) -> None:
    app.include_router(learning_router)


@asynccontextmanager
async def learning_engine_lifespan(app: FastAPI) -> AsyncIterator[None]:
    init_db()
    with Session(engine) as session:
        seed_all_courses(session)
    # Touch the raw-sqlite3 repository so CourseRepository.initialize() runs
    # its schema before the first request rather than inside it.
    get_course_repository()
    yield
