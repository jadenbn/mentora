"""Learning-engine startup: router registration and one-time DB seeding.

Kept out of main.py so attaching this branch's routes to the shared app is a
two-line change — an import and a call — instead of an edit to shared
startup logic that every other feature branch also touches.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI

from app.api.dependencies import get_course_repository
from app.engine.api.dev import router as dev_router
from app.engine.api.learning import router as learning_router
from app.db import init_db

# uvicorn configures its own loggers but not the root one, so a module
# logger's INFO would be dropped. Borrowing uvicorn.error puts this line
# in the same stream, and format, as "Application startup complete".
logger = logging.getLogger("uvicorn.error")


def register_learning_engine(app: FastAPI) -> None:
    app.include_router(learning_router)
    app.include_router(dev_router)  # /dev/dashboard — dev-only, not in the API schema


@asynccontextmanager
async def learning_engine_lifespan(app: FastAPI) -> AsyncIterator[None]:
    init_db()
    # Touch the raw-sqlite3 repository so CourseRepository.initialize() runs
    # its schema (and seeds its default courses) before the first request
    # rather than inside it. Topics are never seeded here -- every course
    # starts with none and grows only through add_skills.
    get_course_repository()
    logger.info("Dev dashboard: http://localhost:8000/dev/dashboard")
    yield
