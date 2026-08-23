"""Configuration surface.

One required key. The whole point of deferring retrieval is that the tutor
runs on a laptop with a single credential.
"""

from __future__ import annotations

from app.config import REQUIRED_SETTINGS, TutorSettings, missing_settings


def test_only_a_gemini_key_is_required(monkeypatch):
    assert REQUIRED_SETTINGS == ("GEMINI_API_KEY",)


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
    monkeypatch.delenv("GEMINI_MODEL", raising=False)
    monkeypatch.delenv("TUTOR_REQUEST_TIMEOUT_SECONDS", raising=False)
    settings = TutorSettings.from_environment()
    assert settings.gemini_model
    assert settings.request_timeout_seconds > 0


def test_an_empty_override_falls_back_rather_than_sending_a_blank_model(monkeypatch):
    # `KEY=` in a .env file sets the variable to "", which defeats getenv's
    # default and would send an empty model id to the provider.
    monkeypatch.setenv("GEMINI_MODEL", "")
    monkeypatch.setenv("TUTOR_REQUEST_TIMEOUT_SECONDS", "")
    settings = TutorSettings.from_environment()
    assert settings.gemini_model
    assert settings.request_timeout_seconds > 0


def test_the_model_is_overridable_without_a_code_change(monkeypatch):
    monkeypatch.setenv("GEMINI_MODEL", "gemini-3-flash-preview")
    assert TutorSettings.from_environment().gemini_model == "gemini-3-flash-preview"
