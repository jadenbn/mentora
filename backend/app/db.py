"""SQLite engine and session helpers for learning engine state."""

from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import Engine, inspect
from sqlmodel import Session, SQLModel, create_engine

DEFAULT_DB_PATH = Path(__file__).resolve().parents[1] / "mentora.db"
configured_path = os.getenv("MENTORA_DB_PATH")
DB_PATH = Path(configured_path).expanduser() if configured_path else DEFAULT_DB_PATH
engine = create_engine(
    f"sqlite:///{DB_PATH}",
    echo=False,
    connect_args={"check_same_thread": False},
)


def ensure_attempt_stuck_requests(db_engine: Engine) -> None:
    """Add the backward-compatible assistance column to existing SQLite DBs."""
    database = inspect(db_engine)
    if "attempt" not in database.get_table_names():
        return
    columns = {column["name"] for column in database.get_columns("attempt")}
    if "stuck_requests" in columns:
        return
    with db_engine.begin() as connection:
        connection.exec_driver_sql(
            "ALTER TABLE attempt "
            "ADD COLUMN stuck_requests INTEGER NOT NULL DEFAULT 0"
        )


def init_db() -> None:
    """Create tables. Called once on startup."""
    SQLModel.metadata.create_all(engine)
    ensure_attempt_stuck_requests(engine)


def get_session():
    with Session(engine) as session:
        yield session
