"""Small shared helpers for direct Gemini provider calls."""

from __future__ import annotations

import json
from typing import Any

from google import genai
from google.genai import types
from pydantic import BaseModel


def create_client(api_key: str) -> genai.Client:
    """Create a client with bounded retries for transient provider failures."""
    return genai.Client(
        api_key=api_key,
        http_options=types.HttpOptions(
            retry_options=types.HttpRetryOptions(
                attempts=3,
                initial_delay=0.5,
                max_delay=4,
                exp_base=2,
                jitter=0.2,
                http_status_codes=[408, 500, 502, 503, 504],
            )
        ),
    )


def as_thinking_level(value: str) -> types.ThinkingLevel:
    """Translate the environment-friendly value to the provider enum."""
    return types.ThinkingLevel(value.upper())


def response_object(response: Any) -> dict[str, Any]:
    """Read Gemini's structured response across SDK parsed/text variants."""
    parsed = response.parsed
    if isinstance(parsed, BaseModel):
        return parsed.model_dump(mode="json")
    if isinstance(parsed, dict):
        return parsed

    text = response.text
    if not text:
        raise ValueError("provider returned no structured response")
    value = json.loads(text)
    if not isinstance(value, dict):
        raise ValueError("provider response was not an object")
    return value
