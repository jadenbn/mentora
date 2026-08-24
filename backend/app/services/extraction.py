"""Extract text from uploaded room documents (PDF, TXT, MD)."""

from __future__ import annotations

import pymupdf
from dataclasses import dataclass
from pathlib import Path


@dataclass
class ExtractedPage:
    page_number: int  # 1-indexed
    text: str


def extract_pdf(file_path: str | Path) -> list[ExtractedPage]:
    """Extract text from each page of a PDF."""
    pages: list[ExtractedPage] = []
    with pymupdf.open(str(file_path)) as doc:
        for i, page in enumerate(doc):
            text = page.get_text().strip()
            if text:
                pages.append(ExtractedPage(page_number=i + 1, text=text))
    return pages


def extract_text_file(file_path: str | Path) -> list[ExtractedPage]:
    """Treat the entire text/markdown file as a single page."""
    text = Path(file_path).read_text(encoding="utf-8").strip()
    if not text:
        return []
    return [ExtractedPage(page_number=1, text=text)]


def extract_document(file_path: str | Path) -> list[ExtractedPage]:
    """Route to the correct extractor based on file extension."""
    path = Path(file_path)
    suffix = path.suffix.lower()

    if suffix == ".pdf":
        return extract_pdf(path)
    elif suffix in (".txt", ".md"):
        return extract_text_file(path)
    else:
        raise ValueError(f"Unsupported file type: {suffix}")
