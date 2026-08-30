"""Gemini transcription adapter.

The only module allowed to import a provider SDK for voice, and the seam a
different speech-to-text service would replace. Everything here is about
surviving the provider rather than about tutoring: the upload/interaction round
trip, and translating failures into the two errors the API can map to status
codes.

Gemini is used because it is already the configured provider — voice adds no
credential, no dependency, and no second vendor to the deployment.

The model is a dedicated speech-to-text model rather than the general
multimodal one. It is asked for nothing but a transcript, so there is no
instruction to write, no response schema to constrain, and no thinking budget
to spend; `gemini-3.5-transcribe` accepts none of those. That also settles what
used to be a prompt-injection concern by construction: a transcription model
has no action to take, so audio saying "ignore your instructions" comes back as
those words rather than being obeyed.
"""

from __future__ import annotations

import asyncio
import io
import logging

from google.genai import types

from app.agents.gemini import create_client
from app.agents.workflow_errors import (
    TranscriptionWorkflowError,
    TranscriptionWorkflowTimeout,
)

logger = logging.getLogger(__name__)

#: The recording is uploaded before it can be transcribed, so it has to be
#: deleted afterwards. Deletion is bounded separately: it runs after the
#: request's own budget is spent, and a slow cleanup must not become a slow
#: request.
DELETE_TIMEOUT_SECONDS = 5


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

        There is no repair attempt, and now nothing to repair: the answer is
        one string rather than a structure a model can get wrong, so a second
        round trip would only re-roll the same call.
        """
        try:
            async with create_client(self.api_key).aio as client:
                transcript = await self._transcribe(
                    client=client, audio=audio, audio_mime_type=audio_mime_type
                )
        except (TimeoutError, asyncio.TimeoutError) as exc:
            logger.warning("transcription timed out after %ss", self.timeout_seconds)
            raise TranscriptionWorkflowTimeout("transcription took too long") from exc
        except Exception:
            # Logged in full here because the client is told nothing: a
            # provider message can quote credentials and prompt fragments.
            logger.exception("transcription request failed")
            raise TranscriptionWorkflowError("the transcription request failed") from None

        if not isinstance(transcript, str):
            logger.error("transcription returned no transcript text")
            raise TranscriptionWorkflowError("the transcription was unreadable")
        return transcript

    async def _transcribe(
        self, *, client, audio: bytes, audio_mime_type: str
    ) -> str | None:
        """Upload, transcribe, and delete the recording again.

        The uploaded file is temporary storage for one request. Cleanup sits
        outside the timeout scope on purpose: once that scope has converted a
        cancellation into a timeout, the delete can still be awaited, which is
        what lets an abandoned request take its recording with it.
        """
        uploaded = None
        try:
            async with asyncio.timeout(self.timeout_seconds):
                uploaded = await client.files.upload(
                    file=io.BytesIO(audio),
                    config=types.UploadFileConfig(mime_type=audio_mime_type),
                )
                interaction = await client.interactions.create(
                    model=self.model,
                    input=[
                        {
                            "type": "audio",
                            "uri": uploaded.uri,
                            "mime_type": uploaded.mime_type,
                        }
                    ],
                )
            return interaction.output_text
        finally:
            if uploaded is not None:
                await self._discard(client, uploaded)

    @staticmethod
    async def _discard(client, uploaded) -> None:
        """Delete the uploaded recording, best effort.

        A failed delete is not a failed transcription: the provider expires
        uploaded files on its own, so the worst case is a recording that lives
        slightly longer than the request that made it. Reporting that to the
        student instead of their answer would be the wrong trade.
        """
        name = getattr(uploaded, "name", None)
        if not name:
            return
        try:
            async with asyncio.timeout(DELETE_TIMEOUT_SECONDS):
                await client.files.delete(name=name)
        except Exception:
            logger.warning("could not delete the uploaded recording", exc_info=True)
