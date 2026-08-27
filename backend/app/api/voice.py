"""HTTP boundary for speech-to-text.

The same posture as the tutor boundary: audio is identified by its signature
rather than its declared type, and no provider or configuration detail is ever
echoed back.

Only WAV is accepted. MediaRecorder's container is browser-dependent — Safari
produces AAC in MP4, Chrome Opus in WebM — so the frontend re-encodes to one
format before uploading, which leaves exactly one signature to verify here and
one mime type for the provider. See frontend/lib/voice/wav.ts.

Nothing is persisted. The bytes live for the length of this request.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from app.agents.workflow_errors import (
    TranscriptionWorkflowError,
    TranscriptionWorkflowTimeout,
)
from app.config import TranscriptionSettings, missing_settings
from app.schemas.voice import TranscriptionResponse
from app.services.transcription_service import TranscriptionService

router = APIRouter(prefix="/api/voice", tags=["voice"])

#: 16 kHz mono 16-bit PCM runs at 32 kB/s, so this is a few minutes of speech
#: and roughly 2.7x the longest recording the interface will produce. Pinned
#: against that maximum in tests/test_voice_api.py; the browser side pins the
#: same pair in frontend/tests/wav.test.ts.
MAX_AUDIO_BYTES = 5 * 1024 * 1024

AUDIO_MIME_TYPE = "audio/wav"


def get_transcription_service() -> TranscriptionService:
    """Build the service, refusing early if the server is not configured.

    The provider adapter is imported here rather than at module scope so that
    an unconfigured server answers 503 instead of failing to import, and so
    this module stays importable without a provider SDK.
    """
    missing = missing_settings()
    if missing:
        raise HTTPException(
            status_code=503,
            detail={
                "message": "Voice input is not configured on this server",
                "missing_settings": missing,
            },
        )
    from app.agents.transcription_workflow import GeminiTranscriptionWorkflow

    settings = TranscriptionSettings.from_environment()
    return TranscriptionService(
        workflow=GeminiTranscriptionWorkflow(
            api_key=settings.gemini_api_key,
            model=settings.gemini_model,
            timeout_seconds=settings.request_timeout_seconds,
        )
    )


def _is_wav(data: bytes) -> bool:
    return len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WAVE"


async def _read_audio(upload: UploadFile) -> bytes:
    data = await upload.read(MAX_AUDIO_BYTES + 1)
    if not data:
        raise HTTPException(400, "audio cannot be empty")
    if len(data) > MAX_AUDIO_BYTES:
        raise HTTPException(413, "audio is too long")
    if not _is_wav(data):
        raise HTTPException(415, "audio must be WAV")
    declared = (upload.content_type or "").lower()
    if declared and declared != AUDIO_MIME_TYPE:
        raise HTTPException(415, "audio does not match its declared type")
    return data


@router.post("/transcribe", response_model=TranscriptionResponse)
async def transcribe(
    audio: Annotated[UploadFile, File()],
    service: TranscriptionService = Depends(get_transcription_service),
) -> TranscriptionResponse:
    data = await _read_audio(audio)
    try:
        transcript = await service.transcribe(
            audio=data, audio_mime_type=AUDIO_MIME_TYPE
        )
    except TranscriptionWorkflowTimeout as exc:
        raise HTTPException(504, "Transcribing took too long") from exc
    except TranscriptionWorkflowError as exc:
        raise HTTPException(502, "Voice input is temporarily unavailable") from exc

    if transcript is None:
        # The request was well formed; the recording simply had no words in it.
        raise HTTPException(422, "No speech was detected in the recording")
    return TranscriptionResponse(transcript=transcript)
