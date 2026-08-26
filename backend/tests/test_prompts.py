"""Prompt policy.

Prompts are data, not provider code, so they are testable without a provider.
The only invariant worth pinning is that the four buttons genuinely behave
differently — a mode that collapses into another is a dead button in the UI.
"""

from __future__ import annotations

import pytest

from app.prompts.tutor import ALLOWED_ACTIONS, tutor_instruction
from app.schemas.tutor import TutorMode


def test_every_mode_produces_a_distinct_instruction():
    instructions = {mode: tutor_instruction(mode) for mode in TutorMode}
    assert len(set(instructions.values())) == len(TutorMode)


@pytest.mark.parametrize("mode", list(TutorMode))
def test_every_mode_is_actually_implemented(mode):
    # A missing branch must fail loudly here rather than silently degrade to a
    # generic prompt at request time.
    assert tutor_instruction(mode).strip()


def test_the_instruction_names_only_the_action_types_we_can_render(mode=TutorMode.hint):
    instruction = tutor_instruction(mode)
    for action in ALLOWED_ACTIONS:
        assert action in instruction
    for retired in ("text", "underline", "latex"):
        assert retired not in instruction


def test_the_allowed_action_set_matches_the_renderer():
    assert ALLOWED_ACTIONS == ("highlight", "circle", "check", "cross")


def test_mark_mode_withholds_future_steps():
    assert "future" in tutor_instruction(TutorMode.mark).lower()


def test_hint_mode_asks_for_the_smallest_nudge():
    assert "smallest" in tutor_instruction(TutorMode.hint).lower()


def test_highlights_are_optional_and_can_be_multiple():
    instruction = tutor_instruction(TutorMode.hint).lower()
    assert "do not emit one by default" in instruction
    assert "multiple" in instruction and "highlight" in instruction


def test_every_instruction_forbids_grading_prior_ai_marks():
    # Follow-up tutoring depends on this: the model sees its own earlier
    # annotations in the image and must not treat them as student work.
    for mode in TutorMode:
        assert "prior" in tutor_instruction(mode).lower()
