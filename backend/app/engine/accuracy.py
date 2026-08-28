"""Pure helpers for reading a SkillState: no database, no I/O.

Two numbers, and the distinction between them is the whole point:

* `observed_accuracy` is what actually happened -- the mean of the recent
  window, `None` when there is nothing to average. It is for display.
* `estimated_accuracy` is what the engine acts on -- the same mean pulled
  toward a prior by PRIOR_WEIGHT pseudo-observations, so a reading from one
  attempt cannot swing a decision the way a reading from eight can.

The smoothing replaces an earlier `has_signal(attempts)` threshold, which
gated *difficulty* on having enough evidence but left *selection* acting on
a single data point: one wrong answer scored 0.60 on the priority formula
and outranked every topic with real history behind it. Shrinkage handles
both callers with one rule and no cliff.
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.engine.models.skill_state import RECENT_WINDOW

#: Outcome scoring: a hint-assisted correct answer counts for less than an
#: unassisted one. Every accuracy figure in the system is a mean of these,
#: at topic scope and at course scope alike.
SCORE_CORRECT_UNASSISTED = 1.0
SCORE_CORRECT_HINTED = 0.6
SCORE_PARTIAL = 0.3
SCORE_INCORRECT = 0.0

#: Where an estimate sits with no evidence, and how much evidence it takes
#: to move it appreciably. Two pseudo-observations: the third real attempt
#: is where the student's own record starts to outweigh the prior.
PRIOR_ACCURACY = 0.5
PRIOR_WEIGHT = 2.0


def score_attempt(*, correct: bool, hints_used: int, partial: bool) -> float:
    if correct:
        return SCORE_CORRECT_UNASSISTED if hints_used == 0 else SCORE_CORRECT_HINTED
    if partial:
        return SCORE_PARTIAL
    return SCORE_INCORRECT


def push_outcome(recent: list[float], score: float) -> list[float]:
    """Append a score, keeping only the most recent RECENT_WINDOW."""
    return (recent + [score])[-RECENT_WINDOW:]


def observed_accuracy(scores: list[float]) -> float | None:
    """Mean of the scores as recorded, or None if there are none.

    Reporting only -- the dashboard shows this. Nothing decides on it,
    because two attempts and eight attempts produce the same number here.
    """
    if not scores:
        return None
    return sum(scores) / len(scores)


def estimated_accuracy(scores: list[float]) -> float:
    """Mean of the scores shrunk toward PRIOR_ACCURACY, always defined.

    With no scores this is exactly the prior, so callers never branch on
    emptiness and never need a "not enough data" fallback of their own.
    """
    return (sum(scores) + PRIOR_WEIGHT * PRIOR_ACCURACY) / (len(scores) + PRIOR_WEIGHT)


def days_since(last_seen: datetime, now: datetime) -> float:
    """Days elapsed, defensive against naive datetimes from older rows."""
    if last_seen.tzinfo is None:
        last_seen = last_seen.replace(tzinfo=timezone.utc)
    return (now - last_seen).total_seconds() / 86400


def difficulty_bucket(difficulty: float) -> str:
    """Collapse a continuous difficulty into the three words a prompt and
    the simulator both need. One definition: api.questions asks the
    generator for one of these words, and services.simulation buckets
    outcomes by the same boundaries to check whether the word was honoured.
    """
    if difficulty < 0.4:
        return "introductory"
    if difficulty < 0.7:
        return "moderate"
    return "challenging"
