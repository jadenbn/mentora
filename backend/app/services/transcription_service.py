"""Orchestration for voice input.

One responsibility: put normalization between provider output and the wire, so
no caller ever has to wonder whether a transcript has been trimmed or capped.

The workflow port is declared here rather than in the provider adapter, so this
module — and everything that tests it — stays free of a provider SDK.
"""

from __future__ import annotations

from typing import Protocol

from app.schemas.voice import MAX_TRANSCRIPT_CHARS, normalize_transcript


class TranscriptionWorkflow(Protocol):
    async def run(self, *, audio: bytes, audio_mime_type: str) -> str: ...


class TranscriptionService:
    def __init__(self, *, workflow: TranscriptionWorkflow) -> None:
        self.workflow = workflow

    async def transcribe(self, *, audio: bytes, audio_mime_type: str) -> str | None:
        """The words that were spoken, or None when nothing was.

        An over-long transcript is truncated rather than refused: the student
        said something, and losing the whole utterance is a worse answer than
        losing its tail. A client that sends one back to the tutor is held to
        the same cap, where refusing *is* right — see api/tutor.py.
        """
        raw = await self.workflow.run(audio=audio, audio_mime_type=audio_mime_type)
        return normalize_transcript(raw[:MAX_TRANSCRIPT_CHARS])
