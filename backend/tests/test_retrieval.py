from __future__ import annotations

from app.database import CourseRepository
from app.schemas.documents import ChunkMetadata, DocumentType
from app.services.retrieval import search_course, search_document


def test_ranked_ids_hydrate_from_sqlite_and_stale_ids_are_skipped(tmp_path, monkeypatch):
    repo = CourseRepository(tmp_path / "db.sqlite")
    chunks = [
        ChunkMetadata(
            chunk_id=f"chunk_doc_1_{index:05d}",
            course_id="course_1",
            document_id="doc_1",
            chunk_index=index,
            filename="book.pdf",
            page=index + 1,
            document_type=DocumentType.lecture,
            text=text,
        )
        for index, text in enumerate(("first", "second"))
    ]
    repo.replace_document(
        document_id="doc_1",
        course_id="course_1",
        filename="book.pdf",
        document_type=DocumentType.lecture,
        total_pages=2,
        chunks=chunks,
    )
    monkeypatch.setattr(
        "app.services.retrieval.query_similar",
        lambda **_kwargs: [
            ("chunk_doc_1_00001", 0.9),
            ("stale", 0.8),
            ("chunk_doc_1_00000", 0.7),
        ],
    )
    results = search_document(
        query="question",
        course_id="course_1",
        document_id="doc_1",
        repository=repo,
    )
    assert [chunk.chunk_id for chunk in results] == [
        "chunk_doc_1_00001",
        "chunk_doc_1_00000",
    ]
    assert [chunk.text for chunk in results] == ["second", "first"]


def _seed_document(repo, *, course_id, document_id, texts):
    chunks = [
        ChunkMetadata(
            chunk_id=f"chunk_{document_id}_{index:05d}",
            course_id=course_id,
            document_id=document_id,
            chunk_index=index,
            filename=f"{document_id}.pdf",
            page=index + 1,
            document_type=DocumentType.lecture,
            text=text,
        )
        for index, text in enumerate(texts)
    ]
    repo.replace_document(
        document_id=document_id,
        course_id=course_id,
        filename=f"{document_id}.pdf",
        document_type=DocumentType.lecture,
        total_pages=len(texts),
        chunks=chunks,
    )


def test_search_course_hydrates_across_documents_and_guards_cross_course_leak(
    tmp_path, monkeypatch
):
    repo = CourseRepository(tmp_path / "db.sqlite")
    _seed_document(repo, course_id="course_1", document_id="doc_a", texts=("a-first",))
    _seed_document(repo, course_id="course_1", document_id="doc_b", texts=("b-first",))
    _seed_document(repo, course_id="course_2", document_id="doc_c", texts=("c-first",))

    # The index leaks a chunk from another course (doc_c) into course_1's
    # ranking; the SQLite row disagrees about course_id, so it must be dropped.
    monkeypatch.setattr(
        "app.services.retrieval.query_similar",
        lambda **_kwargs: [
            ("chunk_doc_b_00000", 0.9),
            ("chunk_doc_c_00000", 0.85),
            ("chunk_doc_a_00000", 0.7),
        ],
    )
    results = search_course(query="question", course_id="course_1", repository=repo)
    assert [chunk.chunk_id for chunk in results] == [
        "chunk_doc_b_00000",
        "chunk_doc_a_00000",
    ]
    assert [chunk.text for chunk in results] == ["b-first", "a-first"]
