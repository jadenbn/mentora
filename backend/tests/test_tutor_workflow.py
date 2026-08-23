"""Tests for the flat one-call tutor workflow and local validation."""

from __future__ import annotations

import asyncio
import json

import pytest
from google.genai import types

from app.agents.tutor_workflow import (
    AdkTutorWorkflow,
    TutorRateLimitError,
    TutorWireOutput,
    TutorWorkflowError,
    validate_tutor_output,
)
from app.schemas.tutor import TutorMode, WorkStatus
from tests.helpers import PNG_BYTES, workflow_result


def wire_output(**updates) -> dict:
    payload = {
        "status": "partial",
        "confidence": 0.9,
        "observed_work": "y' = 4(3x²+1)6x",
        "uncertainties": [],
        "issues": ["The cube on (3x²+1) is missing."],
        "canvas_actions": [
            {
                "type": "text",
                "position": {"x": 0.45, "y": 0.25},
                "text": "What exponent should remain here?",
            }
        ],
        "summary": "The outer power was reduced but not retained.",
        "warnings": [],
        "learning_observations": [],
        "course_boundary": {
            "requires_confirmation": False,
            "technique": None,
            "message": None,
            "alternatives_available": False,
        },
    }
    payload.update(updates)
    return payload


def test_every_mode_builds_one_distinct_literal_observation_policy() -> None:
    workflow = AdkTutorWorkflow(model="test-model")
    instructions = {
        mode: workflow._build_agent(mode).instruction for mode in TutorMode
    }

    assert "without revealing unfinished solution steps" in instructions[TutorMode.mark]
    assert "smallest useful nudge" in instructions[TutorMode.hint]
    assert "explanation local to the canvas" in instructions[TutorMode.explain]
    assert "stronger scaffolding" in instructions[TutorMode.stuck]
    assert all("literal transcription" in value for value in instructions.values())
    assert all("cube is missing" in value for value in instructions.values())
    assert len(set(instructions.values())) == 4


def test_agent_uses_one_flat_schema_and_low_latency_settings() -> None:
    agent = AdkTutorWorkflow(model="test-model")._build_agent(TutorMode.hint)

    assert agent.output_schema is TutorWireOutput
    provider_schema = json.dumps(TutorWireOutput.model_json_schema())
    assert not any(
        keyword in provider_schema
        for keyword in ["minimum", "maximum", "minLength", "maxLength", "maxItems"]
    )
    assert set(TutorWireOutput.model_json_schema()["required"]) == set(
        TutorWireOutput.model_fields
    )
    assert agent.generate_content_config.max_output_tokens == 1_024
    assert (
        agent.generate_content_config.thinking_config.thinking_level
        == types.ThinkingLevel.MINIMAL
    )
    assert (
        agent.generate_content_config.media_resolution
        == types.MediaResolution.MEDIA_RESOLUTION_MEDIUM
    )
    assert agent.model.retry_options.http_status_codes == [408, 500, 502, 503, 504]


def test_missing_exponent_evidence_cannot_remain_correct() -> None:
    result, _ = validate_tutor_output(
        wire_output(status="correct", issues=["The cube is missing."])
    )

    assert result.observed_work == "y' = 4(3x²+1)6x"
    assert result.status == WorkStatus.partial
    assert all(action.type != "check" for action in result.canvas_actions)


def test_equivalent_unsimplified_answer_can_remain_correct() -> None:
    payload = wire_output(
        status="correct",
        observed_work="y' = 4(3x²+1)³(6x)",
        issues=[],
        canvas_actions=[
            {
                "type": "check",
                "target": {"x": 0.1, "y": 0.2, "width": 0.7, "height": 0.2},
            }
        ],
    )
    payload.pop("summary")
    payload["course_boundary"].pop("technique")
    payload["course_boundary"].pop("message")
    result, _ = validate_tutor_output(payload)

    assert result.status == WorkStatus.correct
    assert [action.type for action in result.canvas_actions] == ["check"]


def test_located_uncertainty_overrides_a_grade() -> None:
    result, _ = validate_tutor_output(
        wire_output(
            status="correct",
            issues=[],
            uncertainties=[
                {
                    "description": "The exponent above the closing parenthesis is unclear.",
                    "target": {"x": 0.52, "y": 0.16, "width": 0.05, "height": 0.08},
                }
            ],
        )
    )

    assert result.status == WorkStatus.uncertain
    assert result.uncertainties[0].target.x == 0.52


def test_invalid_actions_are_dropped_without_discarding_valid_feedback() -> None:
    result, locations = validate_tutor_output(
        wire_output(
            canvas_actions=[
                {
                    "type": "text",
                    "position": {"x": 0.2, "y": 0.3},
                    "text": "Check the exponent.",
                    "target": {"x": 0.1, "y": 0.1, "width": 0.2, "height": 0.2},
                },
                {"type": "circle"},
            ]
        )
    )

    assert [action.type for action in result.canvas_actions] == ["text"]
    assert locations
    assert "Some invalid tutor actions were omitted." in result.warnings


def test_all_invalid_actions_recover_from_agent_issue_without_a_correct_template() -> None:
    result, _ = validate_tutor_output(
        wire_output(canvas_actions=[{"type": "circle"}])
    )

    assert [action.type for action in result.canvas_actions] == ["text"]
    assert result.canvas_actions[0].purpose == "safe_local_recovery"
    assert result.canvas_actions[0].text == "The cube on (3x²+1) is missing."


def run_workflow(workflow: AdkTutorWorkflow, mode: TutorMode = TutorMode.hint):
    return asyncio.run(
        workflow.run(
            interaction_id="interaction",
            user_id="user",
            mode=mode,
            context={},
            canvas_image=PNG_BYTES,
            canvas_mime_type="image/png",
            selection_image=None,
            selection_mime_type=None,
        )
    )


class StubWorkflow(AdkTutorWorkflow):
    def __init__(self, *, error=None, delay: float = 0, timeout: float = 8):
        super().__init__(model="test-model", timeout_seconds=timeout)
        self.error, self.delay, self.attempts = error, delay, 0

    async def _run_once(self, **_kwargs):
        self.attempts += 1
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.error:
            raise self.error
        return workflow_result()


def test_malformed_output_is_not_retried_with_another_model_call() -> None:
    workflow = StubWorkflow(error=ValueError("malformed output"))
    with pytest.raises(TutorWorkflowError, match="malformed structured output"):
        run_workflow(workflow)
    assert workflow.attempts == 1


def test_provider_quota_errors_have_a_distinct_safe_failure() -> None:
    class QuotaError(Exception):
        code = 429

    workflow = StubWorkflow(error=QuotaError("raw provider quota details"))
    with pytest.raises(TutorRateLimitError, match="quota exhausted"):
        run_workflow(workflow, TutorMode.mark)


def test_timeout_bounds_the_single_provider_call() -> None:
    workflow = StubWorkflow(delay=1, timeout=0.01)
    with pytest.raises(TutorWorkflowError, match="timed out"):
        run_workflow(workflow)
    assert workflow.attempts == 1
