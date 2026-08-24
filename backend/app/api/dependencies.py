"""Shared FastAPI dependency factories."""

from __future__ import annotations

from typing import Iterator

from sqlmodel import Session

from app.db import engine


def get_session() -> Iterator[Session]:
    with Session(engine) as session:
        yield session
