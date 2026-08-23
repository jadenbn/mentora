"""Environment-backed configuration.

One required credential. Course retrieval is deferred, so Pinecone and OpenAI
are no longer needed to run the tutor.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

REQUIRED_SETTINGS = ("GEMINI_API_KEY",)


def missing_settings() -> list[str]:
    """Names of unset variables. Never their values."""
    return [name for name in REQUIRED_SETTINGS if not os.getenv(name)]


@dataclass(frozen=True)
class TutorSettings:
    gemini_model: str
    request_timeout_seconds: float

    @classmethod
    def from_environment(cls) -> "TutorSettings":
        return cls(
            gemini_model=os.getenv("GEMINI_MODEL", "gemini-3-flash"),
            request_timeout_seconds=float(os.getenv("TUTOR_REQUEST_TIMEOUT_SECONDS", "45")),
        )
