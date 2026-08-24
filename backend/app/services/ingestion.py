"""Orchestrate the full ingestion pipeline.

    extract -> chunk -> SQLite transaction -> embed -> index

Text lands in SQLite and its embedding in Pinecone, joined by `chunk_id`.
SQLite goes first: it is the store of record, and a document with rows but no
vectors is merely unsearchable, where vectors with no rows are pointers into
nothing.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from app.database import CourseRepository
from app.schemas.documents import DocumentType, IngestionResult
from app.services.extraction import extract_document
from app.services.chunking import chunk_pages
from app.services.embeddings import delete_document_vectors, upsert_chunks

_HASH_BLOCK = 1024 * 1024


def compute_document_id(file_path: str | Path, course_id: str) -> str:
    """Deterministic id from course + file contents.

    Content-addressed on purpose: re-uploading the same file to the same course
    yields the same id, so its rows and vectors are replaced instead of stored
    a second time.
    """
    digest = hashlib.sha256()
    digest.update(course_id.encode("utf-8"))
    digest.update(b"\0")
    with Path(file_path).open("rb") as f:
        for block in iter(lambda: f.read(_HASH_BLOCK), b""):
            digest.update(block)
    return f"doc_{digest.hexdigest()[:16]}"


def ingest_document(
    file_path: str | Path,
    course_id: str,
    repository: CourseRepository,
    document_type: DocumentType = DocumentType.other,
    filename: str | None = None,
) -> IngestionResult:
    """Run the full pipeline for a single document.

    Idempotent: ingesting the same file into the same course replaces the
    existing chunks rather than adding duplicates. Nothing is written until
    extraction and chunking have both completed successfully.
    """
    path = Path(file_path)
    # `path` may be a temp file, so prefer the caller's original filename.
    display_name = filename or path.name
    document_id = compute_document_id(path, course_id)

    # 1. Extract
    pages = extract_document(path)

    # 2. Chunk with metadata
    chunks = chunk_pages(
        pages=pages,
        course_id=course_id,
        document_id=document_id,
        filename=display_name,
        document_type=document_type,
    )
    if not pages or not chunks:
        # A PDF of scanned images extracts nothing. Saying so beats recording a
        # document that no search can ever return.
        raise ValueError("document contains no extractable text")

    # 3. Persist the text
    document, replaced = repository.replace_document(
        document_id=document_id,
        course_id=course_id,
        filename=display_name,
        document_type=document_type,
        total_pages=len(pages),
        chunks=chunks,
    )

    # 4. Drop any vectors from a previous ingest of this document. Chunk ids are
    # deterministic, so the upsert overwrites most of them, but a re-chunk can
    # produce fewer and would otherwise strand the tail.
    delete_document_vectors(document_id)

    # 5. Embed and index
    upsert_chunks(chunks)

    return IngestionResult(**document.model_dump(), replaced_existing=replaced)
