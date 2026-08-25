"""Cold-start skill generation, with a stubbed workflow and no provider call."""

from __future__ import annotations

import asyncio

import pytest
from sqlmodel import Session, SQLModel, create_engine

from app.database import CourseRepository
from app.models.enums import SkillOrigin
from app.models.skill import Skill
from app.schemas.documents import ChunkMetadata, DocumentType
from app.services.skill_generation import bootstrap_first_skill

CHAIN_RULE = {
    "id": "chain-rule",
    "name": "Chain rule",
    "description": "Differentiate a composite function.",
    "difficulty_band": 0.5,
    "prereqs": [],
    "keywords": ["composite function"],
    "question_forms": ["differentiate a nested expression"],
}

@pytest.fixture
def session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


class StubWorkflow:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls: list[dict] = []

    async def run(self, *, source_text, existing_skills=None, emergent=False):
        self.calls.append(
            {"source_text": source_text, "existing_skills": existing_skills, "emergent": emergent}
        )
        return next(self.responses)


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


def test_bootstrap_first_skill_persists_exactly_one_skill(session, tmp_path):
    repo = CourseRepository(tmp_path / "db.sqlite")
    _seed_document(repo, course_id="calc1", document_id="doc1", texts=["chain rule text"])
    workflow = StubWorkflow([[CHAIN_RULE]])

    report = asyncio.run(bootstrap_first_skill(session, "calc1", repo, workflow))
    assert report is not None
    assert report.added == ["calc1.chain-rule"]
    assert len(workflow.calls) == 1
    assert workflow.calls[0]["emergent"] is True
    assert workflow.calls[0]["existing_skills"] == []


def test_bootstrap_first_skill_uses_only_one_document(session, tmp_path):
    # list_documents orders most-recently-updated first (same convention
    # _resolve_target_document's own fallback uses); doc2 lands there.
    repo = CourseRepository(tmp_path / "db.sqlite")
    _seed_document(repo, course_id="calc1", document_id="doc1", texts=["from doc1"])
    _seed_document(repo, course_id="calc1", document_id="doc2", texts=["from doc2"])
    workflow = StubWorkflow([[CHAIN_RULE]])

    asyncio.run(bootstrap_first_skill(session, "calc1", repo, workflow))
    text = workflow.calls[0]["source_text"]
    assert "from doc2" in text
    assert "from doc1" not in text


def test_bootstrap_first_skill_returns_none_without_documents(session, tmp_path):
    repo = CourseRepository(tmp_path / "db.sqlite")
    workflow = StubWorkflow([])
    result = asyncio.run(bootstrap_first_skill(session, "calc1", repo, workflow))
    assert result is None
    assert workflow.calls == []
