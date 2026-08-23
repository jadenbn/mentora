"""Tests for ADK construction and bounded malformed-output repair."""

from __future__ import annotations

import asyncio

import pytest
from google.genai import types

from app.agents.tutor_workflow import (
    AdkTutorWorkflow,
    CANVAS_ANALYSIS_RESPONSE_SCHEMA,
    TUTOR_PLAN_RESPONSE_SCHEMA,
    TUTOR_WORKFLOW_RESPONSE_SCHEMA,
    TutorWorkflowError,
    _drop_nulls,
)
from app.schemas.tutor import TutorMode
from tests.helpers import PNG_BYTES, workflow_result


def test_every_tutor_mode_builds_a_distinct_planner_policy() -> None:
    workflow = AdkTutorWorkflow(model="test-model")
    instructions = {}

    for mode in TutorMode:
        agent = workflow._build_agent(mode)
        instructions[mode] = agent.instruction

    assert "do not reveal future solution steps" in instructions[TutorMode.mark]
    assert "smallest useful spatial nudge" in instructions[TutorMode.hint]
    assert "rather than giving a lecture" in instructions[TutorMode.explain]
    assert "stronger scaffolding" in instructions[TutorMode.stuck]
    assert len(set(instructions.values())) == 4


def test_generation_is_tuned_for_interactive_latency() -> None:
    agent = AdkTutorWorkflow(model="test-model")._build_agent(TutorMode.hint)

    config = agent.generate_content_config
    assert config.max_output_tokens == 1_024
    assert config.thinking_config.thinking_level == types.ThinkingLevel.MINIMAL
    assert config.media_resolution == types.MediaResolution.MEDIA_RESOLUTION_MEDIUM
    assert agent.model.retry_options.http_status_codes == [
        408,
        500,
        502,
        503,
        504,
    ]


def test_provider_schemas_remove_unsupported_additional_properties() -> None:
    unsupported = {
        "additionalProperties",
        "$defs",
        "$ref",
        "oneOf",
        "discriminator",
        "const",
        "exclusiveMinimum",
        "exclusiveMaximum",
    }

    def contains_unsupported_keyword(value) -> bool:
        if isinstance(value, dict):
            return bool(unsupported.intersection(value)) or any(
                contains_unsupported_keyword(item) for item in value.values()
            )
        if isinstance(value, list):
            return any(contains_unsupported_keyword(item) for item in value)
        return False

    assert not contains_unsupported_keyword(CANVAS_ANALYSIS_RESPONSE_SCHEMA)
    assert not contains_unsupported_keyword(TUTOR_PLAN_RESPONSE_SCHEMA)
    assert not contains_unsupported_keyword(TUTOR_WORKFLOW_RESPONSE_SCHEMA)


def test_provider_null_placeholders_are_removed_before_union_validation() -> None:
    assert _drop_nulls(
        {"type": "text", "text": "Try factoring", "latex": None, "items": [None]}
    ) == {"type": "text", "text": "Try factoring", "items": [None]}


def test_malformed_output_gets_exactly_one_repair_attempt() -> None:
    class RepairWorkflow(AdkTutorWorkflow):
        def __init__(self):
            super().__init__(model="test-model")
            self.attempts: list[bool] = []

        async def _run_once(self, **kwargs):
            self.attempts.append(kwargs["repair_attempt"])
            if len(self.attempts) == 1:
                raise ValueError("malformed output")
            return workflow_result()

    workflow = RepairWorkflow()
    result = asyncio.run(
        workflow.run(
            interaction_id="interaction",
            user_id="user",
            mode=TutorMode.hint,
            context={},
            canvas_image=PNG_BYTES,
            canvas_mime_type="image/png",
            selection_image=None,
            selection_mime_type=None,
        )
    )

    assert result.plan.status.value == "partial"
    assert workflow.attempts == [False, True]


def test_two_malformed_outputs_raise_safe_workflow_error() -> None:
    class BrokenWorkflow(AdkTutorWorkflow):
        async def _run_once(self, **_kwargs):
            raise ValueError("raw provider parser internals")

    with pytest.raises(TutorWorkflowError, match="malformed structured output"):
        asyncio.run(
            BrokenWorkflow(model="test-model").run(
                interaction_id="interaction",
                user_id="user",
                mode=TutorMode.mark,
                context={},
                canvas_image=PNG_BYTES,
                canvas_mime_type="image/png",
                selection_image=None,
                selection_mime_type=None,
            )
        )


def test_workflow_timeout_bounds_the_repair_attempt_too() -> None:
    class SlowRepairWorkflow(AdkTutorWorkflow):
        def __init__(self):
            super().__init__(model="test-model", timeout_seconds=0.01)
            self.attempts: list[bool] = []

        async def _run_once(self, **kwargs):
            self.attempts.append(kwargs["repair_attempt"])
            if not kwargs["repair_attempt"]:
                raise ValueError("malformed output")
            await asyncio.sleep(1)
            return workflow_result()

    workflow = SlowRepairWorkflow()
    with pytest.raises(TutorWorkflowError, match="timed out"):
        asyncio.run(
            workflow.run(
                interaction_id="interaction",
                user_id="user",
                mode=TutorMode.hint,
                context={},
                canvas_image=PNG_BYTES,
                canvas_mime_type="image/png",
                selection_image=None,
                selection_mime_type=None,
            )
        )

    assert workflow.attempts == [False, True]
