"""Generate chunk embeddings and store/search them in Pinecone."""

from __future__ import annotations

import os
from typing import Any

from openai import OpenAI
from pinecone import Pinecone

from app.schemas.documents import ChunkMetadata

EMBEDDING_MODEL = "text-embedding-3-small"
EMBEDDING_DIMENSION = 1536
_UPSERT_BATCH = 100
_DELETE_BATCH = 1000
_FETCH_BATCH = 100
_EMBED_BATCH = 100

_openai_client: OpenAI | None = None
_pinecone_index: Any = None


def _get_openai() -> OpenAI:
    global _openai_client
    if _openai_client is None:
        _openai_client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    return _openai_client


def _get_index():
    global _pinecone_index
    if _pinecone_index is None:
        client = Pinecone(api_key=os.environ["PINECONE_API_KEY"])
        _pinecone_index = client.Index(os.environ["PINECONE_INDEX_NAME"])
    return _pinecone_index


def embed_texts(texts: list[str]) -> list[list[float]]:
    if not texts:
        return []
    embedded: list[list[float]] = []
    client = _get_openai()
    for start in range(0, len(texts), _EMBED_BATCH):
        response = client.embeddings.create(
            model=EMBEDDING_MODEL,
            input=texts[start : start + _EMBED_BATCH],
        )
        embedded.extend(item.embedding for item in response.data)
    return embedded


def document_vector_prefix(document_id: str) -> str:
    return f"chunk_{document_id}_"


def delete_document_vectors(document_id: str) -> int:
    """Remove all vectors for a deterministic document id."""
    index = _get_index()
    prefix = document_vector_prefix(document_id)
    ids: list[str] = []
    try:
        for page in index.list(prefix=prefix):
            ids.extend(page)
    except Exception:
        # Some Pinecone index types do not support prefix listing.
        index.delete(filter={"document_id": {"$eq": document_id}})
        return 0

    for start in range(0, len(ids), _DELETE_BATCH):
        index.delete(ids=ids[start : start + _DELETE_BATCH])
    return len(ids)


def delete_course_vectors(course_id: str) -> int:
    """Remove vectors for one course, including legacy vector-id formats."""
    index = _get_index()
    all_ids: list[str] = []
    for page in index.list():
        all_ids.extend(page)

    doomed: list[str] = []
    for start in range(0, len(all_ids), _FETCH_BATCH):
        fetched = index.fetch(ids=all_ids[start : start + _FETCH_BATCH])
        vectors = getattr(fetched, "vectors", None)
        if vectors is None:
            vectors = fetched["vectors"]
        for vector_id, vector in vectors.items():
            metadata = getattr(vector, "metadata", None)
            if metadata is None:
                metadata = vector["metadata"]
            if (metadata or {}).get("course_id") == course_id:
                doomed.append(vector_id)
    for start in range(0, len(doomed), _DELETE_BATCH):
        index.delete(ids=doomed[start : start + _DELETE_BATCH])
    return len(doomed)


def upsert_chunks(chunks: list[ChunkMetadata]) -> int:
    """Embed chunks; text stays in SQLite and is never copied to metadata."""
    if not chunks:
        return 0
    embeddings = embed_texts([chunk.text for chunk in chunks])
    vectors = [
        {
            "id": chunk.chunk_id,
            "values": embedding,
            "metadata": {
                "course_id": chunk.course_id,
                "document_id": chunk.document_id,
                "chunk_id": chunk.chunk_id,
            },
        }
        for chunk, embedding in zip(chunks, embeddings, strict=True)
    ]
    index = _get_index()
    for start in range(0, len(vectors), _UPSERT_BATCH):
        index.upsert(vectors=vectors[start : start + _UPSERT_BATCH])
    return len(vectors)


def query_similar(
    *, query: str, course_id: str, document_id: str | None = None, top_k: int = 12
) -> list[tuple[str, float]]:
    """Return ranked chunk ids scoped to a course, or one document within it.

    When ``document_id`` is None the query spans the whole course; otherwise
    it is narrowed to a single document.
    """
    vector = embed_texts([query])[0]
    clauses: list[dict[str, Any]] = [{"course_id": {"$eq": course_id}}]
    if document_id is not None:
        clauses.append({"document_id": {"$eq": document_id}})
    metadata_filter = clauses[0] if len(clauses) == 1 else {"$and": clauses}
    results = _get_index().query(
        vector=vector,
        top_k=top_k,
        filter=metadata_filter,
        include_metadata=True,
    )
    matches = getattr(results, "matches", None)
    if matches is None:
        matches = results["matches"]
    ranked: list[tuple[str, float]] = []
    for match in matches:
        metadata = getattr(match, "metadata", None)
        if metadata is None:
            metadata = match["metadata"]
        score = getattr(match, "score", None)
        if score is None:
            score = match["score"]
        chunk_id = (metadata or {}).get("chunk_id")
        if chunk_id:
            ranked.append((chunk_id, float(score)))
    return ranked
