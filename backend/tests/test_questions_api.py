from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from app.agents.workflow_errors import QuestionWorkflowError, QuestionWorkflowTimeout
from app.api.dependencies import get_course_repository
from app.api.questions import get_question_service
from app.db import engine
from app.main import app
from app.models.enums import SkillOrigin
from app.models.skill import Skill
from app.services import attribution
from app.schemas.documents import ChunkMetadata, DocumentType
from app.schemas.problems import GeneratedProblem, ProblemContext
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
    assert response.json()["problem"]["id"] == "problem_1"
    assert response.json()["skills"] == []
    assert service.calls == [{
        "course_id": "course_1",
        "document_id": "doc_1",
        "question_request": "A chain-rule question",
    }]


def test_generation_response_includes_the_attributed_skills():
    """The route looks up whatever QuestionService.generate() already
    attributed via problem_skills and returns it alongside the problem, so a
    client (manual-generate flow) can show/record against it exactly like
    next-problem's response does — this is the fix for problems generated
    via /questions/generate never being attributable to any skill."""
    course_id = "course_skills_lookup"
    document_id = "doc_skills_lookup"

    class AttributingStubService:
        """Persists via the real repository and session, like
        QuestionService.generate does."""

        def __init__(self, repository, session) -> None:
            self.repository = repository
            self.session = session

        async def generate(self, **kwargs):
            chunks = self.repository.get_chunks(
                course_id=kwargs["course_id"], document_id=kwargs["document_id"]
            )
            generated = self.repository.create_problem(
                problem=ProblemContext(
                    id="problem_with_skill",
                    course_id=kwargs["course_id"],
                    document_id=kwargs["document_id"],
                    source="generated",
                    prompt="Differentiate a nested function.",
                ),
                grounding_chunk_ids=[chunks[0].chunk_id],
            )
            attribution.set_problem_skills(self.session, generated.id, [f"{course_id}.chain-rule"])
            return generated

    with TestClient(app) as http:
        with Session(engine) as session:
            session.add(
                Skill(
                    id=f"{course_id}.chain-rule",
                    course_id=course_id,
                    name="Chain rule",
                    description="d",
                    difficulty_band=0.6,
                    prereqs=[],
                    origin=SkillOrigin.GENERATED,
                )
            )
            session.commit()

        repository = get_course_repository()
        repository.replace_document(
            document_id=document_id,
            course_id=course_id,
            filename="lecture.pdf",
            document_type=DocumentType.lecture,
            total_pages=1,
            chunks=[
                ChunkMetadata(
                    chunk_id=f"chunk_{document_id}_00000",
                    course_id=course_id,
                    document_id=document_id,
                    chunk_index=0,
                    filename="lecture.pdf",
                    page=1,
                    document_type=DocumentType.lecture,
                    text="The chain rule differentiates a composite function.",
                )
            ],
        )
        app.dependency_overrides[get_question_service] = lambda: AttributingStubService(
            repository, Session(engine)
        )

        response = http.post(
            f"/api/courses/{course_id}/questions/generate",
            json={"document_id": document_id, "question_request": "Conceptual"},
        )
    app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["problem"]["id"] == "problem_with_skill"
    assert body["skills"] == [
        {"id": f"{course_id}.chain-rule", "name": "Chain rule", "difficulty_band": 0.6}
    ]


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
