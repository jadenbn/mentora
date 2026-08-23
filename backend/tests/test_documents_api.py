"""HTTP behaviour of the document upload and course search routes."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.api import documents as documents_module
from app.schemas.documents import DocumentType
from tests.ingestion_helpers import write_pdf

UPLOAD_URL = "/api/courses/course_1/documents"
SEARCH_URL = "/api/courses/course_1/search"


def upload(client, name: str, content: bytes = b"Some course content.", **data):
    return client.post(
        UPLOAD_URL, files={"file": (name, content, "application/octet-stream")}, data=data
    )


class TestHealth:
    def test_health_is_available(self, client):
        response = client.get("/health")

        assert response.status_code == 200
        assert response.json() == {"status": "ok"}


class TestUploadDocument:
    @pytest.mark.parametrize("name", ["notes.txt", "notes.md"])
    def test_accepts_supported_text_types(self, client, fake_openai, fake_index, name):
        response = upload(client, name)

        assert response.status_code == 200

    def test_accepts_a_pdf(self, client, fake_openai, fake_index, tmp_path):
        pdf = write_pdf(tmp_path / "d.pdf", ["Page one."]).read_bytes()

        response = upload(client, "lecture.pdf", pdf)

        assert response.status_code == 200
        assert response.json()["total_pages"] == 1

    def test_returns_the_ingestion_result_shape(self, client, fake_openai, fake_index):
        body = upload(client, "notes.txt").json()

        assert set(body) == {"document_id", "filename", "total_chunks", "total_pages"}
        assert body["filename"].endswith(".txt")

    def test_indexes_the_content_under_the_path_course_id(
        self, client, fake_openai, fake_index
    ):
        upload(client, "notes.txt")

        courses = {v["metadata"]["course_id"] for v in fake_index.vectors.values()}
        assert courses == {"course_1"}

    def test_document_type_defaults_to_other(self, client, fake_openai, fake_index):
        upload(client, "notes.txt")

        types = {v["metadata"]["document_type"] for v in fake_index.vectors.values()}
        assert types == {"other"}

    def test_document_type_form_field_is_applied(self, client, fake_openai, fake_index):
        upload(client, "notes.txt", document_type=DocumentType.lecture.value)

        types = {v["metadata"]["document_type"] for v in fake_index.vectors.values()}
        assert types == {"lecture"}

    def test_rejects_an_unknown_document_type(self, client, fake_openai, fake_index):
        response = upload(client, "notes.txt", document_type="not_a_type")

        assert response.status_code == 422

    @pytest.mark.parametrize("name", ["archive.zip", "sheet.xlsx", "image.png"])
    def test_rejects_unsupported_extensions(
        self, client, fake_openai, fake_index, name
    ):
        response = upload(client, name)

        assert response.status_code == 400
        assert "Unsupported file type" in response.json()["detail"]

    def test_rejects_a_file_with_no_extension(self, client, fake_openai, fake_index):
        assert upload(client, "README").status_code == 400

    def test_extension_check_is_case_insensitive(
        self, client, fake_openai, fake_index
    ):
        assert upload(client, "NOTES.TXT").status_code == 200

    def test_requires_a_file(self, client):
        assert client.post(UPLOAD_URL).status_code == 422

    def test_rejection_happens_before_any_provider_call(self, client, monkeypatch):
        """A bad extension must not cost an embedding request."""

        def explode(*args, **kwargs):
            raise AssertionError("ingestion must not run for a rejected file type")

        monkeypatch.setattr(documents_module, "ingest_document", explode)

        assert upload(client, "archive.zip").status_code == 400

    def test_temporary_upload_is_deleted_even_when_ingestion_fails(
        self, client, monkeypatch
    ):
        """The route writes the upload to a temp file; the finally must clean it."""
        seen: list[str] = []

        def capture_then_fail(file_path, **kwargs):
            seen.append(file_path)
            raise RuntimeError("ingestion blew up")

        monkeypatch.setattr(documents_module, "ingest_document", capture_then_fail)

        with pytest.raises(RuntimeError):
            upload(client, "notes.txt")

        assert seen and not Path(seen[0]).exists()

    def test_temporary_upload_is_deleted_on_success(
        self, client, monkeypatch, fake_openai, fake_index
    ):
        seen: list[str] = []
        original = documents_module.ingest_document

        def capture(file_path, **kwargs):
            seen.append(file_path)
            assert Path(file_path).exists(), "upload must exist while ingesting"
            return original(file_path=file_path, **kwargs)

        monkeypatch.setattr(documents_module, "ingest_document", capture)

        response = upload(client, "notes.txt")

        assert response.status_code == 200
        assert seen and not Path(seen[0]).exists()


class TestSearchCourseContext:
    def test_returns_matches_for_a_query(self, client, fake_openai, fake_index):
        upload(client, "notes.txt", b"The power rule is a derivative rule.")

        response = client.get(SEARCH_URL, params={"q": "power rule"})

        assert response.status_code == 200
        assert response.json()["results"]

    def test_echoes_the_course_and_query(self, client, fake_openai, fake_index):
        body = client.get(SEARCH_URL, params={"q": "limits"}).json()

        assert body["course_id"] == "course_1"
        assert body["query"] == "limits"

    def test_result_entries_carry_citation_fields(
        self, client, fake_openai, fake_index
    ):
        upload(client, "notes.txt", b"Integration by parts.")

        result = client.get(SEARCH_URL, params={"q": "parts"}).json()["results"][0]

        assert set(result) == {"text", "filename", "page", "document_type", "score"}

    def test_scopes_the_search_to_the_path_course(
        self, client, fake_openai, fake_index
    ):
        client.get("/api/courses/course_xyz/search", params={"q": "anything"})

        assert fake_index.queries[0]["filter"] == {"course_id": {"$eq": "course_xyz"}}

    def test_defaults_to_five_results(self, client, fake_openai, fake_index):
        client.get(SEARCH_URL, params={"q": "anything"})

        assert fake_index.queries[0]["top_k"] == 5

    def test_top_k_is_forwarded(self, client, fake_openai, fake_index):
        client.get(SEARCH_URL, params={"q": "anything", "top_k": 3})

        assert fake_index.queries[0]["top_k"] == 3

    def test_requires_a_query_parameter(self, client, fake_openai, fake_index):
        assert client.get(SEARCH_URL).status_code == 422

    @pytest.mark.parametrize("blank", ["", "   ", "\t\n"])
    def test_rejects_a_blank_query(self, client, fake_openai, fake_index, blank):
        response = client.get(SEARCH_URL, params={"q": blank})

        assert response.status_code == 400
        assert "empty" in response.json()["detail"].lower()

    def test_no_matches_returns_an_empty_result_list(
        self, client, fake_openai, fake_index
    ):
        body = client.get(SEARCH_URL, params={"q": "nothing indexed"}).json()

        assert body["results"] == []


class TestKnownGaps:
    """Behaviour worth tightening, pinned so a change is visible."""

    @pytest.mark.parametrize("top_k", [0, -5])
    def test_top_k_is_not_validated(self, client, fake_openai, fake_index, top_k):
        """Non-positive top_k reaches Pinecone, which rejects it at runtime.

        A Query/Field constraint would turn this into a clean 422.
        """
        response = client.get(SEARCH_URL, params={"q": "anything", "top_k": top_k})

        assert response.status_code == 200
        assert fake_index.queries[0]["top_k"] == top_k
