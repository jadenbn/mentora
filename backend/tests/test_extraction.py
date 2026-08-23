"""Text extraction from PDF, TXT and MD sources."""

from __future__ import annotations

import pytest

from app.services.extraction import (
    ExtractedPage,
    extract_document,
    extract_pdf,
    extract_text_file,
)
from tests.ingestion_helpers import write_pdf


class TestExtractPdf:
    def test_returns_one_page_per_pdf_page(self, tmp_path):
        path = write_pdf(tmp_path / "d.pdf", ["First page.", "Second page."])

        pages = extract_pdf(path)

        assert [p.page_number for p in pages] == [1, 2]
        assert "First page." in pages[0].text
        assert "Second page." in pages[1].text

    def test_page_numbers_are_one_indexed(self, tmp_path):
        path = write_pdf(tmp_path / "d.pdf", ["only"])

        assert extract_pdf(path)[0].page_number == 1

    def test_blank_pages_are_skipped_but_numbering_still_reflects_position(
        self, tmp_path
    ):
        """A blank page 2 is dropped; page 3 keeps its real number, not 2.

        This matters downstream: a citation of "page 3" must point at the third
        physical page of the document.
        """
        path = write_pdf(tmp_path / "d.pdf", ["Alpha", "", "Gamma"])

        pages = extract_pdf(path)

        assert [p.page_number for p in pages] == [1, 3]
        assert "Gamma" in pages[1].text

    def test_text_is_stripped(self, tmp_path):
        path = write_pdf(tmp_path / "d.pdf", ["Padded"])

        text = extract_pdf(path)[0].text

        assert text == text.strip()

    def test_pdf_with_no_text_yields_no_pages(self, tmp_path):
        path = write_pdf(tmp_path / "blank.pdf", ["", ""])

        assert extract_pdf(path) == []

    def test_accepts_path_and_str(self, tmp_path):
        path = write_pdf(tmp_path / "d.pdf", ["Content"])

        assert len(extract_pdf(path)) == len(extract_pdf(str(path)))


class TestExtractTextFile:
    def test_whole_file_becomes_a_single_page(self, tmp_path):
        path = tmp_path / "notes.txt"
        path.write_text("line one\nline two", encoding="utf-8")

        pages = extract_text_file(path)

        assert len(pages) == 1
        assert pages[0].page_number == 1
        assert pages[0].text == "line one\nline two"

    def test_surrounding_whitespace_is_stripped(self, tmp_path):
        path = tmp_path / "notes.txt"
        path.write_text("\n\n  content  \n\n", encoding="utf-8")

        assert extract_text_file(path)[0].text == "content"

    def test_empty_file_yields_no_pages(self, tmp_path):
        path = tmp_path / "empty.txt"
        path.write_text("   \n  ", encoding="utf-8")

        assert extract_text_file(path) == []

    def test_reads_utf8(self, tmp_path):
        path = tmp_path / "notes.md"
        path.write_text("∫ x dx — naïve", encoding="utf-8")

        assert extract_text_file(path)[0].text == "∫ x dx — naïve"


class TestExtractDocument:
    @pytest.mark.parametrize("suffix", [".txt", ".md"])
    def test_routes_text_suffixes_to_the_text_extractor(self, tmp_path, suffix):
        path = tmp_path / f"notes{suffix}"
        path.write_text("hello", encoding="utf-8")

        assert extract_document(path) == [ExtractedPage(page_number=1, text="hello")]

    def test_routes_pdf_to_the_pdf_extractor(self, tmp_path):
        path = write_pdf(tmp_path / "d.pdf", ["Body"])

        assert "Body" in extract_document(path)[0].text

    @pytest.mark.parametrize("name", ["d.PDF", "notes.TXT", "notes.Md"])
    def test_suffix_matching_is_case_insensitive(self, tmp_path, name):
        path = tmp_path / name
        if path.suffix.lower() == ".pdf":
            write_pdf(path, ["Body"])
        else:
            path.write_text("hello", encoding="utf-8")

        assert extract_document(path)

    @pytest.mark.parametrize("name", ["archive.zip", "sheet.xlsx", "noextension"])
    def test_unsupported_types_raise_value_error(self, tmp_path, name):
        path = tmp_path / name
        path.write_text("whatever", encoding="utf-8")

        with pytest.raises(ValueError, match="Unsupported file type"):
            extract_document(path)
