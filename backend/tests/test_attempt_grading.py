"""Tests for the tutor-response -> attempt-fields adapter."""

from __future__ import annotations

from app.models.enums import MisconceptionTag
from app.services.attempt_grading import _TutorStatus, to_attempt_grading

SKILLS = ["calc1.derivatives.chain-rule"]
MULTI_SKILLS = ["calc1.derivatives.chain-rule", "calc1.derivatives.power-rule"]


def test_correct_status_has_no_errors() -> None:
    grading = to_attempt_grading(_TutorStatus.correct, SKILLS)
    assert grading is not None
    assert grading.correct is True
    assert grading.partial is False
    assert grading.errors == []


def test_uncertain_status_is_not_recorded() -> None:
    assert to_attempt_grading(_TutorStatus.uncertain, SKILLS) is None


def test_partial_status_tags_incomplete_per_expected_skill() -> None:
    grading = to_attempt_grading(_TutorStatus.partial, MULTI_SKILLS)
    assert grading is not None
    assert grading.correct is False
    assert grading.partial is True
    assert [e.skill_id for e in grading.errors] == MULTI_SKILLS
    assert all(e.misconception == MisconceptionTag.INCOMPLETE for e in grading.errors)


def test_incorrect_status_tags_conceptual_error_per_expected_skill() -> None:
    grading = to_attempt_grading(_TutorStatus.incorrect, MULTI_SKILLS)
    assert grading is not None
    assert grading.correct is False
    assert grading.partial is False
    assert [e.skill_id for e in grading.errors] == MULTI_SKILLS
    assert all(e.misconception == MisconceptionTag.CONCEPTUAL_ERROR for e in grading.errors)


def test_errors_carry_no_step_index_yet() -> None:
    grading = to_attempt_grading(_TutorStatus.incorrect, SKILLS)
    assert grading is not None
    assert all(e.step_index is None for e in grading.errors)


def test_no_expected_skills_yields_no_errors_even_when_graded_wrong() -> None:
    grading = to_attempt_grading(_TutorStatus.incorrect, [])
    assert grading is not None
    assert grading.correct is False
    assert grading.errors == []
