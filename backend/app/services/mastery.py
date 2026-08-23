"""Pure mastery estimation math. No database, no I/O, no provider calls.

Stored mastery is always a function of the observed attempt log alone, so it
can be fully recomputed if these constants change.

update_mastery moves toward the RESIDUAL between actual and expected score at
the served difficulty, not toward raw score directly. Raw score alone doesn't
work here: selection always serves difficulty at or above the current mastery
estimate (see services/selection.py), so a student whose mastery has caught up
to their true ability only succeeds ~50% of the time by construction, and an
EWMA toward raw score gets permanently trapped below true ability, chasing a
fixed point defined by "P(correct) == mastery" rather than by ability itself.
Moving toward the expected-score residual is difficulty-invariant at that
fixed point instead, which is what lets mastery actually reach a confident
student's true ability rather than plateauing well below it.
"""

from __future__ import annotations

import math

# Outcome scoring: maps an attempt's result to a 0..1 score.
SCORE_CORRECT_UNASSISTED = 1.00
SCORE_CORRECT_ONE_HINT = 0.70
SCORE_CORRECT_MULTI_HINT = 0.45
SCORE_PARTIAL = 0.15
SCORE_INCORRECT = 0.00

# Learning rate: how much a single attempt moves the mastery estimate.
ALPHA_BASE = 0.50
ALPHA_DECAY = 0.35
ALPHA_FLOOR = 0.15

# Steepness of the expected-score curve. Governs how sharply "attempted well
# above/below current mastery" swings the expected score toward 0 or 1.
EXPECTED_SCORE_K = 4.0

# Mastery is never fully certain in either direction.
MASTERY_FLOOR = 0.02
MASTERY_CEIL = 0.98

# Forgetting: applied on read only, never written back.
HALFLIFE_DAYS = 14.0

# Fraction of a mastery delta bled onto a skill's direct prerequisites.
PREREQ_BLEED = 0.10


def score_attempt(
    correct: bool,
    hints_used: int,
    partial: bool,
    stuck_requests: int = 0,
) -> float:
    """Map an attempt's raw outcome to a 0..1 score."""
    if correct:
        if stuck_requests > 0:
            return SCORE_CORRECT_MULTI_HINT
        if hints_used == 0:
            return SCORE_CORRECT_UNASSISTED
        if hints_used == 1:
            return SCORE_CORRECT_ONE_HINT
        return SCORE_CORRECT_MULTI_HINT
    if partial:
        return SCORE_PARTIAL
    return SCORE_INCORRECT


def learning_rate(attempts: int) -> float:
    """Step size for the next update. Shrinks as evidence accumulates."""
    return max(ALPHA_FLOOR, ALPHA_BASE / (1 + ALPHA_DECAY * attempts))


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def expected_score(mastery: float, difficulty: float) -> float:
    """Predicted score at this mastery-vs-difficulty gap.

    A student attempting a problem exactly at their mastery level is expected
    to score 0.5 on average; comfortably below it, expected score rises
    toward 1; comfortably above it, expected score falls toward 0.
    """
    gap = mastery - difficulty
    return 1 / (1 + math.exp(-EXPECTED_SCORE_K * gap))


def update_mastery(mastery: float, score: float, difficulty: float, attempts: int) -> float:
    """One step toward the residual between actual and expected score."""
    alpha = learning_rate(attempts)
    residual = score - expected_score(mastery, difficulty)
    updated = mastery + alpha * residual
    return _clamp(updated, MASTERY_FLOOR, MASTERY_CEIL)


def apply_decay(mastery: float, days_since_seen: float) -> float:
    """Read-time decay toward 0.5. Never stored; mastery stays rebuildable."""
    if days_since_seen <= 0:
        return mastery
    factor = math.exp(-days_since_seen / HALFLIFE_DAYS)
    return 0.5 + (mastery - 0.5) * factor


def confidence(attempts: int) -> float:
    """How much to trust the mastery estimate. 0 at no attempts, ->1 with more."""
    return 1 - math.exp(-attempts / 4)


def prereq_delta(delta: float) -> float:
    """Fraction of a mastery change to bleed onto a direct prerequisite."""
    return delta * PREREQ_BLEED
