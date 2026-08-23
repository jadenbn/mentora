"""Environment-backed configuration for backend integrations."""

from __future__ import annotations

import os
from dataclasses import dataclass


REQUIRED_TUTOR_SETTINGS = (
    "GEMINI_API_KEY",
    "OPENAI_API_KEY",
    "PINECONE_API_KEY",
    "PINECONE_INDEX_NAME",
)


def missing_tutor_settings() -> list[str]:
    """Return missing variable names without ever exposing their values."""

    return [name for name in REQUIRED_TUTOR_SETTINGS if not os.getenv(name)]


@dataclass(frozen=True)
class TutorSettings:
    gemini_model: str
    learning_metrics_webhook_url: str | None
    learning_metrics_webhook_secret: str | None
    request_timeout_seconds: float
    retrieval_top_k: int

    @classmethod
    def from_environment(cls) -> "TutorSettings":
        return cls(
            gemini_model=os.getenv("GEMINI_MODEL", "gemini-3.7-flash"),
            learning_metrics_webhook_url=os.getenv("LEARNING_METRICS_WEBHOOK_URL"),
            learning_metrics_webhook_secret=os.getenv(
                "LEARNING_METRICS_WEBHOOK_SECRET"
            ),
            request_timeout_seconds=float(
                os.getenv("TUTOR_REQUEST_TIMEOUT_SECONDS", "45")
            ),
            retrieval_top_k=int(os.getenv("TUTOR_RETRIEVAL_TOP_K", "5")),
        )
