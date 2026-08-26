"""Tests for topic selection: coverage vs weakness, recency, difficulty.

No unlock gate and no prerequisite graph -- topics are flat. That is
deliberate: gating on top of an ability estimate is what starved a real
demo course (an average student never clears a fixed unlock threshold), and
a flat pool scored by weakness and staleness does not have that failure mode.
"""

from __future__ import annotations

import itertools
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


def _skill(session, id_, course_id="calc1", difficulty_band=0.5):
    s = Skill(
        id=id_, course_id=course_id, name=id_, description="d",
        difficulty_band=difficulty_band,
    )
    session.add(s)
    return s


def _state(session, skill_id, student_id="stu1", course_id="calc1",
           recent_outcomes=None, attempts=5, days_ago=0.0):
    last_seen = datetime.now(timezone.utc) - timedelta(days=days_ago)
    session.add(
        SkillState(
            student_id=student_id, course_id=course_id, skill_id=skill_id,
            recent_outcomes=recent_outcomes if recent_outcomes is not None else [0.5],
            attempts=attempts, last_seen=last_seen,
        )
    )


_problem_counter = itertools.count()


def _attempt(session, skill_id, student_id="stu1", course_id="calc1", minutes_ago=0):
    # Distinct problem ids: Attempt is unique on (student_id, problem_id).
    session.add(
        Attempt(
            student_id=student_id, course_id=course_id, session_id="s",
            problem_id=f"p{next(_problem_counter)}",
            expected_skills=[skill_id], difficulty=0.5,
            correct=True,
            created_at=datetime.now(timezone.utc) - timedelta(minutes=minutes_ago),
        )
    )


def test_returns_none_when_course_has_no_topics(session):
    assert selection.pick_topic(session, "nope", "stu1") is None


def test_recency_penalty_avoids_just_seen_topic(session):
    _skill(session, "calc1.a")
    _skill(session, "calc1.c")
    # identical weakness/staleness inputs -- only difference is recency
    _state(session, "calc1.a", recent_outcomes=[0.4] * 5, days_ago=3)
    _state(session, "calc1.c", recent_outcomes=[0.4] * 5, days_ago=3)
    # two most recent attempts both name "a" as primary skill
    _attempt(session, "calc1.a", minutes_ago=1)
    _attempt(session, "calc1.a", minutes_ago=2)
    session.commit()

    topic = selection.pick_topic(session, "calc1", "stu1")
    assert topic.skill_id == "calc1.c"


def test_a_failing_topic_outranks_an_untouched_one(session):
    """The bug this formula exists to fix.

    Under the old, gated design, staleness scored "never attempted" at a
    full 1.0 -- a term meaning "decayed since practice" -- so an untouched
    skill (0.60*0.5 + 0.25*1.0 = 0.550) beat a skill the student was failing
    (0.60*0.80 = 0.480). Every newly identified topic then outranked real
    remediation. Coverage and weakness are separate terms now.
    """
    _skill(session, "calc1.failing")
    _skill(session, "calc1.untouched")
    _state(session, "calc1.failing", recent_outcomes=[0.0] * 6, attempts=6, days_ago=0)
    session.commit()

    topic = selection.pick_topic(session, "calc1", "stu1")
    assert topic.skill_id == "calc1.failing"


def test_an_untouched_topic_outranks_a_mastered_one(session):
    """Coverage still has to pull in new material -- just not over remediation."""
    _skill(session, "calc1.mastered")
    _skill(session, "calc1.untouched")
    _state(session, "calc1.mastered", recent_outcomes=[1.0] * 10, attempts=10, days_ago=0)
    session.commit()

    topic = selection.pick_topic(session, "calc1", "stu1")
    assert topic.skill_id == "calc1.untouched"


def test_a_cold_student_starts_at_the_easiest_topic(session):
    """Every topic ties at W_COVERAGE, so the tie-break decides."""
    _skill(session, "calc1.advanced", difficulty_band=0.9)
    _skill(session, "calc1.basic", difficulty_band=0.1)
    session.commit()

    topic = selection.pick_topic(session, "calc1", "stu1")
    assert topic.skill_id == "calc1.basic"


def test_difficulty_tracks_accuracy_once_there_is_signal(session):
    _skill(session, "calc1.a")
    _state(session, "calc1.a", recent_outcomes=[0.7] * 5, attempts=5, days_ago=0)
    session.commit()

    topic = selection.pick_topic(session, "calc1", "stu1")
    assert topic.target_difficulty == pytest.approx(0.7)


def test_difficulty_defaults_without_enough_signal(session):
    _skill(session, "calc1.a")
    _state(session, "calc1.a", recent_outcomes=[0.0], attempts=1, days_ago=0)
    session.commit()

    topic = selection.pick_topic(session, "calc1", "stu1")
    assert topic.target_difficulty == pytest.approx(selection.DEFAULT_DIFFICULTY)


def test_difficulty_is_clamped_to_the_productive_range(session):
    _skill(session, "calc1.a")
    _state(session, "calc1.a", recent_outcomes=[1.0] * 8, attempts=8, days_ago=0)
    session.commit()

    topic = selection.pick_topic(session, "calc1", "stu1")
    assert topic.target_difficulty == pytest.approx(selection.DIFFICULTY_CEIL)
