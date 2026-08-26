"""Test-wide database and course-data isolation.

Every module under app/ resolves its SQLite path from MENTORA_DB_PATH, and
app.services.taxonomy resolves its course-skills directory from
MENTORA_COURSE_DATA_DIR, both at import time -- app.db builds its engine at
module scope, and app.services.taxonomy.DATA_DIR is a module-level constant.
So both variables have to be set before the first `import app.*` anywhere in
the run.

conftest.py is imported before any test module, so setting them here is early
enough. Without the DB one, the API tests (which drive app.main.app through
TestClient) write to the developer's real backend/mentora.db. Without the
course-data one, anything that exercises append_skills -- the dev import
endpoint, the piggyback in question_service -- writes straight into the
git-tracked backend/data/courses/*.json files.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

_TEST_DB_DIR = Path(tempfile.mkdtemp(prefix="mentora-tests-"))
os.environ["MENTORA_DB_PATH"] = str(_TEST_DB_DIR / "test.db")

_REAL_COURSE_DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "courses"
_TEST_COURSE_DATA_DIR = Path(tempfile.mkdtemp(prefix="mentora-course-data-"))
os.environ["MENTORA_COURSE_DATA_DIR"] = str(_TEST_COURSE_DATA_DIR)

import sqlite3  # noqa: E402

import pytest  # noqa: E402
from sqlmodel import Session, SQLModel  # noqa: E402

from app.api.dependencies import get_course_repository  # noqa: E402
from app.db import engine  # noqa: E402


def _reset_repository_tables() -> None:
    """Drop the raw-sqlite3 tables, then let the repository rebuild them.

    Dropping rather than deleting sidesteps ordering: these tables reference
    each other, and DELETE in schema order trips the foreign keys that
    CourseRepository.connect() enables.
    """
    owned_by_orm = set(SQLModel.metadata.tables)
    connection = sqlite3.connect(os.environ["MENTORA_DB_PATH"])
    try:
        names = [
            name
            for (name,) in connection.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            ).fetchall()
            if name not in owned_by_orm
        ]
        for name in names:
            connection.execute(f"DROP TABLE IF EXISTS {name}")
        connection.commit()
    finally:
        connection.close()

    get_course_repository().initialize()


def _reset_course_data() -> None:
    """Refresh the isolated course-data directory from the real files.

    A fresh copy every test, not just at session start: append_skills writes
    into this directory, and a test's writes must not leak into the next.
    """
    shutil.rmtree(_TEST_COURSE_DATA_DIR, ignore_errors=True)
    shutil.copytree(_REAL_COURSE_DATA_DIR, _TEST_COURSE_DATA_DIR)


@pytest.fixture(autouse=True)
def clean_database():
    """Rebuild both DB schemas and the course-data directory around every test.

    Two DB layers share one file (SQLModel via app.db, raw sqlite3 via
    CourseRepository), so both are reset -- resetting only one leaves
    problems pointing at skills that no longer exist.
    """
    SQLModel.metadata.drop_all(engine)
    SQLModel.metadata.create_all(engine)
    _reset_repository_tables()
    _reset_course_data()

    yield

    SQLModel.metadata.drop_all(engine)


@pytest.fixture
def session():
    """A session on the isolated test database."""
    with Session(engine) as active:
        yield active
