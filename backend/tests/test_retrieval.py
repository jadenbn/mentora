from __future__ import annotations

from app.database import CourseRepository
from app.schemas.documents import ChunkMetadata, DocumentType
from app.services.retrieval import search_document


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
