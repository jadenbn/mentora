"""Problem-to-skill attribution: the table the whole guarantee rests on."""

from __future__ import annotations

import pytest
from sqlmodel import Session, SQLModel, create_engine

from app.models.skill import Skill
from app.services import attribution


@pytest.fixture
def session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


def _skill(session, skill_id):
    session.add(
        Skill(id=skill_id, course_id="calc1", name=skill_id, description="d",
              difficulty_band=0.5, prereqs=[])
    )
    session.commit()


def test_attribution_round_trips_in_declared_order(session):
    _skill(session, "calc1.a")
    _skill(session, "calc1.b")
    attribution.set_problem_skills(session, "p1", ["calc1.b", "calc1.a"])

    assert attribution.get_problem_skills(session, "p1") == ["calc1.b", "calc1.a"]


def test_rewriting_replaces_rather_than_appends(session):
    _skill(session, "calc1.a")
    _skill(session, "calc1.b")
    attribution.set_problem_skills(session, "p1", ["calc1.a"])
    attribution.set_problem_skills(session, "p1", ["calc1.b"])

    assert attribution.get_problem_skills(session, "p1") == ["calc1.b"]


def test_an_unknown_skill_is_dropped_with_a_warning_not_an_error(session, caplog):
    _skill(session, "calc1.a")
    attribution.set_problem_skills(session, "p1", ["calc1.a", "calc1.ghost"])

    assert attribution.get_problem_skills(session, "p1") == ["calc1.a"]
    assert "calc1.ghost" in caplog.text


def test_a_problem_with_no_attribution_reads_as_empty(session):
    assert attribution.get_problem_skills(session, "never-seen") == []
