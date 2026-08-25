from __future__ import annotations

import sqlite3

from app.database import CourseRepository
from app.schemas.documents import ChunkMetadata, DocumentType
from app.schemas.problems import ProblemContext


def chunks(document_id="doc_a", course_id="course_a", texts=("alpha", "beta")):
    return [
        ChunkMetadata(
            chunk_id=f"chunk_{document_id}_{index:05d}",
            document_id=document_id,
            course_id=course_id,
            chunk_index=index,
            filename="notes.txt",
            page=index + 1,
            document_type=DocumentType.lecture,
            text=text,
        )
        for index, text in enumerate(texts)
    ]


def store(repo: CourseRepository, texts=("alpha", "beta")):
    return repo.replace_document(
        document_id="doc_a",
        course_id="course_a",
        filename="notes.txt",
        document_type=DocumentType.lecture,
        total_pages=len(texts),
        chunks=chunks(texts=texts),
    )


def test_initialization_preserves_unrelated_tables(tmp_path):
    path = tmp_path / "mentora.db"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE teammate_data (value TEXT)")
        connection.execute("INSERT INTO teammate_data VALUES ('kept')")
    CourseRepository(path)
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT value FROM teammate_data").fetchone()[0] == "kept"


def test_documents_and_chunks_round_trip_in_source_order(tmp_path):
    repo = CourseRepository(tmp_path / "db.sqlite")
    document, replaced = store(repo)
    assert replaced is False
    assert document.total_chunks == 2
    assert [chunk.text for chunk in repo.get_chunks(course_id="course_a", document_id="doc_a")] == [
        "alpha",
        "beta",
    ]


def test_replacing_a_document_is_atomic_and_removes_stale_chunks(tmp_path):
    repo = CourseRepository(tmp_path / "db.sqlite")
    first, _ = store(repo, ("alpha", "beta", "stale"))
    second, replaced = store(repo, ("new alpha", "new beta"))
    assert replaced is True
    assert second.created_at == first.created_at
    assert [c.text for c in repo.get_chunks(course_id="course_a", document_id="doc_a")] == [
        "new alpha",
        "new beta",
    ]


def test_problem_persists_its_ordered_grounding_chunks(tmp_path):
    repo = CourseRepository(tmp_path / "db.sqlite")
    store(repo)
    problem = ProblemContext(
        id="problem_1",
        course_id="course_a",
        document_id="doc_a",
        source="generated",
        prompt="Use alpha to explain beta.",
    )
    repo.create_problem(
        problem=problem,
        grounding_chunk_ids=["chunk_doc_a_00001", "chunk_doc_a_00000"],
    )
    grounded = repo.get_grounded_problem(course_id="course_a", problem_id="problem_1")
    assert grounded is not None
    assert grounded.problem.prompt == problem.prompt
    assert [chunk.chunk_id for chunk in grounded.chunks] == [
        "chunk_doc_a_00001",
        "chunk_doc_a_00000",
    ]


def test_problem_rejects_chunks_from_another_document(tmp_path):
    repo = CourseRepository(tmp_path / "db.sqlite")
    store(repo)
    problem = ProblemContext(
        id="problem_1",
        course_id="course_a",
        document_id="doc_a",
        source="generated",
        prompt="Question",
    )
    try:
        repo.create_problem(problem=problem, grounding_chunk_ids=["chunk_elsewhere"])
    except ValueError:
        pass
    else:
        raise AssertionError("foreign grounding chunk was accepted")
