from __future__ import annotations

import pytest
import pymupdf
from fastapi.testclient import TestClient

import app.api.documents as documents_api
from app.api.dependencies import get_course_repository
from app.database import CourseRepository
from app.main import app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    monkeypatch.setenv("PINECONE_API_KEY", "test")
    monkeypatch.setenv("PINECONE_INDEX_NAME", "test")
    monkeypatch.setattr("app.services.ingestion.delete_document_vectors", lambda _id: 0)
    monkeypatch.setattr("app.services.ingestion.upsert_chunks", lambda chunks: len(chunks))
    repository = CourseRepository(tmp_path / "db.sqlite")
    app.dependency_overrides[get_course_repository] = lambda: repository
    yield TestClient(app)
    app.dependency_overrides.clear()


def upload(client, name="notes.txt", data=b"The chain rule handles nested functions."):
    return client.post(
        "/api/courses/course_1/documents",
        data={"document_type": "lecture"},
        files={"file": (name, data, "text/plain")},
    )


def test_upload_persists_and_lists_a_text_document(client):
    response = upload(client)
    assert response.status_code == 200
    body = response.json()
    assert body["course_id"] == "course_1"
    assert body["replaced_existing"] is False
    listed = client.get("/api/courses/course_1/documents").json()
    assert [item["document_id"] for item in listed] == [body["document_id"]]


def test_reupload_is_reported_as_a_replacement(client):
    upload(client)
    assert upload(client).json()["replaced_existing"] is True


@pytest.mark.parametrize("filename", ["notes.txt", "notes.md"])
def test_invalid_utf8_is_rejected_without_persisting(client, filename):
    response = upload(client, name=filename, data=b"\xff\xfe")
    assert response.status_code == 422
    assert client.get("/api/courses/course_1/documents").json() == []


def test_a_fake_pdf_is_rejected_by_signature(client):
    assert upload(client, name="fake.pdf", data=b"not a pdf").status_code == 415


def test_an_empty_document_is_rejected(client):
    assert upload(client, data=b"").status_code == 400


@pytest.mark.parametrize("filename", ["notes.txt", "notes.md"])
def test_a_text_document_without_content_is_rejected(client, filename):
    assert upload(client, name=filename, data=b" \n\t ").status_code == 422
    assert client.get("/api/courses/course_1/documents").json() == []


def test_a_pdf_without_extractable_text_is_rejected(client):
    document = pymupdf.open()
    document.new_page()
    data = document.tobytes()
    document.close()
    assert upload(client, name="scan.pdf", data=data).status_code == 422
    assert client.get("/api/courses/course_1/documents").json() == []


def test_an_unsupported_extension_is_rejected(client):
    assert upload(client, name="notes.docx").status_code == 400


def test_an_oversized_document_is_rejected_before_persistence(client, monkeypatch):
    monkeypatch.setattr(documents_api, "MAX_DOCUMENT_BYTES", 4)
    assert upload(client, data=b"five!").status_code == 413
    assert client.get("/api/courses/course_1/documents").json() == []


def test_missing_indexing_configuration_names_only_missing_settings(client, monkeypatch):
    monkeypatch.delenv("PINECONE_API_KEY")
    response = upload(client)
    assert response.status_code == 503
    assert response.json()["detail"]["missing_settings"] == ["PINECONE_API_KEY"]


def test_indexing_failure_is_sanitized_and_can_be_retried(client, monkeypatch):
    def fail(_chunks):
        raise RuntimeError("provider secret")

    monkeypatch.setattr("app.services.ingestion.upsert_chunks", fail)
    response = upload(client)
    assert response.status_code == 502
    assert "provider secret" not in response.text
    # SQLite is canonical; the same content can be re-uploaded to repair only
    # the missing vector index without duplicating document rows.
    assert len(client.get("/api/courses/course_1/documents").json()) == 1
