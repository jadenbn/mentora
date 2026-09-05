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


def test_initialize_seeds_the_two_demo_courses(tmp_path):
    repo = CourseRepository(tmp_path / "db.sqlite")
    ids = {course.id for course in repo.list_courses()}
    assert {"course_demo", "course_linear"}.issubset(ids)
    # Re-running initialize (e.g. on a second startup) must not duplicate or error.
    repo.initialize()
    ids_again = [course.id for course in repo.list_courses()]
    assert ids_again.count("course_demo") == 1


def test_course_crud_round_trips(tmp_path):
    repo = CourseRepository(tmp_path / "db.sqlite")
    course = repo.create_course(name="MATH 301", description="Analysis")
    assert repo.get_course(course.id) == course

    updated = repo.update_course(course.id, name="MATH 302")
    assert updated is not None
    assert updated.name == "MATH 302"
    assert updated.description == "Analysis"

    assert repo.update_course("missing", name="x") is None

    assert repo.delete_course(course.id) is True
    assert repo.get_course(course.id) is None
    assert repo.delete_course(course.id) is False


def test_deleting_a_course_cascades_spaces_and_cleans_up_orphans(tmp_path):
    repo = CourseRepository(tmp_path / "db.sqlite")
    course = repo.create_course(name="Temp", description="")
    store(repo, texts=("alpha", "beta"))
    # Re-point the stored document/chunks at the fresh course for this test.
    with repo.connect() as connection:
        connection.execute(
            "UPDATE course_documents SET course_id = ? WHERE document_id = 'doc_a'",
            (course.id,),
        )
        connection.execute(
            "UPDATE document_chunks SET course_id = ? WHERE document_id = 'doc_a'",
            (course.id,),
        )
    problem = ProblemContext(
        id="problem_1",
        course_id=course.id,
        document_id="doc_a",
        source="generated",
        prompt="Q",
    )
    repo.create_problem(problem=problem, grounding_chunk_ids=["chunk_doc_a_00000"])
    space = repo.create_space(course_id=course.id, title="Space", problem_id=None)

    assert repo.delete_course(course.id) is True
    assert repo.get_space(space.id) is None
    assert repo.list_documents(course.id) == []
    assert repo.get_grounded_problem(course_id=course.id, problem_id="problem_1") is None


def test_space_crud_round_trips(tmp_path):
    repo = CourseRepository(tmp_path / "db.sqlite")
    course = repo.create_course(name="Course", description="")
    space = repo.create_space(course_id=course.id, title="Warmup", problem_id=None)
    assert space.title == "Warmup"
    assert space.problem is None
    assert repo.get_space(space.id) == space

    renamed = repo.update_space(space.id, title="Renamed")
    assert renamed is not None
    assert renamed.title == "Renamed"

    touched = repo.update_space(space.id)
    assert touched is not None
    assert touched.title == "Renamed"
    assert touched.updated_at >= renamed.updated_at

    assert repo.delete_space(space.id) is True
    assert repo.get_space(space.id) is None
    assert repo.delete_space(space.id) is False


def test_space_default_title_numbering(tmp_path):
    repo = CourseRepository(tmp_path / "db.sqlite")
    course = repo.create_course(name="Course", description="")
    first = repo.create_space(course_id=course.id, title=None, problem_id=None)
    second = repo.create_space(course_id=course.id, title="   ", problem_id=None)
    assert first.title == "Space 1"
    assert second.title == "Space 2"


def test_create_space_validates_problem_ownership(tmp_path):
    repo = CourseRepository(tmp_path / "db.sqlite")
    course_a = repo.create_course(name="A", description="")
    course_b = repo.create_course(name="B", description="")
    store(repo, texts=("alpha", "beta"))
    with repo.connect() as connection:
        connection.execute(
            "UPDATE course_documents SET course_id = ? WHERE document_id = 'doc_a'",
            (course_a.id,),
        )
        connection.execute(
            "UPDATE document_chunks SET course_id = ? WHERE document_id = 'doc_a'",
            (course_a.id,),
        )
    repo.create_problem(
        problem=ProblemContext(
            id="problem_1",
            course_id=course_a.id,
            document_id="doc_a",
            source="generated",
            prompt="Q",
        ),
        grounding_chunk_ids=["chunk_doc_a_00000"],
    )

    space = repo.create_space(course_id=course_a.id, title="ok", problem_id="problem_1")
    assert space.problem is not None
    assert space.problem.id == "problem_1"

    try:
        repo.create_space(course_id=course_b.id, title="bad", problem_id="problem_1")
    except ValueError:
        pass
    else:
        raise AssertionError("problem from another course was accepted")

    try:
        repo.create_space(course_id=course_a.id, title="bad", problem_id="does-not-exist")
    except ValueError:
        pass
    else:
        raise AssertionError("unknown problem id was accepted")
