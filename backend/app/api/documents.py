"""API routes for document upload and retrieval."""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

import pymupdf
from fastapi import APIRouter, Depends, UploadFile, File, Form, HTTPException

from app.api.dependencies import get_course_repository
from app.config import missing_indexing_settings
from app.database import CourseRepository
from app.schemas.documents import CourseDocument, DocumentType, IngestionResult
from app.services.ingestion import DocumentIndexingError, ingest_document

router = APIRouter(prefix="/api/courses/{course_id}", tags=["documents"])
MAX_DOCUMENT_BYTES = 20 * 1024 * 1024
ALLOWED_SUFFIXES = (".pdf", ".txt", ".md")


@router.post("/documents", response_model=IngestionResult)
async def upload_document(
    course_id: str,
    file: UploadFile = File(...),
    document_type: DocumentType = Form(DocumentType.other),
    repository: CourseRepository = Depends(get_course_repository),
):
    """Upload a course document, extract it, chunk it, and persist it."""
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise HTTPException(400, f"Unsupported file type: {suffix}")

    data = await file.read(MAX_DOCUMENT_BYTES + 1)
    if not data:
        raise HTTPException(400, "document cannot be empty")
    if len(data) > MAX_DOCUMENT_BYTES:
        raise HTTPException(413, "document is too large")
    if suffix == ".pdf" and not data.startswith(b"%PDF-"):
        raise HTTPException(415, "document does not contain a valid PDF signature")

    missing = missing_indexing_settings()
    if missing:
        raise HTTPException(
            503,
            detail={
                "message": "Course indexing is not configured on this server",
                "missing_settings": missing,
            },
        )

    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(data)
        tmp_path = tmp.name

    try:
        try:
            result = await asyncio.to_thread(
                ingest_document,
                file_path=tmp_path,
                course_id=course_id,
                document_type=document_type,
                filename=file.filename or Path(tmp_path).name,
                repository=repository,
            )
        except (UnicodeDecodeError, ValueError) as exc:
            raise HTTPException(422, "document contains no readable text") from exc
        except pymupdf.FileDataError as exc:
            # PyMuPDF exposes several provider-specific parse exceptions. Do
            # not leak their internals or a path to the temporary upload.
            raise HTTPException(422, "document could not be read") from exc
        except DocumentIndexingError as exc:
            raise HTTPException(
                502,
                "Document text was saved, but semantic indexing failed; re-upload to retry",
            ) from exc
    finally:
        Path(tmp_path).unlink(missing_ok=True)

    return result


@router.get("/documents", response_model=list[CourseDocument])
async def list_documents(
    course_id: str,
    repository: CourseRepository = Depends(get_course_repository),
) -> list[CourseDocument]:
    return repository.list_documents(course_id)
