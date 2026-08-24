from __future__ import annotations

import asyncio

import pytest

from app.database import CourseRepository
from app.schemas.documents import ChunkMetadata, DocumentType
from app.schemas.problems import GroundingChunk, QuestionPlan
from app.services.question_service import (
    DocumentNotFoundError,
    QuestionService,
    select_generation_context,
)


class StubQuestionWorkflow:
    def __init__(self, result: QuestionPlan):
        self.result = result
        self.calls = []

    async def run(self, **kwargs):
        self.calls.append(kwargs)
        return self.result


def ground_chunks(count: int, text_size: int = 20):
    return [
        GroundingChunk(chunk_id=f"chunk_{index}", page=index + 1, text=str(index) * text_size)
        for index in range(count)
    ]


def seeded_repo(tmp_path):
    repo = CourseRepository(tmp_path / "db.sqlite")
    chunks = [
        ChunkMetadata(
            chunk_id=f"chunk_doc_1_{index:05d}",
            document_id="doc_1",
            course_id="course_1",
            chunk_index=index,
            filename="lecture.txt",
            page=1,
            document_type=DocumentType.lecture,
            text=text,
        )
        for index, text in enumerate(("chain rule", "worked example"))
    ]
    repo.replace_document(
        document_id="doc_1",
        course_id="course_1",
        filename="lecture.txt",
        document_type=DocumentType.lecture,
        total_pages=1,
        chunks=chunks,
    )
    return repo


def test_small_documents_keep_every_chunk():
    chunks = ground_chunks(4)
    assert select_generation_context(chunks, budget=10_000) == chunks


def test_large_documents_sample_beginning_middle_and_end_windows():
    chunks = ground_chunks(12, text_size=100)
    selected = select_generation_context(chunks, budget=450)
    ids = {chunk.chunk_id for chunk in selected}
    assert "chunk_0" in ids
    assert any(f"chunk_{index}" in ids for index in range(5, 8))
    assert "chunk_11" in ids
    assert len(selected) < len(chunks)


def test_generation_persists_the_problem_and_exact_sources(tmp_path):
    repo = seeded_repo(tmp_path)
    workflow = StubQuestionWorkflow(
        QuestionPlan(
            prompt="Differentiate a nested function.",
            grounding_chunk_ids=["chunk_doc_1_00000"],
        )
    )
    service = QuestionService(repository=repo, workflow=workflow)
    generated = asyncio.run(service.generate(course_id="course_1", document_id="doc_1"))
    grounded = repo.get_grounded_problem(course_id="course_1", problem_id=generated.id)
    assert grounded is not None
    assert grounded.problem.prompt == generated.prompt
    assert [chunk.chunk_id for chunk in grounded.chunks] == ["chunk_doc_1_00000"]
    assert len(workflow.calls[0]["chunks"]) == 2


def test_generation_rejects_a_document_from_another_course(tmp_path):
    repo = seeded_repo(tmp_path)
    workflow = StubQuestionWorkflow(
        QuestionPlan(prompt="Question", grounding_chunk_ids=["chunk_doc_1_00000"])
    )
    service = QuestionService(repository=repo, workflow=workflow)
    with pytest.raises(DocumentNotFoundError):
        asyncio.run(service.generate(course_id="wrong_course", document_id="doc_1"))
