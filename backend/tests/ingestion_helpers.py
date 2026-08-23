"""Test doubles and fixtures data for the course-ingestion pipeline.

Named distinctly from tests/helpers.py so this suite can merge alongside the
tutor test suite without colliding.

Nothing here touches a real provider: OpenAI and Pinecone are replaced with
deterministic fakes so the whole pipeline is exercised offline.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace

import pymupdf

from app.services.embeddings import EMBEDDING_DIMENSION


def deterministic_vector(text: str, dimension: int = EMBEDDING_DIMENSION) -> list[float]:
    """A stable pseudo-embedding, so identical text always embeds identically."""
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    return [digest[i % len(digest)] / 255.0 for i in range(dimension)]


class FakeEmbeddingsAPI:
    def __init__(self, owner: "FakeOpenAI") -> None:
        self._owner = owner

    def create(self, model: str, input: list[str]):  # noqa: A002 - mirrors the SDK
        texts = list(input)
        self._owner.calls.append({"model": model, "input": texts})
        return SimpleNamespace(
            data=[SimpleNamespace(embedding=deterministic_vector(t)) for t in texts]
        )


class FakeOpenAI:
    """Stands in for openai.OpenAI, recording every embedding call."""

    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.embeddings = FakeEmbeddingsAPI(self)

    @property
    def embedded_texts(self) -> list[str]:
        return [text for call in self.calls for text in call["input"]]


class FakePineconeIndex:
    """Stands in for a Pinecone index, recording upserts and queries."""

    def __init__(self) -> None:
        self.upsert_batches: list[list[dict]] = []
        self.queries: list[dict] = []
        self.vectors: dict[str, dict] = {}

    def upsert(self, vectors: list[dict]) -> None:
        batch = list(vectors)
        self.upsert_batches.append(batch)
        for vector in batch:
            # Mirrors Pinecone: same id overwrites, different id accumulates.
            self.vectors[vector["id"]] = vector

    def query(self, vector, top_k, filter, include_metadata):  # noqa: A002
        self.queries.append(
            {
                "vector": vector,
                "top_k": top_k,
                "filter": filter,
                "include_metadata": include_metadata,
            }
        )
        matches = [
            {"metadata": dict(stored["metadata"]), "score": 0.9 - (index * 0.1)}
            for index, stored in enumerate(list(self.vectors.values())[:top_k])
        ]
        return {"matches": matches}

    @property
    def upserted_ids(self) -> list[str]:
        return [v["id"] for batch in self.upsert_batches for v in batch]


def write_pdf(path: Path, pages: list[str]) -> Path:
    """Build a real PDF so extraction runs through PyMuPDF, not a stub.

    An empty string produces a genuinely blank page, which is how the
    skip-blank-pages behaviour gets exercised.
    """
    document = pymupdf.open()
    for text in pages:
        page = document.new_page()
        if text:
            page.insert_text((72, 72), text.split("\n"), fontsize=11)
    document.save(str(path))
    document.close()
    return path
