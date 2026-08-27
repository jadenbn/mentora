"""Gemini transcription adapter.

The only module allowed to import a provider SDK for voice, and the seam a
different speech-to-text service would replace. Everything here is about
surviving the provider rather than about tutoring: structured output, and
translating failures into the two errors the API can map to status codes.

Gemini is used because it is already the configured provider — voice adds no
credential, no dependency, and no second vendor to the deployment.
"""

from __future__ import annotations

import asyncio
import logging

from google.genai import types

from app.agents.gemini import create_client, response_object
from app.agents.workflow_errors import (
    TranscriptionWorkflowError,
    TranscriptionWorkflowTimeout,
)
from app.prompts.voice import TRANSCRIPTION_INSTRUCTION, TRANSCRIPTION_RESPONSE_SCHEMA

logger = logging.getLogger(__name__)


class GeminiTranscriptionWorkflow:
    """Turns one recording into the words that were spoken."""

    def __init__(
        self, *, api_key: str = "", model: str, timeout_seconds: float = 30
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.timeout_seconds = timeout_seconds

    async def run(self, *, audio: bytes, audio_mime_type: str) -> str:
        """The transcript, or "" when nothing intelligible was said.

        There is no repair attempt: unlike a tutor plan, the only structure
        here is one string, so a second round trip would be spent re-rolling
        the same call rather than fixing a schema mistake.
        """
        try:
            async with create_client(self.api_key).aio as client:
                message = types.Content(
                    role="user",
                    parts=[types.Part.from_bytes(data=audio, mime_type=audio_mime_type)],
                )
                async with asyncio.timeout(self.timeout_seconds):
                    response = await client.models.generate_content(
                        model=self.model,
                        contents=message,
                        config=self._generation_config(),
                    )
                transcript = response_object(response).get("transcript")
        except (TimeoutError, asyncio.TimeoutError) as exc:
            logger.warning("transcription timed out after %ss", self.timeout_seconds)
            raise TranscriptionWorkflowTimeout("transcription took too long") from exc
        except Exception:
            # Logged in full here because the client is told nothing: a
            # provider message can quote credentials and prompt fragments.
            logger.exception("transcription request failed")
            raise TranscriptionWorkflowError("the transcription request failed") from None

        if not isinstance(transcript, str):
            logger.error("transcription returned no transcript field")
            raise TranscriptionWorkflowError("the transcription was unreadable")
        return transcript

    def _generation_config(self) -> types.GenerateContentConfig:
        return types.GenerateContentConfig(
            system_instruction=TRANSCRIPTION_INSTRUCTION,
            response_mime_type="application/json",
            response_schema=TRANSCRIPTION_RESPONSE_SCHEMA,
            max_output_tokens=512,
            thinking_config=types.ThinkingConfig(
                thinking_level=types.ThinkingLevel.LOW
            ),
        )
