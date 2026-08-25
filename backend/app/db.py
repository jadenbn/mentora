"""SQLite engine and session helpers for learning engine state."""

from __future__ import annotations

from sqlalchemy import event
from sqlmodel import SQLModel, create_engine

import app.models  # noqa: F401  -- registers every table on SQLModel.metadata
from app.config import database_path

DB_PATH = database_path()
engine = create_engine(f"sqlite:///{DB_PATH}", echo=False)


@event.listens_for(engine, "connect")
def _configure_sqlite(dbapi_connection, connection_record) -> None:
    # This engine shares mentora.db with the raw-sqlite3 CourseRepository.
    # WAL + a busy timeout let the two independent connection pools write the
    # same file without tripping "database is locked" under real concurrency.
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA busy_timeout=5000")
    # Off by default in SQLite. ProblemSkill.skill_id references skill.id, and
    # that reference is the attribution invariant -- unenforced it is a
    # comment, not a constraint.
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def init_db() -> None:
    """Create tables. Called once on startup."""
    SQLModel.metadata.create_all(engine)
