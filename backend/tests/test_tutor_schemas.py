"""The wire contract.

These tests are the specification for what the tutor is allowed to say. The
canvas action union is the security boundary: Gemini cannot express a tldraw
operation, only one of four shapes with bounded coordinates.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas.tutor import (
    CanvasAction,
    NormalizedBounds,
    NormalizedPoint,
    TutorMode,
    TutorPlan,
    TutorResponse,
    WorkStatus,
)
from tests import factories as f


class TestVocabularies:
    """Closed enums. A test that pins the exact set catches silent drift into
    the frontend mirror, which is hand-maintained."""

    def test_tutor_modes_are_the_four_buttons(self):
        assert {m.value for m in TutorMode} == {"mark", "hint", "explain", "stuck"}

    def test_work_status_keeps_an_uncertain_case(self):
        # `uncertain` is load-bearing: it is the only thing standing between an
        # unreadable canvas and a confidently wrong red cross.
        assert {s.value for s in WorkStatus} == {
            "correct",
            "incorrect",
            "partial",
            "uncertain",
        }


class TestCoordinates:
    def test_point_accepts_the_unit_square(self):
        assert NormalizedPoint(x=0.0, y=1.0).y == 1.0

    @pytest.mark.parametrize("x,y", [(-0.01, 0.5), (0.5, 1.01), (2, 0.5)])
    def test_point_rejects_coordinates_outside_the_image(self, x, y):
        with pytest.raises(ValidationError):
            NormalizedPoint(x=x, y=y)

    @pytest.mark.parametrize("width,height", [(0, 0.1), (0.1, 0), (-0.2, 0.1)])
    def test_bounds_reject_a_degenerate_box(self, width, height):
        with pytest.raises(ValidationError):
            NormalizedBounds(x=0.1, y=0.1, width=width, height=height)

    def test_bounds_must_stay_inside_the_image(self):
        # An annotation that starts on-canvas and runs off it is a render bug
        # waiting to happen, so it is refused at the boundary.
        with pytest.raises(ValidationError):
            NormalizedBounds(x=0.9, y=0.1, width=0.2, height=0.1)

    def test_bounds_may_touch_the_far_edge(self):
        assert NormalizedBounds(x=0.8, y=0.1, width=0.2, height=0.1).width == 0.2


class TestCanvasActions:
    """Exactly four action types. Each validates only its own fields."""

    def test_the_union_admits_only_the_four_supported_types(self):
        supported = set()
        for factory in (f.text_action, f.circle_action, f.check_action, f.cross_action):
            action = TutorPlan.model_validate(
                {"status": "partial", "canvas_actions": [factory()]}
            ).canvas_actions[0]
            supported.add(action.type)
        assert supported == {"text", "circle", "check", "cross"}

    @pytest.mark.parametrize("dropped_type", ["math", "arrow", "underline", "highlight"])
    def test_retired_action_types_are_refused(self, dropped_type):
        # These were cut. If one reappears the renderer has no branch for it,
        # so the contract must reject it rather than let it through untyped.
        with pytest.raises(ValidationError):
            TutorPlan.model_validate(
                {
                    "status": "partial",
                    "canvas_actions": [{"type": dropped_type, "target": f.bounds()}],
                }
            )

    def test_text_action_carries_a_point_not_a_box(self):
        action = TutorPlan.model_validate(
            {"status": "partial", "canvas_actions": [f.text_action()]}
        ).canvas_actions[0]
        assert isinstance(action.position, NormalizedPoint)
        assert not hasattr(action, "target")

    def test_marking_actions_carry_a_box_not_a_point(self):
        for factory in (f.circle_action, f.check_action, f.cross_action):
            action = TutorPlan.model_validate(
                {"status": "partial", "canvas_actions": [factory()]}
            ).canvas_actions[0]
            assert isinstance(action.target, NormalizedBounds)
            assert not hasattr(action, "position")

    def test_text_action_requires_something_to_say(self):
        with pytest.raises(ValidationError):
            TutorPlan.model_validate(
                {"status": "partial", "canvas_actions": [f.text_action(text="")]}
            )

    def test_a_marking_action_cannot_omit_its_target(self):
        with pytest.raises(ValidationError):
            TutorPlan.model_validate(
                {"status": "partial", "canvas_actions": [{"type": "circle"}]}
            )

    def test_an_unknown_action_type_is_refused(self):
        with pytest.raises(ValidationError):
            TutorPlan.model_validate(
                {
                    "status": "partial",
                    "canvas_actions": [{"type": "execute", "script": "rm -rf /"}],
                }
            )


class TestStrictness:
    """extra='forbid' everywhere. An unknown key is a bug, not a courtesy."""

    def test_an_unexpected_field_on_a_plan_is_refused(self):
        with pytest.raises(ValidationError):
            TutorPlan.model_validate(
                {"status": "partial", "canvas_actions": [], "temperature": 0.7}
            )

    def test_an_unexpected_field_on_an_action_is_refused(self):
        with pytest.raises(ValidationError):
            TutorPlan.model_validate(
                {
                    "status": "partial",
                    "canvas_actions": [f.text_action(font_size=48)],
                }
            )

    def test_the_model_cannot_mint_its_own_interaction_id(self):
        # interaction_id is server-authored. If a plan could carry one, model
        # output could collide with or overwrite a real interaction's shapes.
        assert "interaction_id" not in TutorPlan.model_fields


class TestTutorResponse:
    def test_a_response_is_four_fields(self):
        assert set(TutorResponse.model_fields) == {
            "interaction_id",
            "status",
            "canvas_actions",
            "summary",
        }

    def test_a_response_with_no_actions_is_valid(self):
        # "I have nothing useful to draw" is a legitimate answer, not an error.
        response = TutorResponse(
            interaction_id="abc123", status=WorkStatus.correct, summary="Looks right."
        )
        assert response.canvas_actions == []

    def test_summary_is_optional(self):
        response = TutorResponse(interaction_id="abc123", status=WorkStatus.partial)
        assert response.summary is None
