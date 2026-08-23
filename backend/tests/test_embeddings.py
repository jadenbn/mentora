"""Embedding generation and Pinecone upsert/query.

Both providers are replaced with deterministic fakes, so these run offline.
"""

from __future__ import annotations

import pytest

from app.schemas.documents import ChunkMetadata, DocumentType
from app.services import embeddings as embeddings_module
from app.services.embeddings import (
    EMBEDDING_DIMENSION,
    EMBEDDING_MODEL,
    embed_texts,
    query_similar,
    upsert_chunks,
)
from tests.ingestion_helpers import deterministic_vector


def make_chunk(index: int = 0, page: int = 1, **overrides) -> ChunkMetadata:
    payload = {
        "course_id": "course_1",
        "document_id": "doc_1",
        "filename": "lecture.pdf",
        "page": page,
        "document_type": DocumentType.lecture,
        "text": f"chunk text {index}",
    }
    payload.update(overrides)
    return ChunkMetadata(**payload)


class TestProviderClients:
    def test_openai_client_requires_its_key(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)

        with pytest.raises(KeyError):
            embeddings_module._get_openai()

    def test_pinecone_index_requires_its_key(self, monkeypatch):
        monkeypatch.delenv("PINECONE_API_KEY", raising=False)

        with pytest.raises(KeyError):
            embeddings_module._get_index()

    def test_openai_client_is_cached_between_calls(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

        assert embeddings_module._get_openai() is embeddings_module._get_openai()


class TestEmbedTexts:
    def test_uses_the_configured_embedding_model(self, fake_openai):
        embed_texts(["hello"])

        assert fake_openai.calls[0]["model"] == EMBEDDING_MODEL

    def test_returns_one_vector_per_text_in_order(self, fake_openai):
        vectors = embed_texts(["alpha", "beta", "gamma"])

        assert len(vectors) == 3
        assert vectors[0] == deterministic_vector("alpha")
        assert vectors[2] == deterministic_vector("gamma")

    def test_vectors_match_the_declared_dimension(self, fake_openai):
        assert len(embed_texts(["alpha"])[0]) == EMBEDDING_DIMENSION

    def test_batches_all_texts_into_a_single_request(self, fake_openai):
        embed_texts(["a", "b", "c"])

        assert len(fake_openai.calls) == 1
        assert fake_openai.calls[0]["input"] == ["a", "b", "c"]


class TestUpsertChunks:
    def test_no_chunks_short_circuits_without_touching_pinecone(self, monkeypatch):
        """Guards the empty case before any client is constructed."""

        def explode():
            raise AssertionError("_get_index must not be called for zero chunks")

        monkeypatch.setattr(embeddings_module, "_get_index", explode)

        assert upsert_chunks([]) == 0

    def test_returns_the_number_of_vectors_written(self, fake_openai, fake_index):
        assert upsert_chunks([make_chunk(i) for i in range(5)]) == 5

    def test_embeds_the_chunk_text(self, fake_openai, fake_index):
        upsert_chunks([make_chunk(0, text="integration by parts")])

        assert fake_openai.embedded_texts == ["integration by parts"]

    def test_vector_id_combines_document_page_and_position(
        self, fake_openai, fake_index
    ):
        upsert_chunks([make_chunk(0, page=3), make_chunk(1, page=7)])

        assert fake_index.upserted_ids == ["doc_1_3_0", "doc_1_7_1"]

    def test_vector_ids_are_unique_within_a_call(self, fake_openai, fake_index):
        chunks = [make_chunk(i, page=1) for i in range(50)]

        upsert_chunks(chunks)

        assert len(set(fake_index.upserted_ids)) == 50

    def test_metadata_travels_with_each_vector(self, fake_openai, fake_index):
        upsert_chunks([make_chunk(0, page=2, text="body text")])

        metadata = fake_index.upsert_batches[0][0]["metadata"]
        assert metadata == {
            "course_id": "course_1",
            "document_id": "doc_1",
            "filename": "lecture.pdf",
            "page": 2,
            "document_type": "lecture",
            "text": "body text",
        }

    def test_document_type_is_stored_as_a_plain_string(self, fake_openai, fake_index):
        """DocumentType subclasses str, so `== "..."` and isinstance both pass
        for the raw enum. Only an exact type check catches an unconverted value
        reaching Pinecone's metadata."""
        upsert_chunks([make_chunk(0, document_type=DocumentType.practice_exam)])

        stored = fake_index.upsert_batches[0][0]["metadata"]["document_type"]
        assert stored == "practice_exam"
        assert type(stored) is str

    def test_chunk_text_is_searchable_in_metadata(self, fake_openai, fake_index):
        """Retrieval reads the text back out of metadata, so it must be stored."""
        upsert_chunks([make_chunk(0, text="the fundamental theorem")])

        assert (
            fake_index.upsert_batches[0][0]["metadata"]["text"]
            == "the fundamental theorem"
        )

    def test_vector_values_are_the_embeddings(self, fake_openai, fake_index):
        upsert_chunks([make_chunk(0, text="alpha")])

        assert fake_index.upsert_batches[0][0]["values"] == deterministic_vector("alpha")

    @pytest.mark.parametrize(
        ("count", "expected_batches"), [(1, 1), (100, 1), (101, 2), (250, 3)]
    )
    def test_upserts_are_split_into_batches_of_100(
        self, fake_openai, fake_index, count, expected_batches
    ):
        """Pinecone rejects oversized upserts, so batching is a hard requirement."""
        upsert_chunks([make_chunk(i) for i in range(count)])

        assert len(fake_index.upsert_batches) == expected_batches
        assert all(len(b) <= 100 for b in fake_index.upsert_batches)

    def test_every_chunk_survives_batching(self, fake_openai, fake_index):
        upsert_chunks([make_chunk(i) for i in range(250)])

        assert len(fake_index.upserted_ids) == 250
        assert len(set(fake_index.upserted_ids)) == 250


class TestQuerySimilar:
    def test_embeds_the_query_text(self, fake_openai, fake_index):
        query_similar(query="power rule", course_id="course_1")

        assert fake_openai.embedded_texts == ["power rule"]

    def test_searches_with_the_query_embedding(self, fake_openai, fake_index):
        query_similar(query="power rule", course_id="course_1")

        assert fake_index.queries[0]["vector"] == deterministic_vector("power rule")

    def test_scopes_results_to_one_course(self, fake_openai, fake_index):
        """Without this filter a student could retrieve another course's material."""
        query_similar(query="q", course_id="course_math_101")

        assert fake_index.queries[0]["filter"] == {
            "course_id": {"$eq": "course_math_101"}
        }

    def test_requests_metadata_because_results_are_built_from_it(
        self, fake_openai, fake_index
    ):
        query_similar(query="q", course_id="c")

        assert fake_index.queries[0]["include_metadata"] is True

    def test_defaults_to_five_results(self, fake_openai, fake_index):
        query_similar(query="q", course_id="c")

        assert fake_index.queries[0]["top_k"] == 5

    def test_top_k_is_passed_through(self, fake_openai, fake_index):
        query_similar(query="q", course_id="c", top_k=12)

        assert fake_index.queries[0]["top_k"] == 12

    def test_no_matches_yields_an_empty_list(self, fake_openai, fake_index):
        assert query_similar(query="q", course_id="c") == []

    def test_maps_matches_onto_the_retrieval_shape(self, fake_openai, fake_index):
        upsert_chunks([make_chunk(0, page=4, text="body text")])

        results = query_similar(query="q", course_id="course_1", top_k=1)

        assert results == [
            {
                "text": "body text",
                "filename": "lecture.pdf",
                "page": 4,
                "document_type": "lecture",
                "score": 0.9,
            }
        ]

    def test_returns_the_fields_the_tutor_grounds_on(self, fake_openai, fake_index):
        """tutor_context.py reads exactly these keys off each result."""
        upsert_chunks([make_chunk(0)])

        result = query_similar(query="q", course_id="course_1", top_k=1)[0]

        assert set(result) == {"text", "filename", "page", "document_type", "score"}
