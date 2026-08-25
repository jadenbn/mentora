"""next_problem's cold-start branch: bootstrap exactly one skill for a
course that has none, then retry selection — with no provider call (the
route function is invoked directly, dependencies passed explicitly, and
bootstrap_first_skill is stubbed)."""

from __future__ import annotations

import asyncio

import pytest
from fastapi import HTTPException
from sqlmodel import Session, SQLModel, create_engine

from app.agents.workflow_errors import QuestionWorkflowError, QuestionWorkflowTimeout
from app.api import learning as learning_api
from app.database import CourseRepository
from app.models.enums import SkillOrigin
from app.models.skill import Skill
from app.schemas.documents import ChunkMetadata, DocumentType
from app.schemas.problems import ProblemContext


@pytest.fixture
def session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


def _seed_document(repo: CourseRepository, *, course_id: str, document_id: str, texts: list[str]):
    chunks = [
        ChunkMetadata(
            chunk_id=f"chunk_{document_id}_{i:05d}",
            course_id=course_id,
            document_id=document_id,
            chunk_index=i,
            filename=f"{document_id}.pdf",
            page=i + 1,
            document_type=DocumentType.lecture,
            text=text,
        )
        for i, text in enumerate(texts)
    ]
    repo.replace_document(
        document_id=document_id,
        course_id=course_id,
        filename=f"{document_id}.pdf",
        document_type=DocumentType.lecture,
        total_pages=len(texts),
        chunks=chunks,
    )


class StubQuestionService:
    """Persists via the real repository, like QuestionService.generate does,
    so problem_skills' FK to generated_problems is satisfied — just skips the
    provider call and grounds in whatever chunk_index 0 of the document is."""

    def __init__(self, repository: CourseRepository):
        self.repository = repository

    async def generate(self, *, course_id, document_id, question_request, required_skill_id=None):
        chunks = self.repository.get_chunks(course_id=course_id, document_id=document_id)
        generated = self.repository.create_problem(
            problem=ProblemContext(
                id="problem_1",
                course_id=course_id,
                document_id=document_id,
                source="generated",
                prompt="A generated question.",
            ),
            grounding_chunk_ids=[chunks[0].chunk_id],
        )
        # Mirror QuestionService.generate()'s own attribution step, minus a
        # model call: the real service always includes required_skill_id.
        if required_skill_id:
            self.repository.set_problem_skills(
                problem_id=generated.id, skill_ids=[required_skill_id]
            )
        return generated


def test_next_problem_bootstraps_a_skill_for_a_course_with_none(session, tmp_path, monkeypatch):
    repo = CourseRepository(tmp_path / "db.sqlite")
    _seed_document(repo, course_id="calc1", document_id="doc1", texts=["chain rule text"])

    async def fake_bootstrap(session_, course_id, repository, workflow):
        session_.add(
            Skill(id="calc1.chain-rule", course_id="calc1", name="Chain rule",
                  description="d", difficulty_band=0.5, prereqs=[],
                  origin=SkillOrigin.GENERATED)
        )
        session_.commit()
        return object()  # any non-None MergeReport-shaped value; unused by the caller

    monkeypatch.setattr(learning_api, "missing_settings", lambda: [])
    monkeypatch.setattr(learning_api, "bootstrap_first_skill", fake_bootstrap)

    result = asyncio.run(
        learning_api.next_problem(
            course_id="calc1",
            student_id="stu1",
            session=session,
            repository=repo,
            service=StubQuestionService(repo),
        )
    )
    assert result.spec.skill_id == "calc1.chain-rule"
    assert result.problem.id == "problem_1"
    assert repo.get_problem_skills("problem_1") == ["calc1.chain-rule"]


