"""Environment-backed configuration.

One required credential. Course retrieval is deferred, so Pinecone and OpenAI
are no longer needed to run the tutor.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
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
    raw = os.getenv("QUESTION_FULL_CONTEXT_MAX_CHARS") or "40000"
    value = int(raw)
    if value <= 0:
        raise ValueError("QUESTION_FULL_CONTEXT_MAX_CHARS must be positive")
    return value


def database_path() -> Path:
    configured = os.getenv("MENTORA_DB_PATH")
    if configured:
        return Path(configured).expanduser()
    return Path(__file__).resolve().parents[1] / "mentora.db"


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


@dataclass(frozen=True)
class TutorSettings:
    gemini_api_key: str
    gemini_model: str
    request_timeout_seconds: float

    @classmethod
    def from_environment(cls) -> "TutorSettings":
        return cls(
            gemini_api_key=os.getenv("GEMINI_API_KEY") or "",
            gemini_model=os.getenv("GEMINI_MODEL") or "gemini-3.5-flash-lite",
            request_timeout_seconds=float(os.getenv("TUTOR_REQUEST_TIMEOUT_SECONDS") or "45"),
        )
