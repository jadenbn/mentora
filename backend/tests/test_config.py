"""Configuration surface.

One required key. The whole point of deferring retrieval is that the tutor
runs on a laptop with a single credential.
"""

from __future__ import annotations

from app.config import (
    INDEXING_SETTINGS,
    REQUIRED_SETTINGS,
    TutorSettings,
    cors_allow_origins,
    database_path,
    missing_indexing_settings,
    missing_settings,
    question_full_context_max_chars,
)


def test_only_a_gemini_key_is_required(monkeypatch):
    assert REQUIRED_SETTINGS == ("GEMINI_API_KEY",)
    assert INDEXING_SETTINGS == (
        "OPENAI_API_KEY",
        "PINECONE_API_KEY",
        "PINECONE_INDEX_NAME",
    )


def test_missing_settings_names_the_gap(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    assert missing_settings() == ["GEMINI_API_KEY"]


def test_a_configured_environment_reports_nothing_missing(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    assert missing_settings() == []


def test_missing_settings_reports_names_never_values(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "")
    assert missing_settings() == ["GEMINI_API_KEY"]


def test_settings_come_from_the_environment_with_usable_defaults(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "secret-test-key")
    monkeypatch.delenv("GEMINI_MODEL", raising=False)
    monkeypatch.delenv("TUTOR_REQUEST_TIMEOUT_SECONDS", raising=False)
    settings = TutorSettings.from_environment()
    assert settings.gemini_api_key == "secret-test-key"
    assert settings.gemini_model
    assert settings.request_timeout_seconds > 0


def test_indexing_readiness_and_context_threshold_are_separate(monkeypatch):
    for name in INDEXING_SETTINGS:
        monkeypatch.delenv(name, raising=False)
    assert missing_indexing_settings() == list(INDEXING_SETTINGS)
    monkeypatch.delenv("QUESTION_FULL_CONTEXT_MAX_CHARS", raising=False)
    assert question_full_context_max_chars() == 40_000
    monkeypatch.setenv("QUESTION_FULL_CONTEXT_MAX_CHARS", "1234")
    assert question_full_context_max_chars() == 1234


def test_an_empty_override_falls_back_rather_than_sending_a_blank_model(monkeypatch):
    # `KEY=` in a .env file sets the variable to "", which defeats getenv's
    # default and would send an empty model id to the provider.
    monkeypatch.setenv("GEMINI_MODEL", "")
    monkeypatch.setenv("TUTOR_REQUEST_TIMEOUT_SECONDS", "")
    settings = TutorSettings.from_environment()
    assert settings.gemini_model
    assert settings.request_timeout_seconds > 0


def test_settings_repr_never_discloses_the_key(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "super-secret-value")
    assert "super-secret-value" not in repr(TutorSettings.from_environment())


def test_the_model_is_overridable_without_a_code_change(monkeypatch):
    monkeypatch.setenv("GEMINI_MODEL", "gemini-3-flash-preview")
    assert TutorSettings.from_environment().gemini_model == "gemini-3-flash-preview"


def test_cors_defaults_to_the_local_frontend(monkeypatch):
    monkeypatch.delenv("CORS_ALLOW_ORIGINS", raising=False)
    assert cors_allow_origins() == ["http://localhost:3000"]


def test_cors_accepts_extra_origins_for_another_device(monkeypatch):
    # A tablet on the network sends the dev machine's address as its Origin.
    monkeypatch.setenv(
        "CORS_ALLOW_ORIGINS", "http://localhost:3000, http://192.168.1.20:3000"
    )
    assert cors_allow_origins() == [
        "http://localhost:3000",
        "http://192.168.1.20:3000",
    ]


def test_an_empty_cors_override_falls_back_rather_than_blocking_everything(monkeypatch):
    monkeypatch.setenv("CORS_ALLOW_ORIGINS", "")
    assert cors_allow_origins() == ["http://localhost:3000"]


def test_database_path_defaults_inside_the_backend(monkeypatch):
    monkeypatch.delenv("MENTORA_DB_PATH", raising=False)
    assert database_path().name == "mentora.db"
    assert database_path().parent.name == "backend"


def test_database_path_can_be_overridden(monkeypatch, tmp_path):
    configured = tmp_path / "course-context.db"
    monkeypatch.setenv("MENTORA_DB_PATH", str(configured))
    assert database_path() == configured


class TestApiKeyGate:
    """MENTORA_API_KEY closes the API to unauthenticated callers when set."""

    def test_the_api_is_open_when_no_key_is_configured(self, monkeypatch):
        from fastapi.testclient import TestClient

        from app.config import api_key
        from app.main import app

        monkeypatch.delenv("MENTORA_API_KEY", raising=False)
        assert api_key() is None
        with TestClient(app) as client:
            assert client.get("/health").status_code == 200
            assert client.get(
                "/api/courses/calc1/student-model", params={"student_id": "s"}
            ).status_code == 200

    def test_a_configured_key_is_required_on_api_routes(self, monkeypatch):
        from fastapi.testclient import TestClient

        from app.main import app

        monkeypatch.setenv("MENTORA_API_KEY", "secret")
        with TestClient(app) as client:
            unauthorized = client.get(
                "/api/courses/calc1/student-model", params={"student_id": "s"}
            )
            assert unauthorized.status_code == 401

            authorized = client.get(
                "/api/courses/calc1/student-model",
                params={"student_id": "s"},
                headers={"x-api-key": "secret"},
            )
            assert authorized.status_code == 200

            # A deployment must stay probeable without the key.
            assert client.get("/health").status_code == 200
