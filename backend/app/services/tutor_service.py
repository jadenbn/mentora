"""Application service coordinating retrieval, agents, and learning events."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable
from uuid import uuid4

from app.agents.tutor_workflow import TutorWorkflow, TutorWorkflowResult
from app.config import TutorSettings
from app.schemas.tutor import (
    LearningDelivery,
    LearningDeliveryStatus,
    LearningEvent,
    LearningWebhookEnvelope,
    TextAction,
    TutorRequest,
    TutorResponse,
    WorkStatus,
)
from app.services.embeddings import query_similar
from app.services.tutor_context import retrieve_course_context


logger = logging.getLogger("uvicorn.error")


@dataclass(frozen=True)
class TutorServiceResult:
    response: TutorResponse
    webhook_envelope: LearningWebhookEnvelope | None


class TutorService:
    def __init__(
        self,
        *,
        settings: TutorSettings,
        workflow: TutorWorkflow,
        retriever: Callable[..., list[dict]] = query_similar,
    ) -> None:
        self.settings = settings
        self.workflow = workflow
        self.retriever = retriever

    async def analyze(
        self,
        *,
        request: TutorRequest,
        canvas_image: bytes,
        canvas_mime_type: str,
        selection_image: bytes | None,
        selection_mime_type: str | None,
        seeded_taxonomy_fallback: list[dict] | None = None,
    ) -> TutorServiceResult:
        interaction_id = uuid4().hex
        logger.info(
            "tutor.trace stage=service_started request_id=%s interaction_id=%s "
            "mode=%s model=%s",
            request.request_id,
            interaction_id,
            request.mode.value,
            self.settings.gemini_model,
        )
        course_context = await retrieve_course_context(
            request,
            top_k=self.settings.retrieval_top_k,
            retriever=self.retriever,
            seeded_taxonomy_fallback=seeded_taxonomy_fallback,
        )
        logger.info(
            "tutor.trace stage=agent_context_ready request_id=%s interaction_id=%s "
            "excerpt_count=%s seeded_fallback=%s",
            request.request_id,
            interaction_id,
            len(course_context.excerpts),
            course_context.used_seeded_taxonomy_fallback,
        )
        agent_context = {
            "request": request.model_dump(mode="json", exclude_none=True),
            "retrieved_course_context": course_context.excerpts,
        }
        workflow_result = await self.workflow.run(
            interaction_id=interaction_id,
            user_id=request.user_id,
            mode=request.mode,
            context=agent_context,
            canvas_image=canvas_image,
            canvas_mime_type=canvas_mime_type,
            selection_image=selection_image,
            selection_mime_type=selection_mime_type,
        )
        logger.info(
            "tutor.trace stage=workflow_complete request_id=%s interaction_id=%s "
            "analysis_status=%s planned_actions=%s",
            request.request_id,
            interaction_id,
            workflow_result.analysis.status.value,
            len(workflow_result.plan.canvas_actions),
        )
        workflow_result = self._apply_safety_policy(request, workflow_result)
        if course_context.used_seeded_taxonomy_fallback:
            if course_context.fallback_reason == "pinecone_index_missing":
                warning = (
                    "The configured course index was not found; feedback is grounded "
                    "in the built-in seeded course taxonomy."
                )
            else:
                warning = (
                    "No uploaded course excerpts were found; feedback is grounded in "
                    "the built-in seeded course taxonomy."
                )
            workflow_result.plan.warnings.append(warning)

        events = [
            LearningEvent(
                **observation.model_dump(),
                interaction_id=interaction_id,
                request_id=request.request_id,
                user_id=request.user_id,
                course_id=request.course_id,
                session_id=request.session_id,
                problem_id=request.problem_id,
                tutor_mode=request.mode,
                trigger=request.trigger,
                difficulty=request.problem.difficulty,
            )
            for observation in workflow_result.analysis.learning_observations
        ]
        webhook_envelope = None
        delivery_status = LearningDeliveryStatus.disabled
        if events and self.settings.learning_metrics_webhook_url:
            delivery_status = LearningDeliveryStatus.queued
            webhook_envelope = LearningWebhookEnvelope(
                interaction_id=interaction_id,
                events=events,
            )

        boundary = workflow_result.plan.course_boundary
        if workflow_result.analysis.course_boundary.requires_confirmation:
            boundary = workflow_result.analysis.course_boundary
        response = TutorResponse(
            interaction_id=interaction_id,
            request_id=request.request_id,
            status=workflow_result.plan.status,
            confidence=min(
                workflow_result.analysis.confidence,
                workflow_result.plan.confidence,
            ),
            canvas_actions=workflow_result.plan.canvas_actions,
            summary=workflow_result.plan.summary,
            grounding_references=course_context.references,
            warnings=workflow_result.plan.warnings,
            course_boundary=boundary,
            learning_events=events,
            learning_delivery=LearningDelivery(
                status=delivery_status,
                event_count=len(events),
            ),
        )
        return TutorServiceResult(
            response=response,
            webhook_envelope=webhook_envelope,
        )

    @staticmethod
    def _apply_safety_policy(
        request: TutorRequest,
        result: TutorWorkflowResult,
    ) -> TutorWorkflowResult:
        plan = result.plan.model_copy(deep=True)
        boundary = result.analysis.course_boundary
        if not boundary.requires_confirmation:
            boundary = plan.course_boundary
        if boundary.requires_confirmation:
            position = {"x": 0.5, "y": 0.5}
            if request.selection:
                position = {
                    "x": request.selection.bounds.x,
                    "y": request.selection.bounds.y,
                }
            plan.canvas_actions = [
                TextAction(
                    type="text",
                    position=position,
                    text=(
                        boundary.message or "This method may be outside your course."
                    )[:240],
                    purpose="course_boundary_confirmation",
                )
            ]
            plan.course_boundary = boundary

        # Action IDs are backend identifiers, not model-controlled values.
        for action in plan.canvas_actions:
            action.action_id = uuid4().hex

        supported = set(request.client_capabilities.supported_actions)
        if supported:
            filtered = [action for action in plan.canvas_actions if action.type in supported]
            if len(filtered) != len(plan.canvas_actions):
                plan.warnings.append("Some actions were omitted because the client does not support them.")
            plan.canvas_actions = filtered

        if result.analysis.status == WorkStatus.uncertain:
            plan.status = WorkStatus.uncertain
            plan.canvas_actions = [
                action
                for action in plan.canvas_actions
                if action.type not in {"check", "cross"}
            ]
            if not plan.canvas_actions and (
                not supported or "text" in supported
            ):
                position = {"x": 0.5, "y": 0.5}
                if request.selection:
                    position = {
                        "x": request.selection.bounds.x,
                        "y": request.selection.bounds.y,
                    }
                plan.canvas_actions.append(
                    TextAction(
                        type="text",
                        position=position,
                        text="I can’t read this clearly—could you rewrite or select the step?",
                        purpose="request_clarification",
                    )
                )
        return TutorWorkflowResult(analysis=result.analysis, plan=plan)
