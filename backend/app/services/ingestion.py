"""Orchestrate the full ingestion pipeline: extract -> chunk -> embed -> index."""

from __future__ import annotations

import hashlib
from pathlib import Path

from app.schemas.documents import DocumentType, IngestionResult
from app.services.extraction import extract_document
from app.services.chunking import chunk_pages
from app.services.embeddings import delete_document_vectors, upsert_chunks

_HASH_BLOCK = 1024 * 1024


def compute_document_id(file_path: str | Path, room_id: str) -> str:
    """Deterministic id from room + file contents.

    Content-addressed on purpose: re-uploading the same PDF yields the same id,
    so its vector ids are stable and the upsert overwrites the previous copy
    instead of indexing the document a second time.
    """
    digest = hashlib.sha256()
    digest.update(room_id.encode("utf-8"))
    digest.update(b"\0")
    with Path(file_path).open("rb") as f:
        for block in iter(lambda: f.read(_HASH_BLOCK), b""):
            digest.update(block)
    return digest.hexdigest()[:16]


def ingest_document(
    file_path: str | Path,
    room_id: str,
    document_type: DocumentType = DocumentType.other,
    filename: str | None = None,
) -> IngestionResult:
    """Run the full pipeline for a single document.

    upload -> extract text -> chunk -> embed/index

    Idempotent: ingesting the same file into the same room replaces the
    existing chunks rather than adding duplicates.
    """
    path = Path(file_path)
    # `path` may be a temp file, so prefer the caller's original filename.
    display_name = filename or path.name
    document_id = compute_document_id(path, room_id)

    # 1. Extract
    pages = extract_document(path)

    # 2. Chunk with metadata
    chunks = chunk_pages(
        pages=pages,
        room_id=room_id,
        document_id=document_id,
        filename=display_name,
        document_type=document_type,
    )

    # 3. Drop any chunks from a previous ingest of this document. Deterministic
    # ids make the upsert overwrite most of them, but chunking can produce a
    # different count, which would otherwise leave stale vectors behind.
    deleted = delete_document_vectors(document_id)

    # 4. Embed and upsert into vector DB
    upsert_chunks(chunks)

    return IngestionResult(
        document_id=document_id,
        filename=display_name,
        total_chunks=len(chunks),
        total_pages=len(pages),
        replaced_existing=deleted > 0,
    )
