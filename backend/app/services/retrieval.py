"""Course retrieval: rank in Pinecone, read text from SQLite.

    query -> embedding -> chunk ids (+scores) -> SQLite rows -> RetrievedChunk

The two stores are joined here rather than inside either one, so the vector
layer never imports the database and the database never learns about
embeddings. Each stays testable without the other.
"""

from __future__ import annotations

from app.database import CourseRepository
from app.schemas.documents import RetrievedChunk
from app.services.embeddings import query_similar


def search_course(
    *,
    query: str,
    course_id: str,
    repository: CourseRepository,
    top_k: int = 5,
) -> list[RetrievedChunk]:
    """The most relevant chunks for a query within one course."""
    ranked = query_similar(query=query, course_id=course_id, top_k=top_k)
    if not ranked:
        return []

    chunks = repository.get_chunks_by_ids([chunk_id for chunk_id, _ in ranked])

    results: list[RetrievedChunk] = []
    for chunk_id, score in ranked:
        chunk = chunks.get(chunk_id)
        if chunk is None:
            # The vector outlived its row — a document deleted from SQLite
            # without its vectors, or an index seeded from another database.
            # Skipping keeps a stale pointer from failing the whole search.
            continue
        results.append(RetrievedChunk(**chunk.model_dump(), score=score))

    return results
