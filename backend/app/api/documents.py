"""API routes for document upload and retrieval."""

from __future__ import annotations

import tempfile
import shutil
from pathlib import Path

from fastapi import APIRouter, UploadFile, File, Form, HTTPException

from app.schemas.documents import DocumentType, IngestionResult
from app.services.ingestion import ingest_document
from app.services.embeddings import query_similar

router = APIRouter(prefix="/api/courses/{course_id}", tags=["documents"])


@router.post("/documents", response_model=IngestionResult)
async def upload_document(
    course_id: str,
    file: UploadFile = File(...),
    document_type: DocumentType = Form(DocumentType.other),
):
    """Upload a course document, extract text, chunk, embed, and index it."""
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
            document_type=document_type,
        )
    finally:
        Path(tmp_path).unlink(missing_ok=True)

    return result


@router.get("/search")
async def search_course_context(
    course_id: str,
    q: str,
    top_k: int = 5,
):
    """Retrieve the most relevant chunks for a query within a course."""
    if not q.strip():
        raise HTTPException(400, "Query cannot be empty")

    results = query_similar(query=q, course_id=course_id, top_k=top_k)
    return {"course_id": course_id, "query": q, "results": results}
