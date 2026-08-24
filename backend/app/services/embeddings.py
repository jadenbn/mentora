"""Generate embeddings and store/retrieve from Pinecone."""

from __future__ import annotations

import os
from openai import OpenAI
from pinecone import Pinecone

from app.schemas.documents import ChunkMetadata

EMBEDDING_MODEL = "text-embedding-3-small"
EMBEDDING_DIMENSION = 1536

#: Pinecone caps a fetch at 100 ids, an upsert at 100 vectors, a delete at 1000.
_FETCH_BATCH = 100
_UPSERT_BATCH = 100
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


def document_vector_prefix(document_id: str) -> str:
    """Id prefix shared by a document's chunks.

    Vector ids are the `chunk_id` from `chunk_pages`, which is
    `chunk_{document_id}_{index:05d}`, so a document's vectors remain
    listable and deletable by prefix.
    """
    return f"chunk_{document_id}_"


def delete_document_vectors(document_id: str) -> int:
    """Delete every vector belonging to a document. Returns count deleted."""
    index = _get_index()
    prefix = document_vector_prefix(document_id)

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
    """Embed chunks and upsert into Pinecone. Returns count upserted.

    Metadata carries only what a search has to answer without a second
    round trip: the `course_id` it filters on, and the ids that address the
    row in SQLite. Chunk text is deliberately not stored here — SQLite owns it,
    so there is one copy to keep correct rather than two to keep in step.
    """
    if not chunks:
        return 0

    index = _get_index()
    texts = [c.text for c in chunks]
    embeddings = embed_texts(texts)

    vectors = []
    for chunk, embedding in zip(chunks, embeddings):
        vectors.append({
            "id": chunk.chunk_id,
            "values": embedding,
            "metadata": {
                "course_id": chunk.course_id,
                "document_id": chunk.document_id,
                "chunk_id": chunk.chunk_id,
            },
        })

    for i in range(0, len(vectors), _UPSERT_BATCH):
        index.upsert(vectors=vectors[i : i + _UPSERT_BATCH])

    return len(vectors)


def query_similar(
    query: str,
    course_id: str,
    top_k: int = 5,
) -> list[tuple[str, float]]:
    """Rank a course's chunks against a query.

    Returns `(chunk_id, score)` most-similar first. Text is not returned
    because this layer no longer holds any; `app/services/retrieval.py` joins
    these ids back to SQLite.
    """
    index = _get_index()
    query_embedding = embed_texts([query])[0]

    results = index.query(
        vector=query_embedding,
        top_k=top_k,
        filter={"course_id": {"$eq": course_id}},
        include_metadata=True,
    )

    return [
        (match["metadata"]["chunk_id"], match["score"])
        for match in results["matches"]
    ]
