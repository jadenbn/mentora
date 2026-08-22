"""Orchestrate the full ingestion pipeline: extract -> chunk -> embed -> index."""

from __future__ import annotations

import uuid
from pathlib import Path

from app.schemas.documents import DocumentType, IngestionResult
from app.services.extraction import extract_document
from app.services.chunking import chunk_pages
from app.services.embeddings import upsert_chunks


def ingest_document(
    file_path: str | Path,
    course_id: str,
    document_type: DocumentType = DocumentType.other,
) -> IngestionResult:
    """Run the full pipeline for a single document.

    upload -> extract text -> chunk -> embed/index
    """
    path = Path(file_path)
    document_id = uuid.uuid4().hex[:12]

    # 1. Extract
    pages = extract_document(path)

    # 2. Chunk with metadata
    chunks = chunk_pages(
        pages=pages,
        course_id=course_id,
        document_id=document_id,
        filename=path.name,
        document_type=document_type,
    )

    # 3. Embed and upsert into vector DB
    upsert_chunks(chunks)

    return IngestionResult(
        document_id=document_id,
        filename=path.name,
        total_chunks=len(chunks),
        total_pages=len(pages),
    )
