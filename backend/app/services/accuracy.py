"""Pure helpers for reading a SkillState: no database, no I/O.

Replaces the earlier Elo/IRT mastery estimator. The engine is infrastructure
the tutor consults, not something a student sees a score from, so a rolling
window of recent outcomes is the right level of sophistication: explainable,
trivially correct, and exactly what PRODUCT.md §23 asks the MVP to track.
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.models.skill_state import RECENT_WINDOW

#: Outcome scoring, same tiers as before: a hint-assisted correct answer
#: counts for less than an unassisted one.
SCORE_CORRECT_UNASSISTED = 1.0
SCORE_CORRECT_HINTED = 0.6
SCORE_PARTIAL = 0.3
SCORE_INCORRECT = 0.0

#: Below this many observations, an accuracy reading is too thin to act on.
MIN_ATTEMPTS_FOR_SIGNAL = 2


def score_attempt(*, correct: bool, hints_used: int, partial: bool) -> float:
    if correct:
        return SCORE_CORRECT_UNASSISTED if hints_used == 0 else SCORE_CORRECT_HINTED
    if partial:
        return SCORE_PARTIAL
    return SCORE_INCORRECT


def push_outcome(recent: list[float], score: float) -> list[float]:
    """Append a score, keeping only the most recent RECENT_WINDOW."""
    return (recent + [score])[-RECENT_WINDOW:]


def accuracy(recent_outcomes: list[float]) -> float | None:
    """Mean of recent outcomes, or None if the skill has never been attempted."""
    if not recent_outcomes:
        return None
    return sum(recent_outcomes) / len(recent_outcomes)


def has_signal(attempts: int) -> bool:
    return attempts >= MIN_ATTEMPTS_FOR_SIGNAL


def days_since(last_seen: datetime, now: datetime) -> float:
    """Days elapsed, defensive against naive datetimes from older rows."""
    if last_seen.tzinfo is None:
        last_seen = last_seen.replace(tzinfo=timezone.utc)
    return (now - last_seen).total_seconds() / 86400
