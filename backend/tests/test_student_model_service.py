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
from app.services.accuracy import observed_accuracy


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

    # updated_skills reports the estimate -- what selection will act on --
    # not the raw score, which is on the window.
    assert result.updated_skills["calc1.a"] == pytest.approx((1.0 + 1.0) / 3)
    state = session.get(SkillState, ("stu1", "calc1.a"))
    assert state.attempts == 1
    assert state.hints_used == 0
    assert observed_accuracy(state.recent_outcomes) == pytest.approx(1.0)


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
    state = session.get(SkillState, ("stu1", "calc1.a"))
    assert state.recent_outcomes == [0.0]
    # One wrong answer does not read as "0% on this topic": the estimate
    # still carries the prior until real evidence outweighs it.
    assert result.updated_skills["calc1.a"] == pytest.approx(1 / 3)


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
    assert observed_accuracy(state.recent_outcomes) == pytest.approx(2 / 3)


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

    assert by_id["calc1.a"].observed == pytest.approx(1.0)
    assert by_id["calc1.a"].attempts == 1
    assert by_id["calc1.b"].observed is None
    assert by_id["calc1.b"].attempts == 0


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


def test_only_the_primary_skill_takes_the_outcome(session):
    """One outcome cannot say which of several skills the student failed at.

    Pushing the same score into every declared skill blurred each topic on
    the problem and inflated the attempt counts confidence is built from --
    a student who nails the chain rule and fumbles the arithmetic used to
    have both topics marked wrong. The secondary skills stay on the ledger
    as attribution; only the topic the question was written for moves.
    """
    _skill(session, "calc1.chain-rule")
    _skill(session, "calc1.arithmetic")
    payload = AttemptCreate(
        student_id="stu1", session_id="sess1", problem_id="p1",
        expected_skills=["calc1.chain-rule", "calc1.arithmetic"],
        difficulty=0.5, correct=False,
    )
    result = svc.record_attempt(session, "calc1", payload)

    assert list(result.updated_skills) == ["calc1.chain-rule"]
    assert session.get(SkillState, ("stu1", "calc1.chain-rule")).attempts == 1
    assert session.get(SkillState, ("stu1", "calc1.arithmetic")) is None

    attempt = session.exec(select(Attempt)).one()
    assert attempt.expected_skills == ["calc1.chain-rule", "calc1.arithmetic"]


def test_error_tag_is_stored_on_the_attempt(session):
    _skill(session, "calc1.a")
    payload = AttemptCreate(
        student_id="stu1", session_id="sess1", problem_id="p1",
        expected_skills=["calc1.a"], difficulty=0.5, correct=False,
        error_tag="sign_error",
    )
    svc.record_attempt(session, "calc1", payload)

    attempt = session.exec(select(Attempt)).one()
    assert attempt.error_tag == "sign_error"


def test_error_tag_defaults_to_none(session):
    _skill(session, "calc1.a")
    payload = AttemptCreate(
        student_id="stu1", session_id="sess1", problem_id="p1",
        expected_skills=["calc1.a"], difficulty=0.5, correct=True,
    )
    svc.record_attempt(session, "calc1", payload)

    attempt = session.exec(select(Attempt)).one()
    assert attempt.error_tag is None


def test_an_explicit_clock_is_used_for_last_seen_and_created_at(session):
    """`now` exists for the simulator's virtual clock; every production
    caller leaves it unset and gets the real wall clock instead."""
    _skill(session, "calc1.a")
    stamp = datetime(2020, 1, 1, tzinfo=timezone.utc)
    payload = AttemptCreate(
        student_id="stu1", session_id="sess1", problem_id="p1",
        expected_skills=["calc1.a"], difficulty=0.5, correct=True,
    )
    svc.record_attempt(session, "calc1", payload, now=stamp)

    state = session.get(SkillState, ("stu1", "calc1.a"))
    attempt = session.exec(select(Attempt)).one()
    # SQLite round-trips a datetime as naive; compare the wall-clock value.
    assert state.last_seen.replace(tzinfo=timezone.utc) == stamp
    assert attempt.created_at.replace(tzinfo=timezone.utc) == stamp
