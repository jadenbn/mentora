"""The two accuracy numbers, and why there are two.

`observed_accuracy` is what happened; `estimated_accuracy` is what the engine
is allowed to act on. The gap between them is confidence, and it exists
because a reading from one attempt used to move decisions exactly as hard as
a reading from eight.
"""

from __future__ import annotations

import pytest

from app.services.accuracy import (
    PRIOR_ACCURACY,
    estimated_accuracy,
    observed_accuracy,
    push_outcome,
    score_attempt,
)
from app.models.skill_state import RECENT_WINDOW


def test_observed_is_undefined_with_nothing_to_average():
    assert observed_accuracy([]) is None


def test_the_estimate_is_always_defined_and_starts_at_the_prior():
    assert estimated_accuracy([]) == pytest.approx(PRIOR_ACCURACY)


def test_one_perfect_attempt_does_not_read_as_certainty():
    assert observed_accuracy([1.0]) == pytest.approx(1.0)
    assert estimated_accuracy([1.0]) == pytest.approx(2 / 3)


def test_evidence_outweighs_the_prior_as_it_accumulates():
    thin = estimated_accuracy([1.0])
    thick = estimated_accuracy([1.0] * 8)
    assert thin < thick < 1.0
    assert thick == pytest.approx(9 / 10)


def test_the_estimate_converges_on_what_was_observed():
    outcomes = [0.3] * RECENT_WINDOW
    assert estimated_accuracy(outcomes) == pytest.approx(observed_accuracy(outcomes), abs=0.05)


def test_a_hinted_correct_answer_is_worth_less_than_an_unassisted_one():
    assert score_attempt(correct=True, hints_used=1, partial=False) < score_attempt(
        correct=True, hints_used=0, partial=False
    )


def test_the_window_only_ever_holds_the_most_recent_outcomes():
    window: list[float] = []
    for i in range(RECENT_WINDOW + 5):
        window = push_outcome(window, float(i))
    assert len(window) == RECENT_WINDOW
    assert window[-1] == float(RECENT_WINDOW + 4)
