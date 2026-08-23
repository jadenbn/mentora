"""Validation rules on the document schemas."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas.documents import ChunkMetadata, DocumentType, IngestionResult


class TestDocumentType:
    def test_covers_the_document_types_the_product_describes(self):
        assert {t.value for t in DocumentType} == {
            "lecture",
            "assignment",
            "exam",
            "practice_exam",
            "syllabus",
            "formula_sheet",
            "other",
        }

    def test_is_a_string_enum_so_it_serializes_as_its_value(self):
        assert DocumentType.lecture == "lecture"
        assert DocumentType("lecture") is DocumentType.lecture


class TestChunkMetadata:
    def test_accepts_a_complete_chunk(self):
        chunk = ChunkMetadata(
            course_id="c",
            document_id="d",
            filename="f.pdf",
            page=2,
            document_type=DocumentType.lecture,
            text="body",
        )

        assert chunk.page == 2
        assert chunk.document_type is DocumentType.lecture

    def test_coerces_a_document_type_string(self):
        chunk = ChunkMetadata(
            course_id="c",
            document_id="d",
            filename="f.pdf",
            page=1,
            document_type="syllabus",
            text="body",
        )

        assert chunk.document_type is DocumentType.syllabus

    def test_rejects_an_unknown_document_type(self):
        with pytest.raises(ValidationError):
            ChunkMetadata(
                course_id="c",
                document_id="d",
                filename="f.pdf",
                page=1,
                document_type="not_a_type",
                text="body",
            )

    @pytest.mark.parametrize(
        "missing",
        ["course_id", "document_id", "filename", "page", "document_type", "text"],
    )
    def test_every_field_is_required(self, missing):
        payload = {
            "course_id": "c",
            "document_id": "d",
            "filename": "f.pdf",
            "page": 1,
            "document_type": DocumentType.other,
            "text": "body",
        }
        payload.pop(missing)

        with pytest.raises(ValidationError):
            ChunkMetadata(**payload)

    def test_rejects_a_non_numeric_page(self):
        with pytest.raises(ValidationError):
            ChunkMetadata(
                course_id="c",
                document_id="d",
                filename="f.pdf",
                page="page four",
                document_type=DocumentType.other,
                text="body",
            )


class TestIngestionResult:
    def test_reports_the_counts_the_api_returns(self):
        result = IngestionResult(
            document_id="doc_1", filename="f.pdf", total_chunks=3, total_pages=2
        )

        assert result.model_dump() == {
            "document_id": "doc_1",
            "filename": "f.pdf",
            "total_chunks": 3,
            "total_pages": 2,
        }

    @pytest.mark.parametrize(
        "missing", ["document_id", "filename", "total_chunks", "total_pages"]
    )
    def test_every_field_is_required(self, missing):
        payload = {
            "document_id": "d",
            "filename": "f.pdf",
            "total_chunks": 1,
            "total_pages": 1,
        }
        payload.pop(missing)

        with pytest.raises(ValidationError):
            IngestionResult(**payload)
