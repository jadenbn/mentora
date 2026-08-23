"""Tests for ADK construction and bounded malformed-output repair."""

from __future__ import annotations

import asyncio

import pytest

from app.agents.tutor_workflow import AdkTutorWorkflow, TutorWorkflowError
from app.schemas.tutor import TutorMode
from tests.helpers import PNG_BYTES, workflow_result


def test_every_tutor_mode_builds_a_distinct_planner_policy() -> None:
    workflow = AdkTutorWorkflow(model="test-model")
    instructions = {}

    for mode in TutorMode:
        root = workflow._build_agent(mode)
        planner = next(node for node in root.graph.nodes if node.name == "tutor_planner")
        instructions[mode] = planner.instruction

    assert "do not reveal future solution steps" in instructions[TutorMode.mark]
    assert "smallest useful spatial nudge" in instructions[TutorMode.hint]
    assert "rather than giving a lecture" in instructions[TutorMode.explain]
    assert "stronger scaffolding" in instructions[TutorMode.stuck]
    assert len(set(instructions.values())) == 4


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
