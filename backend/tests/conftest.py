"""Test-wide database isolation.

Every module under app/ resolves its SQLite path from MENTORA_DB_PATH at
import time -- app.db builds its engine at module scope, and
api.dependencies.get_course_repository is lru_cached. So the variable has to
be set before the first `import app.*` anywhere in the run.

conftest.py is imported before any test module, so setting it here is early
enough. Without this the API tests (which drive app.main.app through
TestClient) write to the developer's real backend/mentora.db: the suite stops
being idempotent, passes on a clean checkout, and fails on the second run.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

_TEST_DB_DIR = Path(tempfile.mkdtemp(prefix="mentora-tests-"))
os.environ["MENTORA_DB_PATH"] = str(_TEST_DB_DIR / "test.db")

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


@pytest.fixture(autouse=True)
def clean_database():
    """Rebuild both schemas around every test.

    Two layers share one file (SQLModel via app.db, raw sqlite3 via
    CourseRepository), so both are reset -- resetting only one leaves
    problems pointing at skills that no longer exist.
    """
    SQLModel.metadata.drop_all(engine)
    SQLModel.metadata.create_all(engine)
    _reset_repository_tables()

    yield

    SQLModel.metadata.drop_all(engine)


@pytest.fixture
def session():
    """A session on the isolated test database."""
    with Session(engine) as active:
        yield active
