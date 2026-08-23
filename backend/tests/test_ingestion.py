"""The full ingestion pipeline: extract -> chunk -> embed -> index.

Providers are faked, so this exercises the real orchestration offline.
"""

from __future__ import annotations

import pytest

from app.schemas.documents import DocumentType, IngestionResult
from app.services.ingestion import ingest_document
from tests.ingestion_helpers import write_pdf


@pytest.fixture
def notes(tmp_path):
    path = tmp_path / "notes.txt"
    path.write_text("The power rule states that d/dx x^n = n x^(n-1).", encoding="utf-8")
    return path


class TestIngestDocument:
    def test_returns_an_ingestion_result(self, notes, fake_openai, fake_index):
        result = ingest_document(file_path=notes, course_id="course_1")

        assert isinstance(result, IngestionResult)

    def test_reports_the_filename(self, notes, fake_openai, fake_index):
        result = ingest_document(file_path=notes, course_id="course_1")

        assert result.filename == "notes.txt"

    def test_counts_pages_and_chunks(self, tmp_path, fake_openai, fake_index):
        pdf = write_pdf(tmp_path / "d.pdf", ["Page one.", "Page two."])

        result = ingest_document(file_path=pdf, course_id="course_1")

        assert result.total_pages == 2
        assert result.total_chunks >= 2

    def test_writes_one_vector_per_chunk(self, notes, fake_openai, fake_index):
        result = ingest_document(file_path=notes, course_id="course_1")

        assert len(fake_index.upserted_ids) == result.total_chunks

    def test_generates_a_twelve_character_document_id(
        self, notes, fake_openai, fake_index
    ):
        result = ingest_document(file_path=notes, course_id="course_1")

        assert len(result.document_id) == 12
        int(result.document_id, 16)  # hex

    def test_the_document_id_tags_every_stored_vector(
        self, notes, fake_openai, fake_index
    ):
        result = ingest_document(file_path=notes, course_id="course_1")

        stored = [v["metadata"]["document_id"] for v in fake_index.vectors.values()]
        assert set(stored) == {result.document_id}

    def test_course_id_is_stamped_on_every_vector(self, notes, fake_openai, fake_index):
        ingest_document(file_path=notes, course_id="course_math_101")

        courses = {v["metadata"]["course_id"] for v in fake_index.vectors.values()}
        assert courses == {"course_math_101"}

    def test_document_type_defaults_to_other(self, notes, fake_openai, fake_index):
        ingest_document(file_path=notes, course_id="course_1")

        types = {v["metadata"]["document_type"] for v in fake_index.vectors.values()}
        assert types == {"other"}

    def test_document_type_is_recorded_when_supplied(
        self, notes, fake_openai, fake_index
    ):
        ingest_document(
            file_path=notes, course_id="course_1", document_type=DocumentType.syllabus
        )

        types = {v["metadata"]["document_type"] for v in fake_index.vectors.values()}
        assert types == {"syllabus"}

    def test_page_numbers_survive_into_the_index(
        self, tmp_path, fake_openai, fake_index
    ):
        pdf = write_pdf(tmp_path / "d.pdf", ["Alpha", "", "Gamma"])

        ingest_document(file_path=pdf, course_id="course_1")

        pages = {v["metadata"]["page"] for v in fake_index.vectors.values()}
        assert pages == {1, 3}

    def test_accepts_a_string_path(self, notes, fake_openai, fake_index):
        assert ingest_document(file_path=str(notes), course_id="c").total_chunks >= 1

    def test_unsupported_file_type_raises(self, tmp_path, fake_openai, fake_index):
        path = tmp_path / "archive.zip"
        path.write_text("data", encoding="utf-8")

        with pytest.raises(ValueError, match="Unsupported file type"):
            ingest_document(file_path=path, course_id="course_1")

    def test_source_file_is_left_on_disk_by_the_service(
        self, notes, fake_openai, fake_index
    ):
        """Deletion is the API layer's job; the service must not consume input."""
        ingest_document(file_path=notes, course_id="course_1")

        assert notes.exists()


class TestKnownGaps:
    """Current behaviour that is surprising. These pin it down rather than bless it."""

    def test_empty_document_reports_success_with_nothing_indexed(
        self, tmp_path, fake_openai, fake_index
    ):
        """An empty upload returns 200 with zero chunks and no warning.

        A student uploading a scanned, text-free PDF gets a success response and
        an unusable course. Worth surfacing to the caller.
        """
        empty = tmp_path / "empty.txt"
        empty.write_text("   ", encoding="utf-8")

        result = ingest_document(file_path=empty, course_id="course_1")

        assert result.total_pages == 0
        assert result.total_chunks == 0
        assert fake_index.upserted_ids == []

    def test_reuploading_the_same_file_duplicates_every_vector(
        self, notes, fake_openai, fake_index
    ):
        """document_id is a fresh uuid per call, so ids never collide.

        Pinecone therefore accumulates a second full copy instead of replacing
        the first. There is no delete path, so retrieval quality degrades with
        each re-upload of the same document.
        """
        first = ingest_document(file_path=notes, course_id="course_1")
        second = ingest_document(file_path=notes, course_id="course_1")

        assert first.document_id != second.document_id
        assert len(fake_index.vectors) == first.total_chunks + second.total_chunks
