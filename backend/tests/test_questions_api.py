from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from app.agents.workflow_errors import QuestionWorkflowError, QuestionWorkflowTimeout
from app.api.questions import get_question_service
from app.main import app
from app.schemas.problems import GeneratedProblem
from app.services.question_service import (
    ContextRetrievalError,
    ContextRetrievalNotConfigured,
    DocumentNotFoundError,
)


class StubService:
    def __init__(self, error=None):
        self.error = error
        self.calls = []

    async def generate(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return GeneratedProblem(
            id="problem_1",
            course_id=kwargs["course_id"],
            document_id=kwargs["document_id"],
            source="generated",
            prompt="Differentiate a nested function.",
            created_at=datetime.now(UTC),
        )


@pytest.fixture
def client():
    service = StubService()
    app.dependency_overrides[get_question_service] = lambda: service
    yield TestClient(app), service
    app.dependency_overrides.clear()


def test_generation_returns_a_structured_problem(client):
    http, service = client
    response = http.post(
        "/api/courses/course_1/questions/generate",
        json={"document_id": "doc_1", "question_request": "A chain-rule question"},
    )
    assert response.status_code == 200
    assert response.json()["id"] == "problem_1"
    assert service.calls == [{
        "course_id": "course_1",
        "document_id": "doc_1",
        "question_request": "A chain-rule question",
    }]


@pytest.mark.parametrize(
    "error,status",
    [
        (DocumentNotFoundError("missing"), 404),
        (ContextRetrievalError("empty"), 502),
        (QuestionWorkflowError("provider key leaked"), 502),
        (QuestionWorkflowTimeout("slow"), 504),
    ],
)
def test_failures_are_mapped_without_exposing_provider_text(error, status):
    app.dependency_overrides[get_question_service] = lambda: StubService(error)
    with TestClient(app) as http:
        response = http.post(
            "/api/courses/course_1/questions/generate",
            json={"document_id": "doc_1", "question_request": "Conceptual"},
        )
    app.dependency_overrides.clear()
    assert response.status_code == status
    assert "provider key leaked" not in response.text


def test_question_request_is_required_and_trimmed(client):
    http, service = client
    rejected = http.post(
        "/api/courses/course_1/questions/generate",
        json={"document_id": "doc_1", "question_request": "   "},
    )
    assert rejected.status_code == 422
    assert service.calls == []

    accepted = http.post(
        "/api/courses/course_1/questions/generate",
        json={"document_id": "doc_1", "question_request": "  conceptual  "},
    )
    assert accepted.status_code == 200
    assert service.calls[0]["question_request"] == "conceptual"


def test_large_document_missing_retrieval_configuration_is_explicit():
    app.dependency_overrides[get_question_service] = lambda: StubService(
        ContextRetrievalNotConfigured(["PINECONE_API_KEY"])
    )
    with TestClient(app) as http:
        response = http.post(
            "/api/courses/course_1/questions/generate",
            json={"document_id": "doc_1", "question_request": "Conceptual"},
        )
    app.dependency_overrides.clear()
    assert response.status_code == 503
    assert response.json()["detail"]["missing_settings"] == ["PINECONE_API_KEY"]
