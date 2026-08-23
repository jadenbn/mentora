"""API tests for multipart validation, readiness, and safe error translation."""

from __future__ import annotations

import json
import os
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.agents.tutor_workflow import TutorRateLimitError, TutorWorkflowError
from app.api.tutor import get_tutor_service
from app.config import TutorSettings
from app.db import get_session
from app.main import app
from app.models.attempt import Attempt
from app.services.tutor_context import CourseContextUnavailable
from app.services.tutor_service import TutorService
from app.services.taxonomy import load_taxonomy
from tests.helpers import PNG_BYTES, retrieval_results, tutor_request, workflow_result


REQUIRED_ENV = {
    "GEMINI_API_KEY": "gemini-test-value",
    "OPENAI_API_KEY": "openai-test-value",
    "PINECONE_API_KEY": "pinecone-test-value",
    "PINECONE_INDEX_NAME": "test-index",
}


class FakeWorkflow:
    async def run(self, **_kwargs):
        return workflow_result()


def fake_service() -> TutorService:
    return TutorService(
        settings=TutorSettings(
            gemini_model="test-model",
            learning_metrics_webhook_url=None,
            learning_metrics_webhook_secret=None,
            request_timeout_seconds=2,
            retrieval_top_k=5,
        ),
        workflow=FakeWorkflow(),
        retriever=lambda **_kwargs: retrieval_results(),
    )


def post_tutor(
    client: TestClient,
    *,
    mode: str = "hint",
    image: bytes = PNG_BYTES,
    content_type: str = "image/png",
):
    return client.post(
        "/api/tutor/analyze",
        data={"payload": tutor_request(mode=mode).model_dump_json()},
        files={"canvas_image": ("canvas.png", image, content_type)},
    )


def test_health_lists_missing_names_without_values() -> None:
    with patch.dict(os.environ, {}, clear=True), TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    tutor_health = response.json()["services"]["tutor"]
    assert tutor_health["status"] == "not_ready"
    assert tutor_health["missing_settings"] == list(REQUIRED_ENV)
    assert tutor_health["model"] == "gemini-3.5-flash-lite"
    assert tutor_health["timeout_seconds"] == 8


def test_tutor_requires_all_provider_settings_without_exposing_values() -> None:
    app.dependency_overrides[get_tutor_service] = fake_service
    try:
        with patch.dict(
            os.environ,
            {"GEMINI_API_KEY": "super-secret-gemini-value"},
            clear=True,
        ), TestClient(app) as client:
            response = post_tutor(client)
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 503
    body = response.text
    assert "super-secret-gemini-value" not in body
    assert "OPENAI_API_KEY" in body
    assert "GEMINI_API_KEY" not in response.json()["detail"]["missing_settings"]


def test_tutor_accepts_valid_multipart_request() -> None:
    app.dependency_overrides[get_tutor_service] = fake_service
    try:
        with patch.dict(os.environ, REQUIRED_ENV, clear=True), TestClient(app) as client:
            response = post_tutor(client)
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "partial"
    assert [action["type"] for action in body["canvas_actions"]] == ["text", "circle"]
    assert body["grounding_references"][0]["filename"] == "lecture-3.pdf"


def test_tutor_api_uses_seeded_taxonomy_after_empty_retrieval() -> None:
    test_engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(test_engine)
    with Session(test_engine) as session:
        session.add_all(load_taxonomy("calc1"))
        session.commit()

    def learning_session():
        with Session(test_engine) as session:
            yield session

    service = TutorService(
        settings=fake_service().settings,
        workflow=FakeWorkflow(),
        retriever=lambda **_kwargs: [],
    )
    base_request = tutor_request()
    request = base_request.model_copy(
        update={
            "course_id": "calc1",
            "problem": base_request.problem.model_copy(
                update={"expected_skills": ["calc1.derivatives.chain-rule"]}
            ),
        }
    )
    app.dependency_overrides[get_tutor_service] = lambda: service
    app.dependency_overrides[get_session] = learning_session
    try:
        with patch.dict(os.environ, REQUIRED_ENV, clear=True), TestClient(app) as client:
            response = client.post(
                "/api/tutor/analyze",
                data={"payload": request.model_dump_json()},
                files={"canvas_image": ("canvas.png", PNG_BYTES, "image/png")},
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200, response.text
    assert response.json()["grounding_references"][0]["filename"] == (
        "calc1-seeded-taxonomy"
    )
    assert "built-in seeded course taxonomy" in response.json()["warnings"][0]


def test_tutor_modes_do_not_create_mastery_attempts() -> None:
    test_engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(test_engine)

    def learning_session():
        with Session(test_engine) as session:
            yield session

    workflow = FakeWorkflow()
    workflow.calls = []

    async def record_mode(**kwargs):
        workflow.calls.append(kwargs["mode"].value)
        return workflow_result()

    workflow.run = record_mode
    service = TutorService(
        settings=fake_service().settings,
        workflow=workflow,
        retriever=lambda **_kwargs: retrieval_results(),
    )
    app.dependency_overrides[get_tutor_service] = lambda: service
    app.dependency_overrides[get_session] = learning_session
    try:
        with patch.dict(os.environ, REQUIRED_ENV, clear=True), TestClient(app) as client:
            assert post_tutor(client, mode="hint").status_code == 200
            assert post_tutor(client, mode="stuck").status_code == 200
        with Session(test_engine) as session:
            assert session.exec(select(Attempt)).all() == []
        assert workflow.calls == ["hint", "stuck"]
    finally:
        app.dependency_overrides.clear()


def test_tutor_rejects_spoofed_or_unsupported_image() -> None:
    app.dependency_overrides[get_tutor_service] = fake_service
    try:
        with patch.dict(os.environ, REQUIRED_ENV, clear=True), TestClient(app) as client:
            response = post_tutor(client, image=b"not an image", content_type="image/png")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 415
    assert response.json()["detail"] == "canvas_image must be PNG, JPEG, or WebP"


def test_tutor_rejects_invalid_payload_without_echoing_input() -> None:
    app.dependency_overrides[get_tutor_service] = fake_service
    try:
        with patch.dict(os.environ, REQUIRED_ENV, clear=True), TestClient(app) as client:
            response = client.post(
                "/api/tutor/analyze",
                data={"payload": json.dumps({"instruction": "private student text"})},
                files={"canvas_image": ("canvas.png", PNG_BYTES, "image/png")},
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 422
    assert "private student text" not in response.text


def test_tutor_translates_retrieval_and_agent_failures() -> None:
    class FailingService:
        settings = fake_service().settings

        def __init__(self, error: Exception):
            self.error = error

        async def analyze(self, **_kwargs):
            raise self.error

    for error, expected_status, expected_detail in (
        (
            TutorRateLimitError("raw provider quota details"),
            429,
            "Tutor usage limit reached; try again shortly",
        ),
        (CourseContextUnavailable("raw pinecone error"), 502, "Required course context is temporarily unavailable"),
        (TutorWorkflowError("tutor workflow timed out"), 504, "Tutor analysis is temporarily unavailable"),
    ):
        app.dependency_overrides[get_tutor_service] = lambda error=error: FailingService(error)
        try:
            with patch.dict(os.environ, REQUIRED_ENV, clear=True), TestClient(app) as client:
                response = post_tutor(client)
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == expected_status
        assert response.json()["detail"] == expected_detail
        assert "raw" not in response.text
