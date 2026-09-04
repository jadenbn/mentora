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


@pytest.fixture
def course_id(client):
    return client.post("/api/courses", json={"name": "Course", "description": ""}).json()["id"]


def test_creating_a_space_in_a_missing_course_is_404(client):
    assert client.post("/api/courses/nope/spaces", json={}).status_code == 404


def test_create_and_list_spaces(client, course_id):
    created = client.post(f"/api/courses/{course_id}/spaces", json={"title": "Warmup"}).json()
    assert created["title"] == "Warmup"
    assert created["course_id"] == course_id
    assert created["problem"] is None
    listed = client.get(f"/api/courses/{course_id}/spaces").json()
    assert [space["id"] for space in listed] == [created["id"]]


def test_default_title_numbering(client, course_id):
    first = client.post(f"/api/courses/{course_id}/spaces", json={}).json()
    second = client.post(f"/api/courses/{course_id}/spaces", json={}).json()
    third = client.post(f"/api/courses/{course_id}/spaces", json={"title": "  "}).json()
    assert first["title"] == "Space 1"
    assert second["title"] == "Space 2"
    assert third["title"] == "Space 3"


def test_create_space_rejects_a_problem_from_another_course(client, course_id):
    other_course = client.post("/api/courses", json={"name": "Other", "description": ""}).json()["id"]
    response = client.post(
        f"/api/courses/{course_id}/spaces", json={"problem_id": "does-not-exist"}
    )
    assert response.status_code == 400
    assert other_course  # sanity: fixture used


def test_update_space_renames_and_touches(client, course_id):
    created = client.post(f"/api/courses/{course_id}/spaces", json={"title": "Original"}).json()
    renamed = client.patch(
        f"/api/courses/{course_id}/spaces/{created['id']}", json={"title": "Renamed"}
    ).json()
    assert renamed["title"] == "Renamed"

    touched = client.patch(f"/api/courses/{course_id}/spaces/{created['id']}", json={}).json()
    assert touched["title"] == "Renamed"
    assert touched["updated_at"] >= renamed["updated_at"]


def test_update_missing_space_is_404(client, course_id):
    assert client.patch(f"/api/courses/{course_id}/spaces/nope", json={}).status_code == 404


def test_update_space_wrong_course_is_404(client, course_id):
    other_course = client.post("/api/courses", json={"name": "Other", "description": ""}).json()["id"]
    created = client.post(f"/api/courses/{course_id}/spaces", json={}).json()
    response = client.patch(f"/api/courses/{other_course}/spaces/{created['id']}", json={})
    assert response.status_code == 404


def test_delete_space(client, course_id):
    created = client.post(f"/api/courses/{course_id}/spaces", json={}).json()
    assert client.delete(f"/api/courses/{course_id}/spaces/{created['id']}").status_code == 204
    assert client.get(f"/api/courses/{course_id}/spaces").json() == []


def test_delete_missing_space_is_404(client, course_id):
    assert client.delete(f"/api/courses/{course_id}/spaces/nope").status_code == 404
