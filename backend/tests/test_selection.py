"""Tests for next-problem selection: unlock gating, recency, review floor."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlmodel import Session, SQLModel, create_engine

from app.models.attempt import Attempt
from app.models.skill import Skill
from app.models.skill_state import SkillState
from app.services import selection


@pytest.fixture
def session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


def _skill(session, id_, course_id="calc1", prereqs=None):
    s = Skill(
        id=id_, course_id=course_id, name=id_, description="d",
        difficulty_band=0.5, prereqs=prereqs or [],
    )
    session.add(s)
    return s


def _state(session, skill_id, student_id="stu1", course_id="calc1",
           mastery=0.5, attempts=5, days_ago=0.0):
    last_seen = datetime.now(timezone.utc) - timedelta(days=days_ago)
    session.add(
        SkillState(
            student_id=student_id, course_id=course_id, skill_id=skill_id,
            mastery=mastery, attempts=attempts, last_seen=last_seen,
        )
    )


def _attempt(session, skill_id, student_id="stu1", course_id="calc1", minutes_ago=0):
    session.add(
        Attempt(
            student_id=student_id, course_id=course_id, session_id="s",
            problem_id="p", expected_skills=[skill_id], difficulty=0.5,
            correct=True,
            created_at=datetime.now(timezone.utc) - timedelta(minutes=minutes_ago),
        )
    )


def test_returns_none_when_course_has_no_skills(session):
    assert selection.select_next(session, "nope", "stu1") is None


def test_locked_skill_never_selected(session):
    _skill(session, "calc1.a")  # no state -> default mastery 0.5, unlocked (no prereqs)
    _skill(session, "calc1.b", prereqs=["calc1.a"])  # locked: a's mastery 0.5 < 0.6
    session.commit()

    spec = selection.select_next(session, "calc1", "stu1")
    assert spec.skill_id == "calc1.a"


def test_unlocks_once_prereq_mastery_clears_threshold(session):
    _skill(session, "calc1.a")
    _skill(session, "calc1.b", prereqs=["calc1.a"])
    _state(session, "calc1.a", mastery=0.9, attempts=10)
    session.commit()

    spec = selection.select_next(session, "calc1", "stu1")
    # both unlocked now; b should win since a is already strong (low urgency)
    assert spec.skill_id == "calc1.b"


def test_recency_penalty_avoids_just_seen_skill(session):
    _skill(session, "calc1.a")
    _skill(session, "calc1.c")
    # identical mastery/staleness inputs -- only difference is recency
    _state(session, "calc1.a", mastery=0.4, attempts=5, days_ago=3)
    _state(session, "calc1.c", mastery=0.4, attempts=5, days_ago=3)
    # two most recent attempts both name "a" as primary skill
    _attempt(session, "calc1.a", minutes_ago=1)
    _attempt(session, "calc1.a", minutes_ago=2)
    session.commit()

    spec = selection.select_next(session, "calc1", "stu1")
    assert spec.skill_id == "calc1.c"


def test_forced_review_floor_after_three_weak_picks(session):
    _skill(session, "calc1.weak")
    _skill(session, "calc1.strong")
    _state(session, "calc1.weak", mastery=0.3, attempts=8, days_ago=0.1)
    _state(session, "calc1.strong", mastery=0.85, attempts=8, days_ago=6)
    for i in range(3):
        _attempt(session, "calc1.weak", minutes_ago=i)
    session.commit()

    spec = selection.select_next(session, "calc1", "stu1")
    assert spec.skill_id == "calc1.strong"
    assert spec.is_review is True


def test_no_review_floor_without_three_consecutive_weak_picks(session):
    _skill(session, "calc1.weak")
    _skill(session, "calc1.strong")
    _state(session, "calc1.weak", mastery=0.3, attempts=8, days_ago=0.1)
    _state(session, "calc1.strong", mastery=0.85, attempts=8, days_ago=6)
    # only two prior attempts, not three, and neither names weak/strong as
    # primary -- isolates the review-floor check from the recency penalty
    _attempt(session, "calc1.other", minutes_ago=0)
    _attempt(session, "calc1.other", minutes_ago=1)
    session.commit()

    spec = selection.select_next(session, "calc1", "stu1")
    assert spec.skill_id == "calc1.weak"
    assert spec.is_review is False


def test_difficulty_target_is_mastery_plus_offset(session):
    _skill(session, "calc1.a")
    # days_ago=0 avoids read-time decay confounding the expected value
    _state(session, "calc1.a", mastery=0.4, attempts=5, days_ago=0)
    session.commit()

    spec = selection.select_next(session, "calc1", "stu1")
    assert spec.target_difficulty == pytest.approx(
        0.4 + selection.DIFFICULTY_OFFSET, abs=1e-4
    )


def test_prereq_mastery_included_in_spec(session):
    _skill(session, "calc1.a")
    _skill(session, "calc1.b", prereqs=["calc1.a"])
    _state(session, "calc1.a", mastery=0.9, attempts=10)
    session.commit()

    spec = selection.select_next(session, "calc1", "stu1")
    assert spec.skill_id == "calc1.b"
    assert spec.prereq_mastery["calc1.a"] == pytest.approx(0.9)
