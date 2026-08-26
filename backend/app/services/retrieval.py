"""Join Pinecone rankings to canonical SQLite chunk text."""

from __future__ import annotations

from app.database import CourseRepository
from app.schemas.problems import GroundingChunk
from app.services.embeddings import query_similar


def search_document(
    *,
    query: str,
    course_id: str,
    document_id: str,
    repository: CourseRepository,
    top_k: int = 12,
) -> list[GroundingChunk]:
    ranked = query_similar(
        query=query,
        course_id=course_id,
        document_id=document_id,
        top_k=top_k,
    )
    chunks = repository.get_chunks_by_ids([chunk_id for chunk_id, _ in ranked])
    return [
        GroundingChunk(chunk_id=chunk.chunk_id, page=chunk.page, text=chunk.text)
        for chunk_id, _score in ranked
        if (chunk := chunks.get(chunk_id)) is not None
        and chunk.course_id == course_id
        and chunk.document_id == document_id
    ]

