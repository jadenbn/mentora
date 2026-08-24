"""Orchestration.

The service owns exactly three things: minting the interaction id, handing the
workflow what it needs, and putting the policy between model output and the
wire. Everything else belongs to a layer above or below it.
"""

from __future__ import annotations

import pytest

from app.schemas.tutor import TutorMode, WorkStatus
from app.services.tutor_service import TutorService
from tests import factories as f


def service(workflow: f.StubWorkflow | None = None) -> tuple[TutorService, f.StubWorkflow]:
    stub = workflow or f.StubWorkflow()
    return TutorService(workflow=stub), stub


async def analyze(svc: TutorService, **over):
    kwargs = {
        "room_id": "room_demo",
        "mode": TutorMode.hint,
        "canvas_image": f.PNG,
        "canvas_mime_type": "image/png",
        "prior_annotations": [],
    }
    kwargs.update(over)
    return await svc.analyze(**kwargs)


class TestWorkflowHandoff:
    async def test_the_canvas_image_reaches_the_workflow(self):
        svc, stub = service()
        await analyze(svc)
        assert stub.last_call["canvas_image"] == f.PNG
        assert stub.last_call["canvas_mime_type"] == "image/png"

    async def test_the_mode_reaches_the_workflow(self):
        svc, stub = service()
        await analyze(svc, mode=TutorMode.stuck)
        assert stub.last_call["mode"] == TutorMode.stuck

    async def test_prior_annotations_reach_the_workflow(self):
        # This is what makes follow-up tutoring work: the model has to know
        # which marks on the canvas are its own so it does not grade them.
        svc, stub = service()
        prior = [f.normalized_bounds(), f.normalized_bounds(x=0.6)]
        await analyze(svc, prior_annotations=prior)
        assert stub.last_call["prior_annotations"] == prior

    async def test_a_first_interaction_sends_no_prior_annotations(self):
        svc, stub = service()
        await analyze(svc)
        assert stub.last_call["prior_annotations"] == []


class TestResponseAssembly:
    async def test_every_interaction_gets_a_server_minted_id(self):
        svc, _ = service()
        first = await analyze(svc)
        second = await analyze(svc)
        assert first.interaction_id
        assert first.interaction_id != second.interaction_id

    async def test_the_plans_verdict_and_summary_reach_the_response(self):
        plan = f.plan(status=WorkStatus.incorrect, summary="Check your exponent.")
        svc, _ = service(f.StubWorkflow(result=plan))
        response = await analyze(svc)
        assert response.status == WorkStatus.incorrect
        assert response.summary == "Check your exponent."

    async def test_the_safety_policy_runs_before_anything_reaches_the_wire(self):
        # Sanity that the seam exists at all: an uncertain plan full of marks
        # must not be able to leave the service with those marks intact.
        plan = f.plan(status=WorkStatus.uncertain, actions=[f.check_action()])
        svc, _ = service(f.StubWorkflow(result=plan))
        response = await analyze(svc)
        assert "check" not in f.action_types(response.canvas_actions)


class TestFailurePropagation:
    async def test_a_workflow_failure_is_not_swallowed(self):
        # The API layer is responsible for translating this into a status code;
        # the service must not paper over it with an empty success response.
        svc, _ = service(f.StubWorkflow(error=RuntimeError("provider exploded")))
        with pytest.raises(RuntimeError):
            await analyze(svc)
