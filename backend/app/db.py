"""SQLite engine and session helpers for learning engine state."""

from __future__ import annotations

import logging

from sqlalchemy import event
from sqlmodel import SQLModel, create_engine

import app.engine.models  # noqa: F401  -- registers the engine's tables
import app.models  # noqa: F401  -- registers taxonomy + attribution tables
from app.config import database_path

logger = logging.getLogger(__name__)

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


def _add_missing_columns() -> None:
    """Add columns a model gained since the database was created.

    create_all() creates missing *tables* but never touches a table that
    already exists, so adding a field to a model left every existing dev
    database a broken one: SkillState.last_served went in, and every query
    against that table started failing with "no such column".

    Deliberately the smallest thing that fixes that class of bug: it only
    ever ADDs a nullable or defaulted column. Nothing here drops, renames,
    retypes, or backfills, and a new NOT NULL column with no default is
    logged and skipped rather than guessed at -- SQLite could not add it
    without inventing values. Anything beyond additive needs a real
    migration tool.
    """
    with engine.begin() as connection:
        # Read the schema on the same connection that alters it. Asking a
        # separate one (an Inspector has its own) can hand back a stale view
        # under SQLite's per-connection schema cache, and the mismatch shows
        # up as "duplicate column" on a column it just reported missing.
        existing = {
            row[0]
            for row in connection.exec_driver_sql(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        for table in SQLModel.metadata.sorted_tables:
            if table.name not in existing:
                continue  # create_all just made it, in full
            present = {
                row[1]
                for row in connection.exec_driver_sql(f"PRAGMA table_info({table.name})")
            }
            for column in table.columns:
                if column.name in present:
                    continue
                if not column.nullable and column.default is None and column.server_default is None:
                    logger.warning(
                        "%s.%s is NOT NULL with no default; add it by hand",
                        table.name,
                        column.name,
                    )
                    continue
                connection.exec_driver_sql(
                    f'ALTER TABLE "{table.name}" '
                    f'ADD COLUMN "{column.name}" {column.type.compile(engine.dialect)}'
                )
                logger.info("added column %s.%s", table.name, column.name)


def init_db() -> None:
    """Create tables, and reconcile ones that predate a model change.

    Called once on startup.
    """
    SQLModel.metadata.create_all(engine)
    _add_missing_columns()
