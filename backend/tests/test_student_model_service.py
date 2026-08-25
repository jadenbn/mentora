"""Tests for attempt ingestion: the expected_skills guard, mastery updates,
prerequisite bleed, cold start, and read-time decay."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlmodel import Session, SQLModel, create_engine, select

from app.models.attempt import Attempt
from app.models.skill import Skill
from app.models.skill_state import SkillState
from app.models.student_profile import StudentProfile
from app.schemas.learning import AttemptCreate, ErrorReport
from app.services import student_model_service as svc
from app.services.mastery import update_mastery


@pytest.fixture
def session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


def _skill(session, id_, course_id="calc1", prereqs=None, name=None):
    s = Skill(
        id=id_,
        course_id=course_id,
        name=name or id_,
        description="test skill",
        difficulty_band=0.5,
        prereqs=prereqs or [],
    )
    session.add(s)
    session.commit()
    return s


def test_record_attempt_updates_mastery(session):
    _skill(session, "calc1.a")
    payload = AttemptCreate(
        student_id="stu1",
        session_id="sess1",
        problem_id="p1",
        expected_skills=["calc1.a"],
        difficulty=0.5,
        correct=True,
        hints_used=0,
    )
    result = svc.record_attempt(session, "calc1", payload)

    expected = update_mastery(0.5, 1.0, 0.5, 0)
    assert result.updated_skills["calc1.a"] == pytest.approx(expected)

    state = session.get(SkillState, ("stu1", "calc1.a"))
    assert state.attempts == 1
    assert state.correct_unassisted == 1
    assert state.streak == 1


def test_guard_drops_errors_outside_expected_skills(session):
    _skill(session, "calc1.a")
    _skill(session, "calc1.b")
    payload = AttemptCreate(
        student_id="stu1",
        session_id="sess1",
        problem_id="p1",
        expected_skills=["calc1.a"],
        difficulty=0.5,
        correct=False,
        errors=[
            ErrorReport(skill_id="calc1.a", misconception="careless-error"),
            ErrorReport(skill_id="calc1.b", misconception="conceptual-error"),
        ],
    )
    result = svc.record_attempt(session, "calc1", payload)

    assert result.dropped_errors == 1
    state_a = session.get(SkillState, ("stu1", "calc1.a"))
    assert state_a.misconception_counts == {"careless-error": 1}
    state_b = session.get(SkillState, ("stu1", "calc1.b"))
    assert state_b is None  # never touched, since its only error was dropped

    attempt = session.exec(select(Attempt)).one()
    assert len(attempt.errors) == 1
    assert attempt.errors[0]["skill_id"] == "calc1.a"


def test_unknown_skill_raises(session):
    _skill(session, "calc1.a")
    payload = AttemptCreate(
        student_id="stu1",
        session_id="sess1",
        problem_id="p1",
        expected_skills=["calc1.does-not-exist"],
        difficulty=0.5,
        correct=True,
    )
    with pytest.raises(svc.UnknownSkillError):
        svc.record_attempt(session, "calc1", payload)


def test_prereq_bleed_reaches_direct_prerequisite(session):
    _skill(session, "calc1.a")
    _skill(session, "calc1.b", prereqs=["calc1.a"])
    payload = AttemptCreate(
        student_id="stu1",
        session_id="sess1",
        problem_id="p1",
        expected_skills=["calc1.b"],
        difficulty=0.5,
        correct=True,
        hints_used=0,
    )
    svc.record_attempt(session, "calc1", payload)

    state_a = session.get(SkillState, ("stu1", "calc1.a"))
    assert state_a is not None
    # b's delta was positive (correct answer), so the bleed onto a is positive too
    assert state_a.mastery > 0.5


def test_cold_start_seeds_at_global_ability(session):
    _skill(session, "calc1.a")
    session.add(StudentProfile(student_id="stu1", course_id="calc1", global_ability=0.8))
    session.commit()

    difficulty = 0.5
    payload = AttemptCreate(
        student_id="stu1",
        session_id="sess1",
        problem_id="p1",
        expected_skills=["calc1.a"],
        difficulty=difficulty,
        correct=True,
        hints_used=0,
        partial=False,
    )
    # score_attempt always returns exactly 1.0 for hints_used=0; instead
    # verify the seed directly via the update formula rather than fishing
    # for a score that happens to match.
    result = svc.record_attempt(session, "calc1", payload)
    seeded_mastery = 0.8
    expected = update_mastery(seeded_mastery, 1.0, difficulty, 0)
    assert result.updated_skills["calc1.a"] == pytest.approx(expected)


def test_reposting_the_same_problem_does_not_move_mastery_again(session):
    """The whiteboard posts on every "mark", so repeats are expected traffic.

    They must be answered with the original attempt, not counted twice --
    otherwise ten marks on one correct canvas saturate mastery.
    """
    _skill(session, "calc1.a")
    payload = AttemptCreate(
        student_id="stu1",
        session_id="sess1",
        problem_id="p1",
        expected_skills=["calc1.a"],
        difficulty=0.5,
        correct=True,
    )
    first = svc.record_attempt(session, "calc1", payload)
    mastery_after_first = session.get(SkillState, ("stu1", "calc1.a")).mastery

    repeat = svc.record_attempt(session, "calc1", payload)

    assert repeat.attempt_id == first.attempt_id
    assert repeat.updated_skills["calc1.a"] == pytest.approx(mastery_after_first)
    assert len(session.exec(select(Attempt)).all()) == 1
    state = session.get(SkillState, ("stu1", "calc1.a"))
    assert state.attempts == 1
    assert state.mastery == pytest.approx(mastery_after_first)


def test_a_different_problem_is_still_a_new_attempt(session):
    _skill(session, "calc1.a")

    def post(problem_id):
        return svc.record_attempt(
            session,
            "calc1",
            AttemptCreate(
                student_id="stu1", session_id="sess1", problem_id=problem_id,
                expected_skills=["calc1.a"], difficulty=0.5, correct=True,
            ),
        )

    post("p1")
    post("p2")

    assert len(session.exec(select(Attempt)).all()) == 2
    assert session.get(SkillState, ("stu1", "calc1.a")).attempts == 2


def test_get_student_model_applies_decay_on_read(session):
    skill = _skill(session, "calc1.a", name="A")
    old = datetime.now(timezone.utc) - timedelta(days=28)  # two half-lives
    session.add(
        SkillState(
            student_id="stu1",
            course_id="calc1",
            skill_id="calc1.a",
            mastery=0.9,
            attempts=5,
            last_seen=old,
        )
    )
    session.commit()

    model = svc.get_student_model(session, "calc1", "stu1")
    out = next(s for s in model.skills if s.skill_id == "calc1.a")
    assert out.mastery < 0.9
    assert out.mastery > 0.5  # decays toward 0.5, doesn't overshoot

    # stored value is untouched -- decay is read-time only
    stored = session.get(SkillState, ("stu1", "calc1.a"))
    assert stored.mastery == 0.9