def test_next_problem_still_404s_when_bootstrap_finds_nothing(session, tmp_path, monkeypatch):
    repo = CourseRepository(tmp_path / "db.sqlite")  # no documents at all

    async def fake_bootstrap(session_, course_id, repository, workflow):
        return None

    monkeypatch.setattr(learning_api, "missing_settings", lambda: [])
    monkeypatch.setattr(learning_api, "bootstrap_first_skill", fake_bootstrap)

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            learning_api.next_problem(
                course_id="calc1",
                student_id="stu1",
                session=session,
                repository=repo,
                service=StubQuestionService(repo),
            )
        )
    assert exc_info.value.status_code == 404


def test_next_problem_skips_bootstrap_when_provider_is_unconfigured(session, tmp_path, monkeypatch):
    repo = CourseRepository(tmp_path / "db.sqlite")
    _seed_document(repo, course_id="calc1", document_id="doc1", texts=["chain rule text"])

    calls: list[bool] = []

    async def fake_bootstrap(*args, **kwargs):
        calls.append(True)

    monkeypatch.setattr(learning_api, "missing_settings", lambda: ["GEMINI_API_KEY"])
    monkeypatch.setattr(learning_api, "bootstrap_first_skill", fake_bootstrap)

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            learning_api.next_problem(
                course_id="calc1",
                student_id="stu1",
                session=session,
                repository=repo,
                service=StubQuestionService(repo),
            )
        )
    assert exc_info.value.status_code == 404
    assert calls == []


def test_next_problem_never_calls_bootstrap_when_a_skill_already_exists(session, tmp_path, monkeypatch):
    repo = CourseRepository(tmp_path / "db.sqlite")
    _seed_document(repo, course_id="calc1", document_id="doc1", texts=["chain rule text"])
    session.add(
        Skill(id="calc1.a", course_id="calc1", name="A", description="d",
              difficulty_band=0.3, prereqs=[], origin=SkillOrigin.SEED)
    )
    session.commit()

    calls: list[bool] = []

    async def fake_bootstrap(*args, **kwargs):
        calls.append(True)

    monkeypatch.setattr(learning_api, "missing_settings", lambda: [])
    monkeypatch.setattr(learning_api, "bootstrap_first_skill", fake_bootstrap)

    result = asyncio.run(
        learning_api.next_problem(
            course_id="calc1",
            student_id="stu1",
            session=session,
            repository=repo,
            service=StubQuestionService(repo),
        )
    )
    assert result.spec.skill_id == "calc1.a"
    assert calls == []


class _FailingQuestionService:
    def __init__(self, error: Exception) -> None:
        self._error = error

    async def generate(self, **_kwargs):
        raise self._error


def test_next_problem_maps_a_provider_timeout_to_504(session, tmp_path):
    repo = CourseRepository(tmp_path / "db.sqlite")
    _seed_document(repo, course_id="calc1", document_id="doc1", texts=["chain rule text"])
    session.add(
        Skill(id="calc1.a", course_id="calc1", name="A", description="d",
              difficulty_band=0.3, prereqs=[], origin=SkillOrigin.SEED)
    )
    session.commit()

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            learning_api.next_problem(
                course_id="calc1",
                student_id="stu1",
                session=session,
                repository=repo,
                service=_FailingQuestionService(QuestionWorkflowTimeout("slow")),
            )
        )
    assert exc_info.value.status_code == 504


def test_next_problem_maps_a_provider_failure_to_502_not_a_raw_500(session, tmp_path):
    repo = CourseRepository(tmp_path / "db.sqlite")
    _seed_document(repo, course_id="calc1", document_id="doc1", texts=["chain rule text"])
    session.add(
        Skill(id="calc1.a", course_id="calc1", name="A", description="d",
              difficulty_band=0.3, prereqs=[], origin=SkillOrigin.SEED)
    )
    session.commit()

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            learning_api.next_problem(
                course_id="calc1",
                student_id="stu1",
                session=session,
                repository=repo,
                service=_FailingQuestionService(QuestionWorkflowError("quota exhausted")),
            )
        )
    assert exc_info.value.status_code == 502
