"""Generate embeddings and store/retrieve from Pinecone."""

from __future__ import annotations

import os
from openai import OpenAI
from pinecone import Pinecone
from pinecone.exceptions import NotFoundException

from app.schemas.documents import ChunkMetadata

EMBEDDING_MODEL = "text-embedding-3-small"
EMBEDDING_DIMENSION = 1536

_openai_client: OpenAI | None = None
_pinecone_index = None


class CourseIndexNotFound(RuntimeError):
    """The configured Pinecone index does not exist for this environment."""


def _get_openai() -> OpenAI:
    global _openai_client
    if _openai_client is None:
        _openai_client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    return _openai_client


def _get_index():
    global _pinecone_index
    if _pinecone_index is None:
        pc = Pinecone(api_key=os.environ["PINECONE_API_KEY"])
        try:
            _pinecone_index = pc.Index(os.environ["PINECONE_INDEX_NAME"])
        except NotFoundException as exc:
            raise CourseIndexNotFound("configured Pinecone index was not found") from exc
    return _pinecone_index


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Generate embeddings for a batch of texts."""
    client = _get_openai()
    response = client.embeddings.create(model=EMBEDDING_MODEL, input=texts)
    return [item.embedding for item in response.data]


def vector_id(document_id: str, chunk_index: int) -> str:
    """Stable id for a chunk. The `#` separator lets us list/delete by prefix."""
    return f"{document_id}#{chunk_index}"


def delete_document_vectors(document_id: str) -> int:
    """Delete every vector belonging to a document. Returns count deleted."""
    index = _get_index()
    prefix = f"{document_id}#"

    ids: list[str] = []
    try:
        for page in index.list(prefix=prefix):
            ids.extend(page)
    except Exception:
        # `list()` needs a serverless index; fall back to a metadata filter.
        index.delete(filter={"document_id": {"$eq": document_id}})
        return 0

    for i in range(0, len(ids), 1000):
        index.delete(ids=ids[i : i + 1000])

    return len(ids)


def upsert_chunks(chunks: list[ChunkMetadata]) -> int:
    """Embed chunks and upsert into Pinecone. Returns count upserted."""
    if not chunks:
        return 0

    index = _get_index()
    texts = [c.text for c in chunks]
    embeddings = embed_texts(texts)

    vectors = []
    for i, (chunk, embedding) in enumerate(zip(chunks, embeddings)):
        vectors.append({
            "id": vector_id(chunk.document_id, i),
            "values": embedding,
            "metadata": {
                "course_id": chunk.course_id,
                "document_id": chunk.document_id,
                "filename": chunk.filename,
                "page": chunk.page,
                "document_type": chunk.document_type.value,
                "text": chunk.text,
            },
        })

    # Upsert in batches of 100 (Pinecone limit)
    batch_size = 100
    for i in range(0, len(vectors), batch_size):
        batch = vectors[i : i + batch_size]
        index.upsert(vectors=batch)

    return len(vectors)


def query_similar(
    query: str,
    course_id: str,
    top_k: int = 5,
) -> list[dict]:
    """Embed a query and retrieve the most relevant chunks for a course."""
    index = _get_index()
    query_embedding = embed_texts([query])[0]

    try:
        results = index.query(
            vector=query_embedding,
            top_k=top_k,
            filter={"course_id": {"$eq": course_id}},
            include_metadata=True,
        )
    except NotFoundException as exc:
        raise CourseIndexNotFound("configured Pinecone index was not found") from exc

    return [
        {
            "text": match["metadata"]["text"],
            "filename": match["metadata"]["filename"],
            "page": match["metadata"]["page"],
            "document_type": match["metadata"]["document_type"],
            "score": match["score"],
        }
        for match in results["matches"]
    ]
