"""Property tests for the pure mastery update rules."""

from __future__ import annotations

from hypothesis import given, strategies as st

from app.services.mastery import (
    MASTERY_CEIL,
    MASTERY_FLOOR,
    apply_decay,
    confidence,
    expected_score,
    learning_rate,
    prereq_delta,
    score_attempt,
    update_mastery,
)

mastery_st = st.floats(min_value=MASTERY_FLOOR, max_value=MASTERY_CEIL, allow_nan=False)
unit_st = st.floats(min_value=0.0, max_value=1.0, allow_nan=False)
attempts_st = st.integers(min_value=0, max_value=200)


@given(mastery=mastery_st, score=unit_st, difficulty=unit_st, attempts=attempts_st)
def test_update_mastery_is_bounded(mastery, score, difficulty, attempts) -> None:
    result = update_mastery(mastery, score, difficulty, attempts)
    assert MASTERY_FLOOR <= result <= MASTERY_CEIL


@given(mastery=mastery_st, difficulty=unit_st, attempts=attempts_st)
def test_perfect_score_never_decreases_mastery(mastery, difficulty, attempts) -> None:
    result = update_mastery(mastery, 1.0, difficulty, attempts)
    assert result >= mastery


@given(mastery=mastery_st, difficulty=unit_st, attempts=attempts_st)
def test_zero_score_never_increases_mastery(mastery, difficulty, attempts) -> None:
    result = update_mastery(mastery, 0.0, difficulty, attempts)
    assert result <= mastery


@given(
    mastery=mastery_st,
    difficulty=unit_st,
    attempts=attempts_st,
    lo=unit_st,
    hi=unit_st,
)
def test_update_mastery_monotonic_in_score(mastery, difficulty, attempts, lo, hi) -> None:
    low, high = sorted((lo, hi))
    result_low = update_mastery(mastery, low, difficulty, attempts)
    result_high = update_mastery(mastery, high, difficulty, attempts)
    assert result_low <= result_high


@given(n1=attempts_st, n2=attempts_st)
def test_learning_rate_non_increasing_in_attempts(n1, n2) -> None:
    lo, hi = sorted((n1, n2))
    assert learning_rate(lo) >= learning_rate(hi)


@given(mastery=mastery_st)
def test_decay_at_zero_days_is_identity(mastery) -> None:
    assert apply_decay(mastery, 0) == mastery


@given(mastery=mastery_st, days=st.floats(min_value=0.01, max_value=3650, allow_nan=False))
def test_decay_moves_toward_half_without_overshoot(mastery, days) -> None:
    decayed = apply_decay(mastery, days)
    if mastery > 0.5:
        assert 0.5 <= decayed <= mastery
    elif mastery < 0.5:
        assert mastery <= decayed <= 0.5
    else:
        assert decayed == 0.5


@given(difficulty=unit_st, mastery=unit_st)
def test_expected_score_is_bounded(difficulty, mastery) -> None:
    e = expected_score(mastery, difficulty)
    assert 0.0 < e < 1.0


@given(mastery=unit_st)
def test_expected_score_at_parity_is_half(mastery) -> None:
    assert abs(expected_score(mastery, mastery) - 0.5) < 1e-9


@given(mastery=unit_st, d1=unit_st, d2=unit_st)
def test_expected_score_decreases_with_difficulty(mastery, d1, d2) -> None:
    lo, hi = sorted((d1, d2))
    assert expected_score(mastery, lo) >= expected_score(mastery, hi)


@given(attempts=attempts_st)
def test_confidence_increases_with_attempts(attempts) -> None:
    c = confidence(attempts)
    assert 0.0 <= c <= 1.0
    if attempts > 0:
        assert c >= confidence(0)


def test_score_attempt_table() -> None:
    assert score_attempt(correct=True, hints_used=0, partial=False) == 1.00
    assert score_attempt(correct=True, hints_used=1, partial=False) == 0.70
    assert score_attempt(correct=True, hints_used=3, partial=False) == 0.45
    assert score_attempt(correct=False, hints_used=0, partial=True) == 0.15
    assert score_attempt(correct=False, hints_used=0, partial=False) == 0.00


def test_stuck_request_uses_stronger_assistance_score() -> None:
    assert (
        score_attempt(
            correct=True,
            hints_used=0,
            partial=False,
            stuck_requests=1,
        )
        == 0.45
    )


@given(delta=st.floats(min_value=-1.0, max_value=1.0, allow_nan=False).filter(lambda d: abs(d) > 1e-9))
def test_prereq_delta_is_a_fraction_of_delta(delta) -> None:
    result = prereq_delta(delta)
    assert abs(result) <= abs(delta)
    assert (result >= 0) == (delta >= 0)
