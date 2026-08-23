"""End-to-end ingestion against real OpenAI and Pinecone.

Skipped unless credentials are present. Run explicitly with:

    pytest -m live

This is the one path the offline suite cannot cover: whether real PDFs extract
sensibly, whether embeddings actually land in the index, and whether a query
retrieves what was just written.
"""

from __future__ import annotations

import os
import uuid

import pytest

from app.schemas.documents import DocumentType
from app.services.ingestion import ingest_document
from app.services.embeddings import query_similar
from tests.ingestion_helpers import write_pdf

REQUIRED = ("OPENAI_API_KEY", "PINECONE_API_KEY", "PINECONE_INDEX_NAME")

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        not all(os.environ.get(name) for name in REQUIRED),
        reason=f"requires {', '.join(REQUIRED)}",
    ),
]


@pytest.fixture
def live_course_id() -> str:
    """A unique course per run, so live data never collides across runs."""
    return f"test_course_{uuid.uuid4().hex[:8]}"


def test_ingest_then_retrieve_round_trip(tmp_path, live_course_id):
    pdf = write_pdf(
        tmp_path / "calculus.pdf",
        [
            "The power rule states that the derivative of x^n is n*x^(n-1).",
            "Integration by parts follows from the product rule.",
        ],
    )

    result = ingest_document(
        file_path=pdf,
        course_id=live_course_id,
        document_type=DocumentType.lecture,
    )

    assert result.total_pages == 2
    assert result.total_chunks >= 2

    matches = query_similar(
        query="What is the power rule?", course_id=live_course_id, top_k=3
    )

    assert matches, "nothing retrieved for a query about indexed content"
    assert any("power rule" in m["text"].lower() for m in matches)
    assert all(m["filename"] == "calculus.pdf" for m in matches)
    assert all(0.0 <= m["score"] <= 1.0 for m in matches)


def test_retrieval_does_not_leak_across_courses(tmp_path, live_course_id):
    notes = tmp_path / "secret.txt"
    notes.write_text("Topic: eigenvalue decomposition.", encoding="utf-8")
    ingest_document(file_path=notes, course_id=live_course_id)

    other_course = f"test_course_{uuid.uuid4().hex[:8]}"
    matches = query_similar(
        query="eigenvalue decomposition", course_id=other_course, top_k=5
    )

    assert matches == []
