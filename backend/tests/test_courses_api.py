from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.api.dependencies import get_course_repository
from app.database import CourseRepository
from app.main import app


@pytest.fixture
def client(tmp_path):
    repository = CourseRepository(tmp_path / "db.sqlite")
    app.dependency_overrides[get_course_repository] = lambda: repository
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_seed_courses_are_present(client):
    ids = {course["id"] for course in client.get("/api/courses").json()}
    assert {"course_demo", "course_linear"}.issubset(ids)


def test_create_and_get_a_course(client):
    created = client.post(
        "/api/courses", json={"name": "MATH 301", "description": "Analysis"}
    ).json()
    assert created["name"] == "MATH 301"
    fetched = client.get(f"/api/courses/{created['id']}").json()
    assert fetched == created


def test_getting_a_missing_course_is_404(client):
    assert client.get("/api/courses/does-not-exist").status_code == 404


def test_update_a_course(client):
    created = client.post("/api/courses", json={"name": "Old", "description": "d"}).json()
    updated = client.patch(f"/api/courses/{created['id']}", json={"name": "New"}).json()
    assert updated["name"] == "New"
    assert updated["description"] == "d"


def test_updating_a_missing_course_is_404(client):
    assert client.patch("/api/courses/nope", json={"name": "x"}).status_code == 404


def test_delete_a_course(client):
    created = client.post("/api/courses", json={"name": "Temp", "description": ""}).json()
    response = client.delete(f"/api/courses/{created['id']}")
    assert response.status_code == 204
    assert client.get(f"/api/courses/{created['id']}").status_code == 404


def test_deleting_a_missing_course_is_404(client):
    assert client.delete("/api/courses/nope").status_code == 404


def test_delete_course_cascades_spaces_and_orphaned_data(client, tmp_path):
    course = client.post("/api/courses", json={"name": "Temp", "description": ""}).json()
    course_id = course["id"]
    client.post(f"/api/courses/{course_id}/spaces", json={})

    repository: CourseRepository = app.dependency_overrides[get_course_repository]()
    from app.schemas.documents import ChunkMetadata, DocumentType

    repository.replace_document(
        document_id="doc_x",
        course_id=course_id,
        filename="notes.txt",
        document_type=DocumentType.lecture,
        total_pages=1,
        chunks=[
            ChunkMetadata(
                chunk_id="chunk_x_0",
                document_id="doc_x",
                course_id=course_id,
                chunk_index=0,
                filename="notes.txt",
                page=1,
                document_type=DocumentType.lecture,
                text="hello",
            )
        ],
    )
    from app.schemas.problems import ProblemContext

    repository.create_problem(
        problem=ProblemContext(
            id="problem_x",
            course_id=course_id,
            document_id="doc_x",
            source="generated",
            prompt="Q",
        ),
        grounding_chunk_ids=["chunk_x_0"],
    )

    assert client.delete(f"/api/courses/{course_id}").status_code == 204
    assert repository.list_spaces(course_id) == []
    assert repository.list_documents(course_id) == []
    assert repository.get_grounded_problem(course_id=course_id, problem_id="problem_x") is None
