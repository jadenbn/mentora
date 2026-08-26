"""Tests for attempt ingestion: the expected_skills guard, the rolling
accuracy window, idempotency, and the dashboard's overview query."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlmodel import Session, SQLModel, create_engine, select

from app.models.attempt import Attempt
from app.models.skill import Skill
from app.models.skill_state import SkillState
from app.schemas.learning import AttemptCreate
from app.services import student_model_service as svc
from app.services.accuracy import accuracy


@pytest.fixture
def session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


def _skill(session, id_, course_id="calc1", name=None):
    s = Skill(
        id=id_,
        course_id=course_id,
        name=name or id_,
        description="test skill",
        difficulty_band=0.5,
    )
    session.add(s)
    session.commit()
    return s


def test_record_attempt_scores_a_correct_unassisted_attempt_at_1(session):
    _skill(session, "calc1.a")
    payload = AttemptCreate(
        student_id="stu1", session_id="sess1", problem_id="p1",
        expected_skills=["calc1.a"], difficulty=0.5, correct=True, hints_used=0,
    )
    result = svc.record_attempt(session, "calc1", payload)

    assert result.updated_skills["calc1.a"] == pytest.approx(1.0)
    state = session.get(SkillState, ("stu1", "calc1.a"))
    assert state.attempts == 1
    assert state.hints_used == 0
    assert accuracy(state.recent_outcomes) == pytest.approx(1.0)


def test_record_attempt_scores_a_hinted_correct_attempt_lower(session):
    _skill(session, "calc1.a")
    payload = AttemptCreate(
        student_id="stu1", session_id="sess1", problem_id="p1",
        expected_skills=["calc1.a"], difficulty=0.5, correct=True, hints_used=1,
    )
    result = svc.record_attempt(session, "calc1", payload)

    assert 0.0 < result.updated_skills["calc1.a"] < 1.0
    state = session.get(SkillState, ("stu1", "calc1.a"))
    assert state.hints_used == 1


def test_record_attempt_scores_incorrect_at_0(session):
    _skill(session, "calc1.a")
    payload = AttemptCreate(
        student_id="stu1", session_id="sess1", problem_id="p1",
        expected_skills=["calc1.a"], difficulty=0.5, correct=False,
    )
    result = svc.record_attempt(session, "calc1", payload)
    assert result.updated_skills["calc1.a"] == pytest.approx(0.0)


def test_accuracy_is_the_mean_of_the_recent_window(session):
    _skill(session, "calc1.a")

    def post(problem_id, correct):
        return svc.record_attempt(
            session, "calc1",
            AttemptCreate(
                student_id="stu1", session_id="sess1", problem_id=problem_id,
                expected_skills=["calc1.a"], difficulty=0.5, correct=correct,
            ),
        )

    post("p1", True)
    post("p2", False)
    post("p3", True)

    state = session.get(SkillState, ("stu1", "calc1.a"))
    assert state.attempts == 3
    assert accuracy(state.recent_outcomes) == pytest.approx(2 / 3)


def test_the_window_caps_at_eight_outcomes(session):
    _skill(session, "calc1.a")
    for i in range(10):
        svc.record_attempt(
            session, "calc1",
            AttemptCreate(
                student_id="stu1", session_id="sess1", problem_id=f"p{i}",
                expected_skills=["calc1.a"], difficulty=0.5, correct=True,
            ),
        )
    state = session.get(SkillState, ("stu1", "calc1.a"))
    assert state.attempts == 10  # the count keeps growing
    assert len(state.recent_outcomes) == 8  # the window doesn't


def test_unknown_skill_raises(session):
    _skill(session, "calc1.a")
    payload = AttemptCreate(
        student_id="stu1", session_id="sess1", problem_id="p1",
        expected_skills=["calc1.does-not-exist"], difficulty=0.5, correct=True,
    )
    with pytest.raises(svc.UnknownSkillError):
        svc.record_attempt(session, "calc1", payload)


def test_reposting_the_same_problem_does_not_move_accuracy_again(session):
    """The whiteboard posts on every "mark", so repeats are expected traffic.

    They must be answered with the original attempt, not counted twice --
    otherwise ten marks on one canvas would all count toward accuracy.
    """
    _skill(session, "calc1.a")
    payload = AttemptCreate(
        student_id="stu1", session_id="sess1", problem_id="p1",
        expected_skills=["calc1.a"], difficulty=0.5, correct=True,
    )
    first = svc.record_attempt(session, "calc1", payload)
    repeat = svc.record_attempt(session, "calc1", payload)

    assert repeat.attempt_id == first.attempt_id
    assert repeat.updated_skills["calc1.a"] == pytest.approx(first.updated_skills["calc1.a"])
    assert len(session.exec(select(Attempt)).all()) == 1
    assert session.get(SkillState, ("stu1", "calc1.a")).attempts == 1


def test_a_different_problem_is_still_a_new_attempt(session):
    _skill(session, "calc1.a")

    def post(problem_id):
        return svc.record_attempt(
            session, "calc1",
            AttemptCreate(
                student_id="stu1", session_id="sess1", problem_id=problem_id,
                expected_skills=["calc1.a"], difficulty=0.5, correct=True,
            ),
        )

    post("p1")
    post("p2")

    assert len(session.exec(select(Attempt)).all()) == 2
    assert session.get(SkillState, ("stu1", "calc1.a")).attempts == 2


def test_skills_overview_includes_untouched_topics(session):
    _skill(session, "calc1.a", name="A")
    _skill(session, "calc1.b", name="B")
    svc.record_attempt(
        session, "calc1",
        AttemptCreate(
            student_id="stu1", session_id="sess1", problem_id="p1",
            expected_skills=["calc1.a"], difficulty=0.5, correct=True,
        ),
    )

    overview = svc.get_skills_overview(session, "calc1", "stu1")
    by_id = {s.skill_id: s for s in overview.skills}

    assert by_id["calc1.a"].accuracy == pytest.approx(1.0)
    assert by_id["calc1.a"].attempts == 1
    assert by_id["calc1.b"].accuracy is None
    assert by_id["calc1.b"].attempts == 0
    assert by_id["calc1.b"].has_signal is False


def test_skills_overview_flags_a_recently_added_topic(session):
    fresh = Skill(id="calc1.new", course_id="calc1", name="New", description="d",
                  difficulty_band=0.4, created_at=datetime.now(timezone.utc))
    old = Skill(id="calc1.old", course_id="calc1", name="Old", description="d",
               difficulty_band=0.4, created_at=datetime.now(timezone.utc) - timedelta(hours=1))
    session.add(fresh)
    session.add(old)
    session.commit()

    overview = svc.get_skills_overview(session, "calc1", "stu1")
    by_id = {s.skill_id: s for s in overview.skills}
    assert by_id["calc1.new"].is_recent is True
    assert by_id["calc1.old"].is_recent is False
