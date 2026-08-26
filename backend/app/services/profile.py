"""A student's overall accuracy, derived from their attempt ledger.

Not a stored row: computed on read from Attempt, the same immutable log
per-topic accuracy is read from. That means it can never drift from what
actually happened and needs no migration if the definition changes later.
If aggregation ever gets too slow to compute per-request, it can be
materialized into a table without changing this module's return shape.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlmodel import Session, select

from app.models.attempt import Attempt

# Below this many attempts, course-wide accuracy is too thin to act on --
# same reasoning as accuracy.MIN_ATTEMPTS_FOR_SIGNAL, at course scope.
MIN_ATTEMPTS_FOR_SIGNAL = 3
DEFAULT_ACCURACY = 0.5


@dataclass(frozen=True)
class StudentProfile:
    attempts: int
    accuracy: float | None  # None until MIN_ATTEMPTS_FOR_SIGNAL is reached


def get_profile(session: Session, course_id: str, student_id: str) -> StudentProfile:
    rows = session.exec(
        select(Attempt).where(
            Attempt.course_id == course_id, Attempt.student_id == student_id
        )
    ).all()

    if not rows:
        return StudentProfile(attempts=0, accuracy=None)

    correct = sum(1 for a in rows if a.correct)
    return StudentProfile(
        attempts=len(rows),
        accuracy=correct / len(rows) if len(rows) >= MIN_ATTEMPTS_FOR_SIGNAL else None,
    )


def difficulty_hint(profile: StudentProfile) -> float:
    """A course-wide difficulty to write at when the topic isn't known yet
    (the student described their own question in free text)."""
    return profile.accuracy if profile.accuracy is not None else DEFAULT_ACCURACY
