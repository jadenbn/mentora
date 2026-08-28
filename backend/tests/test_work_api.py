"""POST /work: the tutor grades, the server records, the client scores nothing."""

from __future__ import annotations

import io

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from app.engine.api.learning import router as learning_router  # noqa: F401
from app.api.tutor import get_tutor_service
from app.db import engine
from app.main import app
from app.engine.models.skill_state import SkillState
from app.engine.accuracy import observed_accuracy
from app.services import attribution
from app.services.taxonomy import seed_all_courses
from app.schemas.documents import ChunkMetadata, DocumentType
from app.schemas.problems import ProblemContext
from app.schemas.tutor import TutorResponse, WorkStatus
from app.api.dependencies import get_course_repository

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


class StubTutor:
    def __init__(self, status, error_tag=None):
        self.status = status
        self.error_tag = error_tag
        self.calls = []

    async def analyze(self, **kwargs):
        self.calls.append(kwargs)
        return TutorResponse(
            interaction_id="i1", status=self.status, summary="s", canvas_actions=[],
            error_tag=self.error_tag,
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
    # Seed the real calc1 taxonomy here rather than relying on the app
    # lifespan: attribution now validates against skill.id, so the skill has
    # to exist before the problem can be attributed to it.
    with Session(engine) as s:
        seed_all_courses(s)
        attribution.set_problem_skills(s, problem.id, ["calc1.derivatives.chain-rule"])
    repo.set_problem_difficulty(problem_id=problem.id, target_difficulty=0.65)
    return problem


def _post(client, **overrides):
    form = {
        "session_id": "sess1", "mode": "mark", "problem_id": "p1",
    }
    form.update(overrides)
    return client.post(
        "/api/courses/calc1/work",
        params={"student_id": "stu1"},
        data=form,
        files={"canvas_image": ("c.png", io.BytesIO(PNG), "image/png")},
    )


def _with_tutor(status, error_tag=None):
    stub = StubTutor(status, error_tag=error_tag)
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
        assert observed_accuracy(state.recent_outcomes) == pytest.approx(1.0)
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

    from app.engine.models.attempt import Attempt
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


def test_a_hint_is_counted_by_the_server_and_lowers_the_later_score(seeded):
    """The client used to report its own hint count.

    `hints_used` was a form field on this route and worth 0.4 of the score,
    so a browser that posted 0 after three hints earned a full mark. The
    server sees every hint request; it counts them itself now, and POST
    /work has no field for the client to state one.
    """
    _with_tutor(WorkStatus.correct)
    with TestClient(app) as client:
        client.post(
            "/api/courses/calc1/work",
            params={"student_id": "stu1"},
            data={"session_id": "sess1", "mode": "hint", "problem_id": "p1"},
            files={"canvas_image": ("c.png", io.BytesIO(PNG), "image/png")},
        )
        body = _post(client).json()

    assert body["attempt"] is not None
    with Session(engine) as s:
        state = s.get(SkillState, ("stu1", "calc1.derivatives.chain-rule"))
        # Correct, but hinted: 0.6, not the 1.0 an unassisted mark earns.
        assert state.recent_outcomes == [pytest.approx(0.6)]
        assert state.hints_used == 1


def test_the_product_api_rejects_a_client_stated_hint_count(seeded):
    _with_tutor(WorkStatus.correct)
    with TestClient(app) as client:
        response = _post(client, hints_used="0")
    # Extra form fields are ignored rather than 422'd, but the count that
    # reaches the score is the server's, and it is zero here.
    assert response.status_code == 200
    with Session(engine) as s:
        state = s.get(SkillState, ("stu1", "calc1.derivatives.chain-rule"))
        assert state.recent_outcomes == [pytest.approx(1.0)]


def test_the_tutors_error_tag_is_stored_on_the_attempt(seeded):
    _with_tutor(WorkStatus.incorrect, error_tag="sign_error")
    with TestClient(app) as client:
        body = _post(client).json()

    assert body["tutor"]["error_tag"] == "sign_error"
    from app.engine.models.attempt import Attempt
    from sqlmodel import select
    with Session(engine) as s:
        attempt = s.exec(select(Attempt)).one()
        assert attempt.error_tag == "sign_error"


def test_the_tutor_receives_a_learner_context_for_an_attributed_problem(seeded):
    """POST /work is the one path with a student identity, so it is the one
    path that can build the tutor's student-model context."""
    stub = _with_tutor(WorkStatus.correct)
    with TestClient(app) as client:
        _post(client)

    assert stub.calls[0]["learner"] is not None
    assert stub.calls[0]["learner"].skill_name == "Chain rule"
