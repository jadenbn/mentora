"""The provider adapter.

Everything here is about surviving Gemini rather than about tutoring: schema
dialect quirks, malformed output, and turning provider failures into two
error types the API layer can map to status codes.
"""

from __future__ import annotations

import asyncio

import pytest

pytest.importorskip("google.genai", reason="provider adapter requires google-genai")

from app.agents.tutor_workflow import (  # noqa: E402
    TUTOR_PLAN_RESPONSE_SCHEMA,
    GeminiTutorWorkflow,
    _canvas_state,
    drop_nulls,
    normalize_provider_output,
)
from app.agents.workflow_errors import TutorWorkflowError, TutorWorkflowTimeout  # noqa: E402
from app.schemas.tutor import TutorMode  # noqa: E402
from google.genai import types  # noqa: E402
from tests import factories as f  # noqa: E402

pytestmark = pytest.mark.provider


class TestProviderSchemaDialect:
    """Gemini's response_schema endpoint rejects much of JSON Schema. The
    hand-written provider schema is the workaround; Pydantic remains the real
    validation boundary."""

    @pytest.mark.parametrize(
        "keyword",
        ["additionalProperties", "$defs", "$ref", "oneOf", "anyOf", "discriminator", "const"],
    )
    def test_the_provider_schema_avoids_unsupported_keywords(self, keyword):
        assert keyword not in _walk_keys(TUTOR_PLAN_RESPONSE_SCHEMA)

    def test_generation_is_tuned_for_an_interactive_path(self):
        config = GeminiTutorWorkflow(model="m")._generation_config(TutorMode.hint)
        assert config.thinking_config.thinking_level == types.ThinkingLevel.LOW
        assert config.max_output_tokens == 1_024
        # Vision tokens dominate; medium keeps handwriting legible for less.
        assert config.media_resolution == types.MediaResolution.MEDIA_RESOLUTION_MEDIUM

    def test_the_provider_schema_offers_only_renderable_actions(self):
        action_types = _find_enum(TUTOR_PLAN_RESPONSE_SCHEMA, "type")
        assert set(action_types) == {"highlight", "circle", "check", "cross"}


class TestNullPlaceholders:
    """The provider schema requires every key, so absent fields arrive as
    null. Strict unions reject nulls, so they are stripped first."""

    def test_null_fields_are_removed(self):
        assert drop_nulls({"type": "circle", "target": None}) == {"type": "circle"}

    def test_nested_objects_are_cleaned(self):
        assert drop_nulls({"a": {"b": None, "c": 1}}) == {"a": {"c": 1}}

    def test_lists_are_cleaned_elementwise(self):
        assert drop_nulls({"xs": [{"a": None, "b": 2}]}) == {"xs": [{"b": 2}]}

    def test_falsy_but_present_values_survive(self):
        # 0 and "" are data; only None is a placeholder.
        assert drop_nulls({"x": 0, "y": "", "z": False}) == {"x": 0, "y": "", "z": False}


class TestCanvasState:
    def test_a_problem_only_request_is_explicitly_not_an_unreadable_image(self):
        state = _canvas_state(None)
        assert "has not drawn anything yet" in state
        assert "Do not say that the handwriting is unreadable" in state

    def test_an_image_request_tells_the_model_to_use_the_canvas(self):
        assert "student-work image is supplied above" in _canvas_state(f.PNG)


