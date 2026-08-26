from __future__ import annotations

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
from app.schemas.documents import ChunkMetadata, DocumentType
from app.schemas.problems import ProblemContext
from app.services import attribution
from app.services.question_service import (
    ContextRetrievalError,
    ContextRetrievalNotConfigured,
    DocumentNotFoundError,
)

COURSE_ID = "course_1"
DOCUMENT_ID = "doc_1"


def _seed_document(repository, course_id=COURSE_ID, document_id=DOCUMENT_ID):
    """A real document with one real chunk -- generate() always persists via
    create_problem, whose grounding-chunk FK requires this to already exist."""
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
    return f"chunk_{document_id}_00000"


class StubService:
    """Persists via the real repository, like QuestionService.generate does,
    so the difficulty write generate_question makes afterward (a real FK on
    generated_problems) is satisfied."""

    def __init__(self, repository, chunk_id, error=None):
        self.repository = repository
        self.chunk_id = chunk_id
        self.error = error
        self.calls = []

    async def generate(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return self.repository.create_problem(
            problem=ProblemContext(
                id="problem_1",
                course_id=kwargs["course_id"],
                document_id=kwargs["document_id"],
                source="generated",
                prompt="Differentiate a nested function.",
            ),
            grounding_chunk_ids=[self.chunk_id],
        )


@pytest.fixture
def client():
    repository = get_course_repository()
    chunk_id = _seed_document(repository)
    service = StubService(repository, chunk_id)
    app.dependency_overrides[get_question_service] = lambda: service
    yield TestClient(app), service
    app.dependency_overrides.clear()


def test_generation_returns_a_structured_problem(client):
    http, service = client
    response = http.post(
        f"/api/courses/{COURSE_ID}/questions/generate",
        json={"student_id": "stu1", "document_id": DOCUMENT_ID,
              "question_request": "A chain-rule question"},
    )
    assert response.status_code == 200
    assert response.json()["problem"]["id"] == "problem_1"
    assert response.json()["skills"] == []
    assert service.calls[0]["course_id"] == COURSE_ID
    assert service.calls[0]["document_id"] == DOCUMENT_ID
    assert "A chain-rule question" in service.calls[0]["question_request"]


def test_generation_response_includes_the_attributed_skills():
    """The route looks up whatever QuestionService.generate() already
    attributed via ProblemSkill and returns it alongside the problem, so a
    client can show/record against it without a second lookup."""
    course_id = "course_skills_lookup"
    document_id = "doc_skills_lookup"

    class AttributingStubService:
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
                    origin=SkillOrigin.GENERATED,
                )
            )
            session.commit()

        repository = get_course_repository()
        _seed_document(repository, course_id=course_id, document_id=document_id)
        app.dependency_overrides[get_question_service] = lambda: AttributingStubService(
            repository, Session(engine)
        )

        response = http.post(
            f"/api/courses/{course_id}/questions/generate",
            json={"student_id": "stu1", "document_id": document_id, "question_request": "Conceptual"},
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
    repository = get_course_repository()
    chunk_id = _seed_document(repository)
    app.dependency_overrides[get_question_service] = lambda: StubService(
        repository, chunk_id, error
    )
    with TestClient(app) as http:
        response = http.post(
            f"/api/courses/{COURSE_ID}/questions/generate",
            json={"student_id": "stu1", "document_id": DOCUMENT_ID, "question_request": "Conceptual"},
        )
    app.dependency_overrides.clear()
    assert response.status_code == status
    assert "provider key leaked" not in response.text


def test_a_typed_request_is_trimmed_and_augmented_with_a_difficulty_level(client):
    http, service = client
    response = http.post(
        f"/api/courses/{COURSE_ID}/questions/generate",
        json={"student_id": "stu1", "document_id": DOCUMENT_ID,
              "question_request": "  conceptual  "},
    )
    assert response.status_code == 200
    sent = service.calls[0]["question_request"]
    assert sent.startswith("conceptual")
    assert "difficulty" in sent  # the engine's contribution, appended
    assert service.calls[0]["required_skill_id"] is None  # the student's own topic wins


def test_an_empty_request_lets_the_engine_pick_a_topic(client):
    """No question text describing a topic -- the engine builds the request
    itself. This is "practice next topic", implicit."""
    http, service = client
    response = http.post(
        f"/api/courses/{COURSE_ID}/questions/generate",
        json={"student_id": "stu1", "document_id": DOCUMENT_ID, "question_request": "   "},
    )
    assert response.status_code == 200
    assert service.calls[0]["question_request"]  # the engine still wrote something


def test_large_document_missing_retrieval_configuration_is_explicit():
    repository = get_course_repository()
    chunk_id = _seed_document(repository)
    app.dependency_overrides[get_question_service] = lambda: StubService(
        repository, chunk_id, ContextRetrievalNotConfigured(["PINECONE_API_KEY"])
    )
    with TestClient(app) as http:
        response = http.post(
            f"/api/courses/{COURSE_ID}/questions/generate",
            json={"student_id": "stu1", "document_id": DOCUMENT_ID, "question_request": "Conceptual"},
        )
    app.dependency_overrides.clear()
    assert response.status_code == 503
    assert response.json()["detail"]["missing_settings"] == ["PINECONE_API_KEY"]
