"""Tests for topic selection: coverage vs weakness, recency, difficulty.

No unlock gate and no prerequisite graph -- topics are flat. That is
deliberate: gating on top of an ability estimate is what starved a real
demo course (an average student never clears a fixed unlock threshold), and
a flat pool scored by weakness and staleness does not have that failure mode.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlmodel import Session, SQLModel, create_engine

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
           recent_outcomes=None, attempts=5, days_ago=0.0, served_minutes_ago=None):
    now = datetime.now(timezone.utc)
    session.add(
        SkillState(
            student_id=student_id, course_id=course_id, skill_id=skill_id,
            recent_outcomes=recent_outcomes if recent_outcomes is not None else [0.5],
            attempts=attempts, last_seen=now - timedelta(days=days_ago),
            last_served=(
                None if served_minutes_ago is None
                else now - timedelta(minutes=served_minutes_ago)
            ),
        )
    )


def test_returns_none_when_course_has_no_topics(session):
    assert selection.pick_topic(session, "nope", "stu1") is None


def test_recency_penalty_avoids_just_served_topic(session):
    _skill(session, "calc1.a")
    _skill(session, "calc1.c")
    # identical weakness/staleness inputs -- only difference is recency
    _state(session, "calc1.a", recent_outcomes=[0.4] * 5, days_ago=3, served_minutes_ago=1)
    _state(session, "calc1.c", recent_outcomes=[0.4] * 5, days_ago=3)
    session.commit()

    topic = selection.pick_topic(session, "calc1", "stu1")
    assert topic.skill_id == "calc1.c"


def test_an_abandoned_question_still_counts_as_served(session):
    """The bug: recency used to key off the attempt ledger.

    A student who is served a topic and never marks the work leaves no
    attempt, so the engine re-served that same topic forever -- to exactly
    the student who was bouncing off it. Serving is what the penalty tracks
    now, and mark_served is the only thing that has happened here.
    """
    _skill(session, "calc1.a")
    _skill(session, "calc1.b", difficulty_band=0.9)
    session.commit()

    first = selection.pick_topic(session, "calc1", "stu1")
    selection.mark_served(session, "calc1", "stu1", first.skill_id)

    second = selection.pick_topic(session, "calc1", "stu1")
    assert second.skill_id != first.skill_id


def test_one_bad_attempt_does_not_outrank_a_topic_with_real_evidence(session):
    """Why the estimate is smoothed.

    Unsmoothed, a single wrong answer read as accuracy 0.0 and scored
    0.60*1.0 = 0.600 -- above every topic in the course, including one with
    eight attempts of evidence that the student is doing better there. The
    engine chased noise, hardest on the topics it knew least about.
    """
    _skill(session, "calc1.one-bad-answer")
    _skill(session, "calc1.genuinely-weak")
    _state(session, "calc1.one-bad-answer", recent_outcomes=[0.0], attempts=1)
    _state(session, "calc1.genuinely-weak", recent_outcomes=[0.2] * 8, attempts=8)
    session.commit()

    topic = selection.pick_topic(session, "calc1", "stu1")
    assert topic.skill_id == "calc1.genuinely-weak"


def test_a_well_known_topic_goes_stale_more_slowly(session):
    """Spacing scales with strength: the same gap since practice means less
    on material that was solid than on material that was shaky."""
    _skill(session, "calc1.solid")
    _skill(session, "calc1.shaky")
    _state(session, "calc1.solid", recent_outcomes=[1.0] * 8, attempts=8, days_ago=6)
    _state(session, "calc1.shaky", recent_outcomes=[1.0] * 8, attempts=8, days_ago=6)
    # Same outcomes and the same gap; only the strength differs, so force it.
    session.commit()
    solid = session.get(SkillState, ("stu1", "calc1.solid"))
    shaky = session.get(SkillState, ("stu1", "calc1.shaky"))
    shaky.recent_outcomes = [0.4] * 8
    session.add(shaky)
    session.commit()

    now = datetime.now(timezone.utc)
    assert selection._staleness(solid, now, 0.9) < selection._staleness(shaky, now, 0.4)


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


def test_difficulty_tracks_the_estimate(session):
    _skill(session, "calc1.a")
    _state(session, "calc1.a", recent_outcomes=[0.7] * 5, attempts=5, days_ago=0)
    session.commit()

    # (0.7*5 + 0.5*2) / (5 + 2) -- the window, pulled toward the prior.
    topic = selection.pick_topic(session, "calc1", "stu1")
    assert topic.target_difficulty == pytest.approx(4.5 / 7)


def test_an_untouched_topic_is_written_at_its_authored_band(session):
    """The taxonomy already says how hard the topic is. Ignoring that and
    defaulting to 0.5 threw away the only cold-start prior on offer."""
    _skill(session, "calc1.hard", difficulty_band=0.8)
    session.commit()

    topic = selection.pick_topic(session, "calc1", "stu1")
    assert topic.target_difficulty == pytest.approx(0.8)


def test_a_topic_gone_stale_under_an_explicit_clock_outranks_a_freshly_seen_one(session):
    """The point of pick_topic's `now` parameter.

    Every production caller leaves `now` unset and gets the wall clock; the
    simulator is the one caller that passes a virtual timestamp, so it can
    move time forward without a real multi-day run to prove staleness
    actually changes a decision.
    """
    _skill(session, "calc1.stale")
    _skill(session, "calc1.fresh")
    anchor = datetime(2020, 1, 1, tzinfo=timezone.utc)
    # Identical weakness on both -- only last_seen differs.
    session.add(SkillState(
        student_id="stu1", course_id="calc1", skill_id="calc1.stale",
        recent_outcomes=[0.5] * 8, attempts=8, last_seen=anchor,
    ))
    session.add(SkillState(
        student_id="stu1", course_id="calc1", skill_id="calc1.fresh",
        recent_outcomes=[0.5] * 8, attempts=8, last_seen=anchor + timedelta(days=20),
    ))
    session.commit()

    topic = selection.pick_topic(session, "calc1", "stu1", now=anchor + timedelta(days=21))
    assert topic.skill_id == "calc1.stale"


def test_difficulty_is_clamped_to_the_productive_range(session):
    _skill(session, "calc1.a")
    _state(session, "calc1.a", recent_outcomes=[1.0] * 8, attempts=8, days_ago=0)
    session.commit()

    topic = selection.pick_topic(session, "calc1", "stu1")
    assert topic.target_difficulty == pytest.approx(selection.DIFFICULTY_CEIL)
