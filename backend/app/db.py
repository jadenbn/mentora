"""SQLite engine and session helpers for learning engine state."""

from __future__ import annotations

import os

from sqlmodel import Session, SQLModel, create_engine

DB_PATH = os.getenv("MENTORA_DB_PATH", "mentora.db")
engine = create_engine(f"sqlite:///{DB_PATH}", echo=False)


def init_db() -> None:
    """Create tables. Called once on startup."""
    SQLModel.metadata.create_all(engine)


def get_session():
    with Session(engine) as session:
        yield session
