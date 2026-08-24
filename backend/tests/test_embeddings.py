from __future__ import annotations

from app.schemas.documents import ChunkMetadata, DocumentType
from app.services import embeddings


def chunk(index=0):
    return ChunkMetadata(
        chunk_id=f"chunk_doc_1_{index:05d}",
        course_id="course_1",
        document_id="doc_1",
        chunk_index=index,
        filename="book.pdf",
        page=3,
        document_type=DocumentType.lecture,
        text="The chain rule applies to nested functions.",
    )


class FakeIndex:
    def __init__(self):
        self.upserts = []
        self.queries = []

    def upsert(self, *, vectors):
        self.upserts.extend(vectors)

    def query(self, **kwargs):
        self.queries.append(kwargs)
        return {
            "matches": [
                {
                    "score": 0.91,
                    "metadata": {"chunk_id": "chunk_doc_1_00000"},
                }
            ]
        }


def test_upsert_keeps_text_out_of_pinecone_metadata(monkeypatch):
    index = FakeIndex()
    monkeypatch.setattr(embeddings, "_pinecone_index", index)
    monkeypatch.setattr(embeddings, "embed_texts", lambda texts: [[0.1, 0.2]])
    assert embeddings.upsert_chunks([chunk()]) == 1
    vector = index.upserts[0]
    assert vector["id"] == "chunk_doc_1_00000"
    assert vector["metadata"] == {
        "course_id": "course_1",
        "document_id": "doc_1",
        "chunk_id": "chunk_doc_1_00000",
    }
    assert "text" not in vector["metadata"]


def test_query_is_scoped_to_course_and_document(monkeypatch):
    index = FakeIndex()
    monkeypatch.setattr(embeddings, "_pinecone_index", index)
    monkeypatch.setattr(embeddings, "embed_texts", lambda texts: [[0.4, 0.5]])
    ranked = embeddings.query_similar(
        query="conceptual chain rule",
        course_id="course_1",
        document_id="doc_1",
        top_k=12,
    )
    assert ranked == [("chunk_doc_1_00000", 0.91)]
    assert index.queries[0]["filter"] == {
        "$and": [
            {"course_id": {"$eq": "course_1"}},
            {"document_id": {"$eq": "doc_1"}},
        ]
    }
    assert index.queries[0]["top_k"] == 12
