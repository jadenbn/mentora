"""Orchestration.

Three responsibilities: mint the interaction id, hand the workflow what it
needs, and put the safety policy between model output and the wire.

The workflow port is declared here rather than in the provider adapter, so
this module — and everything that tests it — stays free of a provider SDK.
"""

from __future__ import annotations

from typing import Protocol
from uuid import uuid4

from app.schemas.tutor import (
    NormalizedBounds,
    TutorMode,
    TutorPlan,
    TutorResponse,
)
from app.services.tutor_policy import apply_safety_policy


class TutorWorkflow(Protocol):
    async def run(
        self,
        *,
        mode: TutorMode,
        canvas_image: bytes,
        canvas_mime_type: str,
        prior_annotations: list[NormalizedBounds],
    ) -> TutorPlan: ...


class TutorService:
    def __init__(self, *, workflow: TutorWorkflow) -> None:
        self.workflow = workflow

    async def analyze(
        self,
        *,
        room_id: str,
        mode: TutorMode,
        canvas_image: bytes,
        canvas_mime_type: str,
        prior_annotations: list[NormalizedBounds],
    ) -> TutorResponse:
        # room_id is carried but not yet used: it is the retrieval scope, and
        # room grounding lands after the canvas loop works end to end.
        plan = await self.workflow.run(
            mode=mode,
            canvas_image=canvas_image,
            canvas_mime_type=canvas_mime_type,
            prior_annotations=prior_annotations,
        )
        safe = apply_safety_policy(plan)
        # Uncertainties stay server-side: the policy has already turned them
        # into a question placed on the canvas, which is the only form the
        # student needs.
        return TutorResponse(
            interaction_id=uuid4().hex,
            **safe.model_dump(exclude={"uncertainties"}),
        )
