"""Splitting extracted pages into metadata-carrying chunks."""

from __future__ import annotations

import pytest

from app.schemas.documents import DocumentType
from app.services.chunking import CHUNK_OVERLAP, CHUNK_SIZE, chunk_pages
from app.services.extraction import ExtractedPage


def make_chunks(pages, **overrides):
    kwargs = {
        "course_id": "course_1",
        "document_id": "doc_1",
        "filename": "lecture.pdf",
        "document_type": DocumentType.lecture,
    }
    kwargs.update(overrides)
    return chunk_pages(pages=pages, **kwargs)


class TestChunkPages:
    def test_no_pages_produces_no_chunks(self):
        assert make_chunks([]) == []

    def test_short_page_stays_a_single_chunk(self):
        pages = [ExtractedPage(page_number=1, text="A short sentence.")]

        chunks = make_chunks(pages)

        assert len(chunks) == 1
        assert chunks[0].text == "A short sentence."

    def test_long_page_is_split_into_several_chunks(self):
        text = " ".join(f"sentence number {i}." for i in range(400))
        pages = [ExtractedPage(page_number=1, text=text)]

        chunks = make_chunks(pages)

        assert len(chunks) > 1

    def test_chunks_respect_the_configured_size(self):
        text = "word " * 2_000
        pages = [ExtractedPage(page_number=1, text=text)]

        for chunk in make_chunks(pages):
            assert len(chunk.text) <= CHUNK_SIZE

    def test_overlap_is_configured_below_chunk_size(self):
        """A splitter whose overlap meets or exceeds its size cannot terminate."""
        assert 0 <= CHUNK_OVERLAP < CHUNK_SIZE

    def test_metadata_is_attached_to_every_chunk(self):
        pages = [ExtractedPage(page_number=4, text="Body text.")]

        chunk = make_chunks(
            pages,
            course_id="course_math_101",
            document_id="doc_abc",
            filename="week4.pdf",
            document_type=DocumentType.exam,
        )[0]

        assert chunk.course_id == "course_math_101"
        assert chunk.document_id == "doc_abc"
        assert chunk.filename == "week4.pdf"
        assert chunk.document_type is DocumentType.exam

    def test_each_chunk_keeps_its_source_page_number(self):
        pages = [
            ExtractedPage(page_number=1, text="alpha " * 400),
            ExtractedPage(page_number=7, text="gamma"),
        ]

        chunks = make_chunks(pages)

        assert {c.page for c in chunks} == {1, 7}
        assert [c.page for c in chunks if "gamma" in c.text] == [7]

    def test_chunks_are_returned_in_page_order(self):
        pages = [
            ExtractedPage(page_number=1, text="first"),
            ExtractedPage(page_number=2, text="second"),
            ExtractedPage(page_number=3, text="third"),
        ]

        assert [c.page for c in make_chunks(pages)] == [1, 2, 3]

    def test_page_content_is_preserved_across_the_split(self):
        pages = [ExtractedPage(page_number=1, text="alpha beta gamma delta")]

        combined = " ".join(c.text for c in make_chunks(pages))

        for word in ("alpha", "beta", "gamma", "delta"):
            assert word in combined

    @pytest.mark.parametrize("document_type", list(DocumentType))
    def test_every_document_type_is_accepted(self, document_type):
        pages = [ExtractedPage(page_number=1, text="Body.")]

        chunks = make_chunks(pages, document_type=document_type)

        assert chunks[0].document_type is document_type
