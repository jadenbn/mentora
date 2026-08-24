"""API routes for document upload and retrieval."""

from __future__ import annotations

import tempfile
import shutil
from pathlib import Path

from fastapi import APIRouter, Depends, UploadFile, File, Form, HTTPException

from app.api.dependencies import get_course_repository
from app.database import CourseRepository
from app.schemas.documents import CourseDocument, DocumentType, IngestionResult, RetrievedChunk
from app.services.ingestion import ingest_document
from app.services.retrieval import search_course

router = APIRouter(prefix="/api/courses/{course_id}", tags=["documents"])


@router.post("/documents", response_model=IngestionResult)
async def upload_document(
    course_id: str,
    file: UploadFile = File(...),
    document_type: DocumentType = Form(DocumentType.other),
    repository: CourseRepository = Depends(get_course_repository),
):
    """Upload a course document, extract text, chunk, store, and index it."""
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in (".pdf", ".txt", ".md"):
        raise HTTPException(400, f"Unsupported file type: {suffix}")

    # Save upload to a temp file for processing
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        shutil.copyfileobj(file.file, tmp)
        tmp_path = tmp.name

    try:
        result = ingest_document(
            file_path=tmp_path,
            course_id=course_id,
            repository=repository,
            document_type=document_type,
            filename=file.filename or Path(tmp_path).name,
        )
    except ValueError as exc:
        # Extraction found no text — a scanned PDF, most likely.
        raise HTTPException(422, str(exc)) from exc
    finally:
        Path(tmp_path).unlink(missing_ok=True)

    return result


@router.get("/documents", response_model=list[CourseDocument])
async def list_documents(
    course_id: str,
    repository: CourseRepository = Depends(get_course_repository),
):
    """Every document indexed for a course."""
    return repository.list_documents(course_id)


@router.get("/search", response_model=list[RetrievedChunk])
async def search_course_context(
    course_id: str,
    q: str,
    top_k: int = 5,
    repository: CourseRepository = Depends(get_course_repository),
):
    """Retrieve the most relevant chunks for a query within a course."""
    if not q.strip():
        raise HTTPException(400, "Query cannot be empty")

    return search_course(
        query=q, course_id=course_id, repository=repository, top_k=top_k
    )
