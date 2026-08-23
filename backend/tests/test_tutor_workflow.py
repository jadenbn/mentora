"""Tests for ADK construction and local structured-output recovery."""

from __future__ import annotations

import asyncio

import pytest
from google.genai import types

from app.agents.tutor_workflow import (
    AdkTutorWorkflow,
    CANVAS_ANALYSIS_RESPONSE_SCHEMA,
    TUTOR_PLAN_RESPONSE_SCHEMA,
    TUTOR_WORKFLOW_RESPONSE_SCHEMA,
    TutorRateLimitError,
    TutorWorkflowError,
    _drop_nulls,
    _normalize_provider_output,
    _validate_or_recover_plan,
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
    assert all("mathematical equivalence" in value for value in instructions.values())
    assert all("no cross or corrective annotation" in value for value in instructions.values())
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


def test_irrelevant_provider_union_fields_are_removed_locally() -> None:
    raw = {
        "plan": {
            "canvas_actions": [
                {
                    "type": "text",
                    "purpose": "hint",
                    "position": {"x": 0.2, "y": 0.3},
                    "text": "This action is valid.",
                    "target": {"x": 0.1, "y": 0.1, "width": 0.2, "height": 0.2},
                    "label": "provider union placeholder",
                }
            ]
        }
    }

    normalized = _normalize_provider_output(raw)

    assert normalized["plan"]["canvas_actions"] == [
        {
            "type": "text",
            "purpose": "hint",
            "position": {"x": 0.2, "y": 0.3},
            "text": "This action is valid.",
        }
    ]


def test_invalid_actions_are_dropped_without_discarding_valid_feedback() -> None:
    analysis = workflow_result().analysis
    plan, dropped, locations = _validate_or_recover_plan(
        {
            "status": "partial",
            "confidence": 0.8,
            "canvas_actions": [
                {
                    "type": "text",
                    "position": {"x": 0.2, "y": 0.3},
                    "text": "Check the exponent.",
                },
                {"type": "circle", "label": "missing target"},
            ],
            "warnings": [],
            "course_boundary": {
                "requires_confirmation": False,
                "alternatives_available": False,
            },
        },
        analysis,
    )

    assert [action.type for action in plan.canvas_actions] == ["text"]
    assert dropped == 1
    assert locations
    assert "Some invalid tutor actions were omitted." in plan.warnings


def test_all_invalid_actions_use_a_safe_local_canvas_fallback() -> None:
    analysis = workflow_result().analysis
    plan, dropped, _locations = _validate_or_recover_plan(
        {
            "status": "partial",
            "confidence": 0.8,
            "canvas_actions": [{"type": "circle"}],
        },
        analysis,
    )

    assert dropped == 1
    assert [action.type for action in plan.canvas_actions] == ["text"]
    assert plan.canvas_actions[0].purpose == "safe_local_recovery"


def test_malformed_analysis_is_not_retried_with_another_provider_call() -> None:
    class BrokenWorkflow(AdkTutorWorkflow):
        def __init__(self):
            super().__init__(model="test-model")
            self.attempts = 0

        async def _run_once(self, **_kwargs):
            self.attempts += 1
            raise ValueError("malformed output")

    workflow = BrokenWorkflow()
    with pytest.raises(TutorWorkflowError, match="malformed structured output"):
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

    assert workflow.attempts == 1


def test_provider_quota_errors_have_a_distinct_safe_failure() -> None:
    class QuotaError(Exception):
        code = 429

    class QuotaWorkflow(AdkTutorWorkflow):
        async def _run_once(self, **_kwargs):
            raise QuotaError("raw provider quota details")

    with pytest.raises(TutorRateLimitError, match="quota exhausted"):
        asyncio.run(
            QuotaWorkflow(model="test-model").run(
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


def test_workflow_timeout_bounds_the_single_provider_call() -> None:
    class SlowWorkflow(AdkTutorWorkflow):
        def __init__(self):
            super().__init__(model="test-model", timeout_seconds=0.01)
            self.attempts = 0

        async def _run_once(self, **_kwargs):
            self.attempts += 1
            await asyncio.sleep(1)
            return workflow_result()

    workflow = SlowWorkflow()
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

    assert workflow.attempts == 1
