"""Environment-backed configuration for Gemini, SQLite, and browser access."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

REQUIRED_SETTINGS = ("GEMINI_API_KEY",)
INDEXING_SETTINGS = ("OPENAI_API_KEY", "PINECONE_API_KEY", "PINECONE_INDEX_NAME")


def missing_settings() -> list[str]:
    """Names of unset variables. Never their values."""
    return [name for name in REQUIRED_SETTINGS if not os.getenv(name)]


def missing_indexing_settings() -> list[str]:
    """Names required to embed and retrieve course chunks."""
    return [name for name in INDEXING_SETTINGS if not os.getenv(name)]


def question_full_context_max_chars() -> int:
    """Serialized context size below which retrieval is unnecessary."""
    raw = os.getenv("QUESTION_FULL_CONTEXT_MAX_CHARS") or "40000"
    value = int(raw)
    if value <= 0:
        raise ValueError("QUESTION_FULL_CONTEXT_MAX_CHARS must be positive")
    return value


def cors_allow_origins() -> list[str]:
    """Browser origins permitted to call this API.

    Defaults to the local dev frontend. To reach the backend from another
    device on the network, set CORS_ALLOW_ORIGINS to a comma-separated list of
    origins, e.g. "http://192.168.1.20:3000". "*" allows any origin — only do
    that on a machine that is not reachable from the internet, since this API
    has no authentication and spends provider quota.
    """
    raw = os.getenv("CORS_ALLOW_ORIGINS") or "http://localhost:3000"
    return [origin.strip() for origin in raw.split(",") if origin.strip()]


def api_key() -> str | None:
    """Shared secret required on /api requests, or None to leave the API open.

    Set MENTORA_API_KEY on any deployment reachable by anything but you. This
    API spends provider quota on every generation and grading call, and it
    writes to the student model.

    Scope, stated plainly: a shared key authenticates the *caller*, not the
    student. `student_id` is still whatever the request says it is, so any
    holder of the key can read or write any student's model. Per-student
    identity needs a real user system and per-user tokens; this closes the
    open-to-the-internet hole, not that one.
    """
    return os.getenv("MENTORA_API_KEY") or None


def database_path() -> Path:
    configured = os.getenv("MENTORA_DB_PATH")
    if configured:
        return Path(configured).expanduser()
    return Path(__file__).resolve().parents[1] / "mentora.db"


@dataclass(frozen=True)
class TutorSettings:
    gemini_api_key: str = field(repr=False)
    gemini_model: str
    request_timeout_seconds: float

    @classmethod
    def from_environment(cls) -> "TutorSettings":
        return cls(
            gemini_api_key=os.getenv("GEMINI_API_KEY") or "",
            gemini_model=os.getenv("GEMINI_MODEL") or "gemini-3.5-flash-lite",
            request_timeout_seconds=float(os.getenv("TUTOR_REQUEST_TIMEOUT_SECONDS") or "45"),
        )
