"""Generate embeddings and store/retrieve from Pinecone."""

from __future__ import annotations

import os
from openai import OpenAI
from pinecone import Pinecone

from app.schemas.documents import ChunkMetadata

EMBEDDING_MODEL = "text-embedding-3-small"
EMBEDDING_DIMENSION = 1536

#: Pinecone caps a fetch at 100 ids and a delete at 1000.
_FETCH_BATCH = 100
_DELETE_BATCH = 1000

_openai_client: OpenAI | None = None
_pinecone_index = None


def _get_openai() -> OpenAI:
    global _openai_client
    if _openai_client is None:
        _openai_client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    return _openai_client


def _get_index():
    global _pinecone_index
    if _pinecone_index is None:
        pc = Pinecone(api_key=os.environ["PINECONE_API_KEY"])
        _pinecone_index = pc.Index(os.environ["PINECONE_INDEX_NAME"])
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

    for i in range(0, len(ids), _DELETE_BATCH):
        index.delete(ids=ids[i : i + _DELETE_BATCH])

    return len(ids)


def delete_course_vectors(course_id: str) -> int:
    """Delete every vector belonging to a course. Returns count deleted.

    Walks the index rather than deleting by prefix or by filter: `course_id`
    lives in metadata and not in the vector id, and delete-by-metadata-filter
    is unavailable on serverless indexes.

    This is the only way to reach chunks written by earlier versions of the
    pipeline, which minted a random `document_id` per upload and used a
    different vector-id format, so nothing can address them by document.
    """
    index = _get_index()

    all_ids: list[str] = []
    for page in index.list():
        all_ids.extend(page)

    doomed: list[str] = []
    for i in range(0, len(all_ids), _FETCH_BATCH):
        fetched = index.fetch(ids=all_ids[i : i + _FETCH_BATCH])
        vectors = getattr(fetched, "vectors", None)
        if vectors is None:
            vectors = fetched["vectors"]
        for key, vector in vectors.items():
            metadata = getattr(vector, "metadata", None)
            if metadata is None:
                metadata = vector["metadata"]
            if (metadata or {}).get("course_id") == course_id:
                doomed.append(key)

    for i in range(0, len(doomed), _DELETE_BATCH):
        index.delete(ids=doomed[i : i + _DELETE_BATCH])

    return len(doomed)


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

    results = index.query(
        vector=query_embedding,
        top_k=top_k,
        filter={"course_id": {"$eq": course_id}},
        include_metadata=True,
    )

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
