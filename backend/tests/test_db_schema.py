"""Startup reconciles a database that predates a model change.

The bug this exists for: create_all() creates missing tables but never
touches an existing one, so adding SkillState.last_served left every dev
database already on disk unable to answer a single SkillState query -- the
dashboard came back "load failed" and the tests, which build their schema
fresh every run, saw nothing wrong.
"""

from __future__ import annotations

import sqlite3

from sqlmodel import Session, select

from app.db import engine, init_db
from app.models.skill_state import SkillState


def _columns(table: str) -> set[str]:
    connection = sqlite3.connect(engine.url.database)
    try:
        return {row[1] for row in connection.execute(f"PRAGMA table_info({table})")}
    finally:
        connection.close()


def test_a_column_added_to_a_model_is_added_to_an_existing_table():
    connection = sqlite3.connect(engine.url.database)
    try:
        connection.execute("ALTER TABLE skillstate DROP COLUMN last_served")
        connection.commit()
    finally:
        connection.close()
    # The schema changed outside this process, which is exactly the real
    # case: the model gained a field while the database sat on disk. Drop
    # the pool so the reconciler starts from the file, not a cached view.
    engine.dispose()
    assert "last_served" not in _columns("skillstate")

    init_db()

    assert "last_served" in _columns("skillstate")
    with Session(engine) as session:
        # The query that was failing: any read of the table at all.
        assert session.exec(select(SkillState)).all() == []


def test_reconciling_an_already_current_database_changes_nothing():
    before = _columns("skillstate")
    init_db()
    init_db()
    assert _columns("skillstate") == before
