"""Orchestration.

Three responsibilities: mint the interaction id, hand the workflow what it
needs, and put the safety policy between model output and the wire.

The workflow port is declared here rather than in the provider adapter, so
this module — and everything that tests it — stays free of a provider SDK.
"""

from __future__ import annotations

import logging
from typing import Protocol
from uuid import uuid4

from app.schemas.tutor import (
    NormalizedBounds,
    TutorMode,
    TutorPlan,
    TutorResponse,
)
from app.schemas.problems import GroundedProblem, GroundingChunk, ProblemContext
from app.engine import LearnerContext
from app.services.tutor_policy import apply_safety_policy

logger = logging.getLogger(__name__)


class TutorWorkflow(Protocol):
    async def run(
        self,
        *,
        mode: TutorMode,
        canvas_image: bytes,
        canvas_mime_type: str,
        prior_annotations: list[NormalizedBounds],
        problem: ProblemContext | None,
        course_context: list[GroundingChunk],
        learner: LearnerContext | None = None,
    ) -> TutorPlan: ...


class ProblemRepository(Protocol):
    def get_grounded_problem(
        self, *, course_id: str, problem_id: str
    ) -> GroundedProblem | None: ...


class TutorService:
    def __init__(
        self,
        *,
        workflow: TutorWorkflow,
        repository: ProblemRepository | None = None,
    ) -> None:
        self.workflow = workflow
        self.repository = repository

    async def analyze(
        self,
        *,
        course_id: str,
        mode: TutorMode,
        canvas_image: bytes,
        canvas_mime_type: str,
        prior_annotations: list[NormalizedBounds],
        problem_context: ProblemContext | None = None,
        learner: LearnerContext | None = None,
    ) -> TutorResponse:
        problem = problem_context
        course_context: list[GroundingChunk] = []
        if problem_context is not None and problem_context.course_id == course_id and self.repository:
            try:
                grounded = self.repository.get_grounded_problem(
                    course_id=course_id,
                    problem_id=problem_context.id,
                )
                if grounded is not None:
                    problem = grounded.problem
                    course_context = grounded.chunks
            except Exception:
                # A local retrieval failure must not take down otherwise usable
                # tutoring. The browser-supplied prompt remains the fallback.
                logger.exception("could not load grounded problem context")
        plan = await self.workflow.run(
            mode=mode,
            canvas_image=canvas_image,
            canvas_mime_type=canvas_mime_type,
            prior_annotations=prior_annotations,
            problem=problem,
            course_context=course_context,
            learner=learner,
        )
        safe = apply_safety_policy(plan)
        return TutorResponse(interaction_id=uuid4().hex, **safe.model_dump())
