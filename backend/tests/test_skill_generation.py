"""The generation service: source gathering, the content-hash no-op guard,
and additive persistence via merge_generated — with a stubbed workflow, no
provider call."""

from __future__ import annotations

import asyncio

import pytest
from sqlmodel import Session, SQLModel, create_engine

from app.database import CourseRepository
from app.models.enums import SkillOrigin
from app.models.skill import Skill
from app.models.skill_state import SkillState
from app.schemas.documents import ChunkMetadata, DocumentType
from app.services.skill_generation import generate_taxonomy_for_course

CHAIN_RULE = {
    "id": "chain-rule",
    "name": "Chain rule",
    "description": "Differentiate a composite function.",
    "difficulty_band": 0.5,
    "prereqs": [],
    "keywords": ["composite function"],
    "question_forms": ["differentiate a nested expression"],
}
PRODUCT_RULE = {
    "id": "product-rule",
    "name": "Product rule",
    "description": "Differentiate a product of two functions.",
    "difficulty_band": 0.4,
    "prereqs": [],
    "keywords": [],
    "question_forms": [],
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


def test_no_documents_returns_none_without_calling_the_workflow(session, tmp_path):
    repo = CourseRepository(tmp_path / "db.sqlite")
    workflow = StubWorkflow([])
    result = asyncio.run(
        generate_taxonomy_for_course(
            session, "calc1", repo, workflow, max_source_chars=1000
        )
    )
    assert result is None
    assert workflow.calls == []


def test_first_generation_persists_skills_as_generated(session, tmp_path):
    repo = CourseRepository(tmp_path / "db.sqlite")
    _seed_document(repo, course_id="calc1", document_id="doc1", texts=["chain rule text"])
    workflow = StubWorkflow([[CHAIN_RULE, PRODUCT_RULE]])

    report = asyncio.run(
        generate_taxonomy_for_course(session, "calc1", repo, workflow, max_source_chars=1000)
    )
    assert report is not None
    assert set(report.added) == {"calc1.chain-rule", "calc1.product-rule"}
    assert len(workflow.calls) == 1
    assert "chain rule text" in workflow.calls[0]["source_text"]

    persisted = session.get(Skill, "calc1.chain-rule")
    assert persisted is not None
    assert persisted.origin == SkillOrigin.GENERATED


def test_unchanged_document_set_is_a_noop_on_second_call(session, tmp_path):
    repo = CourseRepository(tmp_path / "db.sqlite")
    _seed_document(repo, course_id="calc1", document_id="doc1", texts=["text"])
    workflow = StubWorkflow([[CHAIN_RULE]])

    first = asyncio.run(
        generate_taxonomy_for_course(session, "calc1", repo, workflow, max_source_chars=1000)
    )
    assert first is not None
    assert len(workflow.calls) == 1

    second = asyncio.run(
        generate_taxonomy_for_course(session, "calc1", repo, workflow, max_source_chars=1000)
    )
    assert second is None
    assert len(workflow.calls) == 1  # the model was not called again


def test_a_new_document_triggers_regeneration_and_preserves_skillstate(session, tmp_path):
    repo = CourseRepository(tmp_path / "db.sqlite")
    _seed_document(repo, course_id="calc1", document_id="doc1", texts=["chain rule text"])
    workflow = StubWorkflow([[CHAIN_RULE], [CHAIN_RULE, PRODUCT_RULE]])

    asyncio.run(
        generate_taxonomy_for_course(session, "calc1", repo, workflow, max_source_chars=1000)
    )
    session.add(
        SkillState(student_id="stu1", course_id="calc1", skill_id="calc1.chain-rule", mastery=0.81)
    )
    session.commit()

    _seed_document(repo, course_id="calc1", document_id="doc2", texts=["product rule text"])
    report = asyncio.run(
        generate_taxonomy_for_course(session, "calc1", repo, workflow, max_source_chars=1000)
    )
    assert report is not None
    assert len(workflow.calls) == 2
    assert "calc1.chain-rule" in report.updated
    assert "calc1.product-rule" in report.added

    state = session.get(SkillState, ("stu1", "calc1.chain-rule"))
    assert state is not None
    assert state.mastery == 0.81  # regeneration never touched progress


def test_existing_skills_are_offered_to_the_workflow_as_prereq_context(session, tmp_path):
    repo = CourseRepository(tmp_path / "db.sqlite")
    session.add(Skill(id="calc1.root", course_id="calc1", name="Root", description="d",
                      difficulty_band=0.2, prereqs=[], origin=SkillOrigin.SEED))
    session.commit()
    _seed_document(repo, course_id="calc1", document_id="doc1", texts=["text"])
    workflow = StubWorkflow([[CHAIN_RULE]])

    asyncio.run(
        generate_taxonomy_for_course(session, "calc1", repo, workflow, max_source_chars=1000)
    )
    offered = workflow.calls[0]["existing_skills"]
    assert {"id": "calc1.root", "name": "Root"} in offered


def test_source_text_samples_across_documents_within_the_char_cap(session, tmp_path):
    repo = CourseRepository(tmp_path / "db.sqlite")
    _seed_document(repo, course_id="calc1", document_id="doc_a", texts=["a" * 40])
    _seed_document(repo, course_id="calc1", document_id="doc_b", texts=["b" * 40])
    workflow = StubWorkflow([[CHAIN_RULE]])

    asyncio.run(
        generate_taxonomy_for_course(session, "calc1", repo, workflow, max_source_chars=60)
    )
    text = workflow.calls[0]["source_text"]
    assert len(text) <= 60
    # Round-robin means both documents contributed rather than one dominating.
    assert "a" in text and "b" in text
