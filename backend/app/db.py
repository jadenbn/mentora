"""SQLite engine and session helpers for learning engine state."""

from __future__ import annotations

import os
from pathlib import Path

from sqlmodel import SQLModel, create_engine


def _db_path() -> Path:
    # Mirrors the shape app.config.database_path() is expected to take once
    # config.py exists on this branch — same env var, same repo-relative
    # default instead of a CWD-relative one.
    configured = os.getenv("MENTORA_DB_PATH")
    if configured:
        return Path(configured).expanduser()
    return Path(__file__).resolve().parents[1] / "mentora.db"


DB_PATH = _db_path()
engine = create_engine(f"sqlite:///{DB_PATH}", echo=False)


def init_db() -> None:
    """Create tables. Called once on startup."""
    SQLModel.metadata.create_all(engine)
