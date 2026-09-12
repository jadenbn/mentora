"""A student's course-wide accuracy, derived from their attempt ledger.

Not a stored row: computed on read from Attempt, the same immutable log
per-topic accuracy is read from. That means it can never drift from what
actually happened and needs no migration if the definition changes later.

It is deliberately the *same* number as per-topic accuracy, one scope up:
the mean of `score_attempt` over the ledger, shrunk toward the same prior.
It used to be `correct / len(rows)` -- a plain binary count in which a
hint-assisted answer weighed the same as an unassisted one and a partial
weighed nothing -- so "accuracy" meant two incompatible things one page
apart, and the weaker of the two was what fed the generator.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlmodel import Session, select

from app.engine.models.attempt import Attempt
from app.models.skill import Skill
from app.engine.models.skill_state import SkillState
from app.engine import hints
from app.engine.accuracy import estimated_accuracy, score_attempt


@dataclass(frozen=True)
class StudentProfile:
    attempts: int
    #: Always defined: with no attempts it is the prior. Callers asking
    #: "how hard should this student's next question be" always get an
    #: answer, and a thin record simply answers close to the middle.
    accuracy: float


def get_profile(session: Session, course_id: str, student_id: str) -> StudentProfile:
    rows = session.exec(
        select(Attempt).where(
            Attempt.course_id == course_id, Attempt.student_id == student_id
        )
    ).all()
    scores = [
        score_attempt(correct=a.correct, hints_used=a.hints_used, partial=a.partial)
        for a in rows
    ]
    return StudentProfile(attempts=len(rows), accuracy=estimated_accuracy(scores))


@dataclass(frozen=True)
class LearnerContext:
    """What the tutor is allowed to know about this student on this topic.

    Not a score for the student to see -- PRODUCT.md §24 wants the engine's
    invisibility preserved, and this is consumed by a prompt, never rendered
    on a canvas. `estimate` is the same shrunk mean selection.pick_topic
    already acts on; nothing new is computed to produce it.
    """

    skill_name: str
    estimate: float
    attempts: int
    hints_on_this_problem: int


def get_learner_context(
    session: Session,
    *,
    course_id: str,
    student_id: str,
    skill_id: str,
    problem_id: str,
) -> LearnerContext | None:
    """None when skill_id names nothing in this course -- callers pass that
    straight through to the tutor rather than guess at a context."""
    skill = session.get(Skill, skill_id)
    if skill is None or skill.course_id != course_id:
        return None
    state = session.get(SkillState, (student_id, skill_id))
    return LearnerContext(
        skill_name=skill.name,
        estimate=estimated_accuracy(state.recent_outcomes if state else []),
        attempts=state.attempts if state else 0,
        hints_on_this_problem=hints.hints_taken(session, student_id, problem_id),
    )
