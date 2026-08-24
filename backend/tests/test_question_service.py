from __future__ import annotations

import asyncio

import pytest

from app.database import CourseRepository
from app.schemas.documents import ChunkMetadata, DocumentType
from app.schemas.problems import GroundingChunk, QuestionPlan
from app.services.question_service import (
    ContextRetrievalError,
    DocumentNotFoundError,
    QuestionService,
    serialized_context_chars,
)


class StubQuestionWorkflow:
    def __init__(self, chunk_id="chunk_doc_1_00000"):
        self.chunk_id = chunk_id
        self.calls = []

    async def run(self, **kwargs):
        self.calls.append(kwargs)
        return QuestionPlan(
            prompt="Differentiate a nested function.",
            grounding_chunk_ids=[self.chunk_id],
        )


class StubRetriever:
    def __init__(self, chunks=None, error=None):
        self.chunks = chunks or []
        self.error = error
        self.calls = []

    def search(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return self.chunks


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


def service(repo, workflow, retriever, threshold):
    return QuestionService(
        repository=repo,
        workflow=workflow,
        retriever=retriever,
        full_context_max_chars=threshold,
    )


def test_serialized_context_counts_labels_and_text():
    chunks = [GroundingChunk(chunk_id="chunk_1", page=1, text="abc")]
    assert serialized_context_chars(chunks) == len("chunk_1") + 3 + 32


def test_small_documents_send_all_chunks_and_bypass_retrieval(tmp_path):
    repo = seeded_repo(tmp_path)
    workflow = StubQuestionWorkflow()
    retriever = StubRetriever(error=AssertionError("retrieval should be bypassed"))
    generated = asyncio.run(
        service(repo, workflow, retriever, 10_000).generate(
            course_id="course_1",
            document_id="doc_1",
            question_request="A conceptual question",
        )
    )
    assert generated.prompt == "Differentiate a nested function."
    assert retriever.calls == []
    assert len(workflow.calls[0]["chunks"]) == 2
    assert workflow.calls[0]["question_request"] == "A conceptual question"


def test_large_documents_retrieve_ranked_sqlite_context(tmp_path):
    repo = seeded_repo(tmp_path)
    selected = GroundingChunk(
        chunk_id="chunk_doc_1_00001", page=1, text="worked example"
    )
    workflow = StubQuestionWorkflow(chunk_id=selected.chunk_id)
    retriever = StubRetriever([selected])
    generated = asyncio.run(
        service(repo, workflow, retriever, 1).generate(
            course_id="course_1",
            document_id="doc_1",
            question_request="A difficult applied question",
        )
    )
    assert retriever.calls == [{
        "query": "A difficult applied question",
        "course_id": "course_1",
        "document_id": "doc_1",
        "top_k": 12,
    }]
    assert workflow.calls[0]["chunks"] == [selected]
    grounded = repo.get_grounded_problem(course_id="course_1", problem_id=generated.id)
    assert grounded is not None
    assert [chunk.chunk_id for chunk in grounded.chunks] == [selected.chunk_id]


def test_empty_or_failed_large_document_retrieval_fails_closed(tmp_path):
    repo = seeded_repo(tmp_path)
    for retriever in (StubRetriever(), StubRetriever(error=RuntimeError("secret"))):
        with pytest.raises(ContextRetrievalError):
            asyncio.run(
                service(repo, StubQuestionWorkflow(), retriever, 1).generate(
                    course_id="course_1",
                    document_id="doc_1",
                    question_request="Question",
                )
            )


def test_generation_rejects_a_document_from_another_course(tmp_path):
    repo = seeded_repo(tmp_path)
    with pytest.raises(DocumentNotFoundError):
        asyncio.run(
            service(repo, StubQuestionWorkflow(), StubRetriever(), 10_000).generate(
                course_id="wrong_course",
                document_id="doc_1",
                question_request="Question",
            )
        )
