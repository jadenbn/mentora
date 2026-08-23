"""Tests for backward-compatible learning-engine database initialization."""

from sqlalchemy import inspect
from sqlmodel import create_engine

from app.db import ensure_attempt_stuck_requests


def test_stuck_request_migration_is_additive_and_idempotent() -> None:
    test_engine = create_engine("sqlite://")
    with test_engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE attempt (id VARCHAR PRIMARY KEY, hints_used INTEGER NOT NULL)"
        )

    ensure_attempt_stuck_requests(test_engine)
    ensure_attempt_stuck_requests(test_engine)

    columns = {
        column["name"]: column
        for column in inspect(test_engine).get_columns("attempt")
    }
    assert "stuck_requests" in columns
    assert columns["stuck_requests"]["nullable"] is False
