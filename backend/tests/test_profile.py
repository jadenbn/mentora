"""Course-wide accuracy: the same metric as per-topic accuracy, one scope up."""

from __future__ import annotations

import pytest
from sqlmodel import Session, SQLModel, create_engine

from app.models.attempt import Attempt
from app.models.skill import Skill
from app.models.skill_state import SkillState
from app.services.accuracy import PRIOR_ACCURACY
from app.services.hints import record_hint
from app.services.profile import get_learner_context, get_profile


@pytest.fixture
def session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


def _attempt(session, problem_id, *, correct, partial=False, hints_used=0):
    session.add(
        Attempt(
            student_id="stu1", course_id="calc1", session_id="s",
            problem_id=problem_id, expected_skills=["calc1.a"], difficulty=0.5,
            correct=correct, partial=partial, hints_used=hints_used,
        )
    )
    session.commit()


def test_a_student_with_no_history_reads_as_the_prior(session):
    profile = get_profile(session, "calc1", "stu1")
    assert profile.attempts == 0
    assert profile.accuracy == pytest.approx(PRIOR_ACCURACY)


def test_hints_count_against_course_wide_accuracy(session):
    """The bug this fixes.

    Course-wide accuracy used to be `correct / len(rows)` -- a binary count
    in which a hint-assisted answer weighed the same as an unassisted one.
    A student leaning on hints read as stronger than the per-topic model
    said they were, and that reading is what set the difficulty of every
    question they typed a request for.
    """
    _attempt(session, "p1", correct=True, hints_used=3)
    _attempt(session, "p2", correct=True, hints_used=3)
    hinted = get_profile(session, "calc1", "stu1").accuracy

    _attempt(session, "p3", correct=True)
    _attempt(session, "p4", correct=True)
    unassisted = get_profile(session, "calc1", "stu1").accuracy

    assert hinted < unassisted


def test_a_partial_is_worth_more_than_nothing(session):
    _attempt(session, "p1", correct=False, partial=True)
    partial = get_profile(session, "calc1", "stu1").accuracy

    _attempt(session, "p2", correct=False)
    with_a_miss = get_profile(session, "calc1", "stu1").accuracy

    assert with_a_miss < partial


class TestLearnerContext:
    """What the tutor gets to know about a student on one topic.

    Not new information: the same estimate selection.pick_topic already
    acts on, read for a prompt instead of a priority score.
    """

    def _skill(self, session, skill_id="calc1.a", course_id="calc1"):
        session.add(
            Skill(
                id=skill_id, course_id=course_id, name="Chain rule",
                description="d", difficulty_band=0.5,
            )
        )
        session.commit()

    def test_an_unknown_skill_id_returns_none(self, session):
        assert get_learner_context(
            session, course_id="calc1", student_id="stu1",
            skill_id="calc1.nope", problem_id="p1",
        ) is None

    def test_a_skill_from_another_course_returns_none(self, session):
        self._skill(session, skill_id="calc2.a", course_id="calc2")
        assert get_learner_context(
            session, course_id="calc1", student_id="stu1",
            skill_id="calc2.a", problem_id="p1",
        ) is None

    def test_a_first_attempt_has_no_history(self, session):
        self._skill(session)
        context = get_learner_context(
            session, course_id="calc1", student_id="stu1",
            skill_id="calc1.a", problem_id="p1",
        )
        assert context.skill_name == "Chain rule"
        assert context.attempts == 0
        assert context.estimate == pytest.approx(PRIOR_ACCURACY)
        assert context.hints_on_this_problem == 0

    def test_a_weak_topic_and_a_strong_topic_read_differently(self, session):
        self._skill(session, skill_id="calc1.weak")
        self._skill(session, skill_id="calc1.strong")
        session.add(SkillState(
            student_id="stu1", course_id="calc1", skill_id="calc1.weak",
            recent_outcomes=[0.0] * 8, attempts=8,
        ))
        session.add(SkillState(
            student_id="stu1", course_id="calc1", skill_id="calc1.strong",
            recent_outcomes=[1.0] * 8, attempts=8,
        ))
        session.commit()

        weak = get_learner_context(
            session, course_id="calc1", student_id="stu1",
            skill_id="calc1.weak", problem_id="p1",
        )
        strong = get_learner_context(
            session, course_id="calc1", student_id="stu1",
            skill_id="calc1.strong", problem_id="p2",
        )
        assert weak.estimate < strong.estimate
        assert weak.attempts == strong.attempts == 8

    def test_hints_taken_on_this_problem_are_counted(self, session):
        self._skill(session)
        record_hint(session, "stu1", "p1")
        record_hint(session, "stu1", "p1")
        context = get_learner_context(
            session, course_id="calc1", student_id="stu1",
            skill_id="calc1.a", problem_id="p1",
        )
        assert context.hints_on_this_problem == 2

    def test_hints_on_a_different_problem_do_not_count(self, session):
        self._skill(session)
        record_hint(session, "stu1", "some-other-problem")
        context = get_learner_context(
            session, course_id="calc1", student_id="stu1",
            skill_id="calc1.a", problem_id="p1",
        )
        assert context.hints_on_this_problem == 0
