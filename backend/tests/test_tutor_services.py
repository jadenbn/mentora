"""Tests for context assembly, safety policy, and learning delivery."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging

import httpx
import pytest

from app.config import TutorSettings
from app.schemas.tutor import (
    CanvasAnalysis,
    CourseBoundaryDecision,
    LearningObservation,
    LearningObservationType,
    LearningWebhookEnvelope,
    StudentModelSnapshot,
    TutorPlan,
    WorkStatus,
)
from app.services.learning_events import publish_learning_events, webhook_signature
from app.services.tutor_context import (
    CourseContextUnavailable,
    build_retrieval_query,
    retrieve_course_context,
)
from app.services.tutor_service import TutorService
from tests.helpers import PNG_BYTES, retrieval_results, tutor_request, workflow_result


class FakeWorkflow:
    def __init__(self, result):
        self.result = result
        self.calls: list[dict] = []

    async def run(self, **kwargs):
        self.calls.append(kwargs)
        return self.result


def settings(*, webhook_url: str | None = None) -> TutorSettings:
    return TutorSettings(
        gemini_model="test-model",
        learning_metrics_webhook_url=webhook_url,
        learning_metrics_webhook_secret="secret" if webhook_url else None,
        request_timeout_seconds=2,
        retrieval_top_k=5,
    )


def retriever(**_kwargs) -> list[dict]:
    return retrieval_results()


def test_retrieval_query_uses_student_text_but_not_prior_ai_text() -> None:
    query = build_retrieval_query(tutor_request())

    assert "f'(x) = x" in query
    assert "The AI said 2x" not in query


def test_pinecone_results_take_precedence_over_seeded_taxonomy() -> None:
    result = asyncio.run(
        retrieve_course_context(
            tutor_request(),
            top_k=5,
            retriever=retriever,
            seeded_taxonomy_fallback=[
                {
                    "text": "Seeded skill description",
                    "filename": "calc1-seeded-taxonomy",
                    "page": 1,
                    "score": 1.0,
                }
            ],
        )
    )

    assert result.used_seeded_taxonomy_fallback is False
    assert result.references[0].filename == "lecture-3.pdf"


def test_empty_pinecone_results_use_seeded_taxonomy_with_visible_warning(
    caplog,
) -> None:
    caplog.set_level(logging.INFO, logger="uvicorn.error")
    fake = FakeWorkflow(workflow_result())
    service = TutorService(
        settings=settings(),
        workflow=fake,
        retriever=lambda **_kwargs: [],
    )

    result = asyncio.run(
        service.analyze(
            request=tutor_request(),
            canvas_image=PNG_BYTES,
            canvas_mime_type="image/png",
            selection_image=None,
            selection_mime_type=None,
            seeded_taxonomy_fallback=[
                {
                    "text": "Skill: Power rule\nDescription: Differentiate x^n.",
                    "filename": "calc1-seeded-taxonomy",
                    "page": 1,
                    "document_type": "course_taxonomy",
                    "score": 1.0,
                }
            ],
        )
    )

    assert result.response.grounding_references[0].filename == "calc1-seeded-taxonomy"
    assert "built-in seeded course taxonomy" in result.response.warnings[0]
    assert fake.calls[0]["context"]["retrieved_course_context"][0][
        "document_type"
    ] == "course_taxonomy"
    assert "stage=retrieval_seed_fallback" in caplog.text


def test_pinecone_failure_is_not_hidden_by_seeded_taxonomy(caplog) -> None:
    caplog.set_level(logging.INFO, logger="uvicorn.error")

    def failing_retriever(**_kwargs):
        raise RuntimeError("provider unavailable")

    with pytest.raises(CourseContextUnavailable, match="retrieval failed"):
        asyncio.run(
            retrieve_course_context(
                tutor_request(),
                top_k=5,
                retriever=failing_retriever,
                seeded_taxonomy_fallback=[
                    {
                        "text": "Seeded skill description",
                        "filename": "calc1-seeded-taxonomy",
                        "page": 1,
                        "score": 1.0,
                    }
                ],
            )
        )
    assert "stage=retrieval_provider_error" in caplog.text
    assert "provider_exception=RuntimeError" in caplog.text


def test_service_enriches_learning_events_and_queues_webhook() -> None:
    observation = LearningObservation(
        type=LearningObservationType.mistake,
        topic="derivatives",
        skill="power rule",
        outcome=WorkStatus.incorrect,
        evidence="The coefficient 2 is missing from the derivative.",
        mistake_tag="power-rule-coefficient",
        confidence=0.91,
    )
    raw_result = workflow_result(learning_observations=[observation])
    raw_result.plan.canvas_actions[0].action_id = "model-controlled-id"
    fake = FakeWorkflow(raw_result)
    service = TutorService(
        settings=settings(webhook_url="https://learning.example/events"),
        workflow=fake,
        retriever=retriever,
    )
    request = tutor_request()

    result = asyncio.run(
        service.analyze(
            request=request,
            canvas_image=PNG_BYTES,
            canvas_mime_type="image/png",
            selection_image=None,
            selection_mime_type=None,
        )
    )

    assert result.response.learning_delivery.status.value == "queued"
    assert result.webhook_envelope is not None
    event = result.response.learning_events[0]
    assert event.user_id == request.user_id
    assert event.interaction_id == result.response.interaction_id
    assert event.mistake_tag == "power-rule-coefficient"
    assert result.response.grounding_references[0].filename == "lecture-3.pdf"
    assert result.response.canvas_actions[0].action_id != "model-controlled-id"


def test_student_model_snapshot_reaches_agent_context() -> None:
    fake = FakeWorkflow(workflow_result())
    service = TutorService(
        settings=settings(),
        workflow=fake,
        retriever=retriever,
    )
    request = tutor_request().model_copy(
        update={
            "student_model": StudentModelSnapshot(
                attempted_topics=["Chain rule"],
                strengths=["Power rule"],
                total_hints_used=3,
            )
        }
    )

    asyncio.run(
        service.analyze(
            request=request,
            canvas_image=PNG_BYTES,
            canvas_mime_type="image/png",
            selection_image=None,
            selection_mime_type=None,
        )
    )

    student_model = fake.calls[0]["context"]["request"]["student_model"]
    assert student_model["attempted_topics"] == ["Chain rule"]
    assert student_model["strengths"] == ["Power rule"]
    assert student_model["total_hints_used"] == 3


def test_course_boundary_replaces_plan_with_confirmation_only() -> None:
    raw = workflow_result()
    raw = raw.__class__(
        analysis=raw.analysis.model_copy(
            update={
                "course_boundary": CourseBoundaryDecision(
                    requires_confirmation=True,
                    technique="L'Hôpital's rule",
                    message="This technique does not appear in your course yet.",
                    alternatives_available=True,
                )
            }
        ),
        plan=raw.plan,
    )
    service = TutorService(
        settings=settings(),
        workflow=FakeWorkflow(raw),
        retriever=retriever,
    )

    result = asyncio.run(
        service.analyze(
            request=tutor_request(),
            canvas_image=PNG_BYTES,
            canvas_mime_type="image/png",
            selection_image=None,
            selection_mime_type=None,
        )
    )

    assert [action.type for action in result.response.canvas_actions] == ["text"]
    assert result.response.course_boundary.requires_confirmation is True
    assert "does not appear" in result.response.canvas_actions[0].text


def test_uncertain_work_removes_grading_marks_and_learning_claims() -> None:
    result_model = workflow_result(status="uncertain")
    result_model = result_model.__class__(
        analysis=CanvasAnalysis(
            status="uncertain",
            confidence=0.2,
            current_work_summary="The handwriting is not legible.",
        ),
        plan=TutorPlan.model_validate(
            {
                "status": "uncertain",
                "confidence": 0.3,
                "canvas_actions": [
                    {
                        "type": "cross",
                        "target": {"x": 0.2, "y": 0.3, "width": 0.1, "height": 0.1},
                    }
                ],
            }
        ),
    )
    service = TutorService(
        settings=settings(), workflow=FakeWorkflow(result_model), retriever=retriever
    )

    result = asyncio.run(
        service.analyze(
            request=tutor_request(),
            canvas_image=PNG_BYTES,
            canvas_mime_type="image/png",
            selection_image=None,
            selection_mime_type=None,
        )
    )

    assert result.response.status == WorkStatus.uncertain
    assert [action.type for action in result.response.canvas_actions] == ["text"]
    assert result.response.learning_events == []


def test_webhook_signature_uses_hmac_sha256() -> None:
    body = b'{"hello":"world"}'
    expected = hmac.new(b"secret", body, hashlib.sha256).hexdigest()

    assert webhook_signature(body, "secret") == f"sha256={expected}"


def test_webhook_failure_is_reported_without_raising() -> None:
    async def run() -> bool:
        transport = httpx.MockTransport(lambda _request: httpx.Response(503))
        async with httpx.AsyncClient(transport=transport) as client:
            return await publish_learning_events(
                LearningWebhookEnvelope(interaction_id="interaction", events=[]),
                webhook_url="https://learning.example/events",
                webhook_secret="secret",
                client=client,
            )

    assert asyncio.run(run()) is False
