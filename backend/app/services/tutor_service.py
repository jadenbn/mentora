"""Application service coordinating retrieval, tutor output, and learning events."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable
from uuid import uuid4

from app.agents.tutor_workflow import TutorAgentOutput, TutorWorkflow
from app.config import TutorSettings
from app.schemas.tutor import (
    LearningDelivery,
    LearningDeliveryStatus,
    LearningEvent,
    LearningObservationType,
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
        output = await self.workflow.run(
            interaction_id=interaction_id,
            user_id=request.user_id,
            mode=request.mode,
            context={
                "request": request.model_dump(mode="json", exclude_none=True),
                "retrieved_course_context": course_context.excerpts,
            },
            canvas_image=canvas_image,
            canvas_mime_type=canvas_mime_type,
            selection_image=selection_image,
            selection_mime_type=selection_mime_type,
        )
        logger.info(
            "tutor.trace stage=workflow_complete request_id=%s interaction_id=%s "
            "status=%s actions=%s uncertainties=%s",
            request.request_id,
            interaction_id,
            output.status.value,
            len(output.canvas_actions),
            len(output.uncertainties),
        )
        output = self._apply_safety_policy(request, output)

        if course_context.used_seeded_taxonomy_fallback:
            output.warnings.append(
                "The configured course index was not found; feedback is grounded "
                "in the built-in seeded course taxonomy."
                if course_context.fallback_reason == "pinecone_index_missing"
                else "No uploaded course excerpts were found; feedback is grounded "
                "in the built-in seeded course taxonomy."
            )

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
            for observation in output.learning_observations
        ]
        delivery_status = LearningDeliveryStatus.disabled
        webhook_envelope = None
        if events and self.settings.learning_metrics_webhook_url:
            delivery_status = LearningDeliveryStatus.queued
            webhook_envelope = LearningWebhookEnvelope(
                interaction_id=interaction_id,
                events=events,
            )

        return TutorServiceResult(
            response=TutorResponse(
                interaction_id=interaction_id,
                request_id=request.request_id,
                status=output.status,
                confidence=output.confidence,
                canvas_actions=output.canvas_actions,
                summary=output.summary,
                grounding_references=course_context.references,
                warnings=output.warnings[:20],
                course_boundary=output.course_boundary,
                learning_events=events,
                learning_delivery=LearningDelivery(
                    status=delivery_status,
                    event_count=len(events),
                ),
            ),
            webhook_envelope=webhook_envelope,
        )

    @staticmethod
    def _apply_safety_policy(
        request: TutorRequest,
        result: TutorAgentOutput,
    ) -> TutorAgentOutput:
        output = result.model_copy(deep=True)

        if output.uncertainties:
            output.status = WorkStatus.uncertain
        if output.status == WorkStatus.uncertain:
            output.canvas_actions = [
                action
                for action in output.canvas_actions
                if action.type not in {"check", "cross"}
            ]
            output.learning_observations = [
                observation
                for observation in output.learning_observations
                if observation.type
                not in {
                    LearningObservationType.mistake,
                    LearningObservationType.strength,
                }
            ]
            if output.uncertainties and not any(
                action.type == "text" for action in output.canvas_actions
            ):
                uncertainty = output.uncertainties[0]
                output.canvas_actions.append(
                    TextAction(
                        type="text",
                        position={
                            "x": uncertainty.target.x,
                            "y": uncertainty.target.y,
                        },
                        text=f"{uncertainty.description} Please rewrite this symbol."[
                            :240
                        ],
                        purpose="clarify_ambiguous_symbol",
                    )
                )
        elif output.status == WorkStatus.correct:
            output.canvas_actions = [
                action
                for action in output.canvas_actions
                if action.type in {"check", "text"}
            ]
            output.learning_observations = [
                observation
                for observation in output.learning_observations
                if observation.type != LearningObservationType.mistake
                and observation.outcome == WorkStatus.correct
            ]

        if output.course_boundary.requires_confirmation:
            position = {"x": 0.5, "y": 0.5}
            if request.selection:
                position = {
                    "x": request.selection.bounds.x,
                    "y": request.selection.bounds.y,
                }
            output.canvas_actions = [
                TextAction(
                    type="text",
                    position=position,
                    text=(
                        output.course_boundary.message
                        or "This method may be outside your course."
                    )[:240],
                    purpose="course_boundary_confirmation",
                )
            ]

        supported = set(request.client_capabilities.supported_actions)
        if supported:
            filtered = [
                action for action in output.canvas_actions if action.type in supported
            ]
            if len(filtered) != len(output.canvas_actions):
                output.warnings.append(
                    "Some actions were omitted because the client does not support them."
                )
            output.canvas_actions = filtered

        for action in output.canvas_actions:
            action.action_id = uuid4().hex
        return output
