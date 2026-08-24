"""The provider adapter.

Everything here is about surviving Gemini rather than about tutoring: schema
dialect quirks, malformed output, and turning provider failures into two
error types the API layer can map to status codes.
"""

from __future__ import annotations

import asyncio

import pytest

pytest.importorskip("google.adk", reason="provider adapter requires google-adk")

from app.agents.tutor_workflow import (  # noqa: E402
    TUTOR_PLAN_RESPONSE_SCHEMA,
    GeminiTutorWorkflow,
    drop_nulls,
)
from app.agents.workflow_errors import TutorWorkflowError, TutorWorkflowTimeout  # noqa: E402
from app.schemas.tutor import TutorMode  # noqa: E402
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

    def test_the_provider_schema_offers_only_renderable_actions(self):
        action_types = _find_enum(TUTOR_PLAN_RESPONSE_SCHEMA, "type")
        assert set(action_types) == {"text", "circle", "check", "cross"}


class TestNullPlaceholders:
    """The provider schema requires every key, so absent fields arrive as
    null. Strict unions reject nulls, so they are stripped first."""

    def test_null_fields_are_removed(self):
        assert drop_nulls({"type": "text", "text": "hi", "target": None}) == {
            "type": "text",
            "text": "hi",
        }

    def test_nested_objects_are_cleaned(self):
        assert drop_nulls({"a": {"b": None, "c": 1}}) == {"a": {"c": 1}}

    def test_lists_are_cleaned_elementwise(self):
        assert drop_nulls({"xs": [{"a": None, "b": 2}]}) == {"xs": [{"b": 2}]}

    def test_falsy_but_present_values_survive(self):
        # 0 and "" are data; only None is a placeholder.
        assert drop_nulls({"x": 0, "y": "", "z": False}) == {"x": 0, "y": "", "z": False}


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
            super().__init__(model="test-model", timeout_seconds=1)
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
