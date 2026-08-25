"""POST /work: the tutor grades, the server records, the client scores nothing."""

from __future__ import annotations

import io

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from app.api.learning import router as learning_router  # noqa: F401
from app.api.tutor import get_tutor_service
from app.db import engine
from app.main import app
from app.models.skill_state import SkillState
from app.schemas.documents import ChunkMetadata, DocumentType
from app.schemas.problems import ProblemContext
from app.schemas.tutor import TutorResponse, WorkStatus
from app.api.dependencies import get_course_repository

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


class StubTutor:
    def __init__(self, status):
        self.status = status
        self.calls = []

    async def analyze(self, **kwargs):
        self.calls.append(kwargs)
        return TutorResponse(
            interaction_id="i1", status=self.status, summary="s", canvas_actions=[]
        )


@pytest.fixture
def seeded():
    repo = get_course_repository()
    repo.replace_document(
        document_id="doc_1", course_id="calc1", filename="l.txt",
        document_type=DocumentType.lecture, total_pages=1,
        chunks=[ChunkMetadata(
            chunk_id="chunk_doc_1_00000", document_id="doc_1", course_id="calc1",
            chunk_index=0, filename="l.txt", page=1,
            document_type=DocumentType.lecture, text="chain rule",
        )],
    )
    problem = repo.create_problem(
        problem=ProblemContext(id="p1", course_id="calc1", document_id="doc_1",
                               source="generated", prompt="Differentiate."),
        grounding_chunk_ids=["chunk_doc_1_00000"],
    )
    repo.set_problem_skills(problem_id=problem.id, skill_ids=["calc1.derivatives.chain-rule"])
    repo.set_problem_difficulty(problem_id=problem.id, target_difficulty=0.65)
    # calc1.derivatives.chain-rule comes from the real seed taxonomy, loaded
    # by the app lifespan -- inserting our own here would be deleted by it.
    return problem


def _post(client, **overrides):
    form = {
        "session_id": "sess1", "mode": "mark", "problem_id": "p1", "hints_used": "0",
    }
    form.update(overrides)
    return client.post(
        "/api/courses/calc1/work",
        params={"student_id": "stu1"},
        data=form,
        files={"canvas_image": ("c.png", io.BytesIO(PNG), "image/png")},
    )


def _with_tutor(status):
    stub = StubTutor(status)
    app.dependency_overrides[get_tutor_service] = lambda: stub
    return stub


def teardown_function():
    app.dependency_overrides.pop(get_tutor_service, None)


def test_a_correct_mark_records_an_attempt_the_client_never_scored(seeded):
    _with_tutor(WorkStatus.correct)
    with TestClient(app) as client:
        body = _post(client).json()

    assert body["tutor"]["status"] == "correct"
    assert body["attempt"] is not None
    assert "calc1.derivatives.chain-rule" in body["attempt"]["updated_skills"]
    with Session(engine) as s:
        state = s.get(SkillState, ("stu1", "calc1.derivatives.chain-rule"))
        assert state.mastery > 0.5  # a correct attempt raised it
        assert state.attempts == 1


def test_an_uncertain_reading_grades_but_records_nothing(seeded):
    _with_tutor(WorkStatus.uncertain)
    with TestClient(app) as client:
        body = _post(client).json()

    assert body["attempt"] is None
    with Session(engine) as s:
        assert s.get(SkillState, ("stu1", "calc1.derivatives.chain-rule")) is None


def test_a_hint_is_not_a_graded_attempt(seeded):
    _with_tutor(WorkStatus.correct)
    with TestClient(app) as client:
        body = _post(client, mode="hint").json()

    assert body["attempt"] is None
    with Session(engine) as s:
        assert s.get(SkillState, ("stu1", "calc1.derivatives.chain-rule")) is None


def test_difficulty_comes_from_generation_not_the_request(seeded):
    """The client cannot restate how hard the problem was."""
    _with_tutor(WorkStatus.incorrect)
    with TestClient(app) as client:
        _post(client)

    from app.models.attempt import Attempt
    from sqlmodel import select
    with Session(engine) as s:
        attempt = s.exec(select(Attempt)).one()
        assert attempt.difficulty == pytest.approx(0.65)
        assert attempt.correct is False


def test_remarking_the_same_problem_does_not_move_mastery_twice(seeded):
    _with_tutor(WorkStatus.correct)
    with TestClient(app) as client:
        first = _post(client).json()
        second = _post(client).json()

    assert second["attempt"]["attempt_id"] == first["attempt"]["attempt_id"]
    with Session(engine) as s:
        assert s.get(SkillState, ("stu1", "calc1.derivatives.chain-rule")).attempts == 1


def test_an_unknown_problem_is_a_404(seeded):
    _with_tutor(WorkStatus.correct)
    with TestClient(app) as client:
        assert _post(client, problem_id="nope").status_code == 404


def test_the_product_api_no_longer_accepts_a_client_stated_grade():
    with TestClient(app) as client:
        response = client.post(
            "/api/courses/calc1/attempts",
            json={"student_id": "stu1", "session_id": "s", "problem_id": "p",
                  "expected_skills": ["calc1.derivatives.chain-rule"], "difficulty": 0.5,
                  "correct": True},
        )
    assert response.status_code == 405 or response.status_code == 404
