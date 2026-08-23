"""Shared fixtures for the course-ingestion suite."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.services import embeddings as embeddings_module
from tests.ingestion_helpers import FakeOpenAI, FakePineconeIndex, write_pdf


@pytest.fixture(autouse=True)
def reset_provider_singletons():
    """embeddings.py caches its clients in module globals; isolate every test."""
    embeddings_module._openai_client = None
    embeddings_module._pinecone_index = None
    yield
    embeddings_module._openai_client = None
    embeddings_module._pinecone_index = None


@pytest.fixture
def fake_openai(monkeypatch) -> FakeOpenAI:
    client = FakeOpenAI()
    monkeypatch.setattr(embeddings_module, "_get_openai", lambda: client)
    return client


@pytest.fixture
def fake_index(monkeypatch) -> FakePineconeIndex:
    index = FakePineconeIndex()
    monkeypatch.setattr(embeddings_module, "_get_index", lambda: index)
    return index


@pytest.fixture
def client() -> TestClient:
    from app.main import app

    return TestClient(app)


@pytest.fixture
def sample_pdf(tmp_path: Path) -> Path:
    return write_pdf(
        tmp_path / "lecture.pdf",
        ["Page one about limits.", "Page two about derivatives."],
    )