class TestFirstAttemptValidation:
    """Every avoidable repair attempt is a second round trip on an
    interactive path, so provider output is normalised before validating."""

    def test_a_field_from_another_action_is_dropped(self):
        plan = normalize_provider_output(
            {"status": "partial", "canvas_actions": [
                {"type": "circle", "target": {"x": 0, "y": 0, "width": 1, "height": 1},
                 "text": "hi", "position": {"x": 0.1, "y": 0.1}}]}
        )
        assert set(plan["canvas_actions"][0]) == {"type", "target"}

    def test_a_marking_action_keeps_only_its_target(self):
        plan = normalize_provider_output(
            {"status": "partial", "canvas_actions": [
                {"type": "circle", "target": {"x": 0.1, "y": 0.1, "width": 0.2, "height": 0.2},
                 "text": "stray", "position": {"x": 0.5, "y": 0.5}}]}
        )
        assert set(plan["canvas_actions"][0]) == {"type", "target"}

    def test_nulls_are_still_stripped(self):
        plan = normalize_provider_output(
            {"status": "partial", "canvas_actions": [
                {"type": "circle", "target": None}], "summary": None}
        )
        assert "summary" not in plan and plan["canvas_actions"][0] == {"type": "circle"}

    def test_an_unknown_action_is_left_for_validation_to_reject(self):
        plan = normalize_provider_output(
            {"status": "partial", "canvas_actions": [{"type": "hologram", "beam": 1}]}
        )
        assert plan["canvas_actions"][0]["type"] == "hologram"

    def test_a_plan_without_actions_is_untouched(self):
        assert normalize_provider_output({"status": "correct", "canvas_actions": []})[
            "canvas_actions"
        ] == []


class TestFailureTranslation:
    def test_a_timeout_raises_a_timeout(self):
        workflow = _workflow(raises=asyncio.TimeoutError())
        with pytest.raises(TutorWorkflowTimeout):
            asyncio.run(_run(workflow))

    def test_a_provider_exception_is_wrapped(self):
        workflow = _workflow(raises=RuntimeError("connection reset"))
        with pytest.raises(TutorWorkflowError):
            asyncio.run(_run(workflow))

    def test_a_provider_exception_message_is_not_re_raised_verbatim(self):
        workflow = _workflow(raises=RuntimeError("key sk-live-999 rejected"))
        with pytest.raises(TutorWorkflowError) as caught:
            asyncio.run(_run(workflow))
        assert "sk-live-999" not in str(caught.value)


class TestMalformedOutput:
    def test_malformed_output_gets_exactly_one_repair_attempt(self):
        workflow = _workflow(malformed_responses=1)
        result = asyncio.run(_run(workflow))
        assert workflow.attempts == 2
        assert result.canvas_actions is not None

    def test_persistently_malformed_output_gives_up_rather_than_looping(self):
        workflow = _workflow(malformed_responses=99)
        with pytest.raises(TutorWorkflowError):
            asyncio.run(_run(workflow))
        assert workflow.attempts == 2


# --- helpers ---------------------------------------------------------------


def _walk_keys(node) -> set:
    if isinstance(node, dict):
        return set(node) | set().union(*(_walk_keys(v) for v in node.values()), set())
    if isinstance(node, list):
        return set().union(*(_walk_keys(v) for v in node), set())
    return set()


def _find_enum(node, key: str) -> list:
    if isinstance(node, dict):
        if key in node and isinstance(node[key], dict) and "enum" in node[key]:
            return node[key]["enum"]
        for value in node.values():
            found = _find_enum(value, key)
            if found:
                return found
    if isinstance(node, list):
        for value in node:
            found = _find_enum(value, key)
            if found:
                return found
    return []


def _workflow(*, raises: Exception | None = None, malformed_responses: int = 0):
    """A GeminiTutorWorkflow with only the provider round trip replaced."""

    class Harness(GeminiTutorWorkflow):
        def __init__(self):
            super().__init__(api_key="test-key", model="test-model", timeout_seconds=1)
            self.attempts = 0

        async def _request_plan(self, **kwargs):
            self.attempts += 1
            if raises is not None:
                raise raises
            if self.attempts <= malformed_responses:
                return {"status": "not-a-status"}
            return f.plan().model_dump(mode="json")

    return Harness()


async def _run(workflow):
    return await workflow.run(
        mode=TutorMode.hint,
        canvas_image=f.PNG,
        canvas_mime_type="image/png",
        prior_annotations=[],
    )
