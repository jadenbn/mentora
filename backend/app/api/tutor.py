"""HTTP boundary for whiteboard tutor analysis.

Everything crossing it is hostile until proven otherwise: image bytes are
identified by their signature rather than their declared type, and no provider
or configuration detail is ever echoed back.
"""

from __future__ import annotations

import json
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import TypeAdapter, ValidationError

from app.agents.workflow_errors import TutorWorkflowError, TutorWorkflowTimeout
from app.config import TutorSettings, missing_settings
from app.schemas.tutor import NormalizedBounds, TutorMode, TutorResponse
from app.services.tutor_service import TutorService

router = APIRouter(prefix="/api/tutor", tags=["tutor"])

MAX_IMAGE_BYTES = 10 * 1024 * 1024

#: Signature -> mime type. The client's declared type is a claim, not evidence.
_SIGNATURES: tuple[tuple[bytes, str], ...] = (
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
)

_PRIOR_ANNOTATIONS = TypeAdapter(list[NormalizedBounds])


def get_tutor_service() -> TutorService:
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
                "message": "The tutor is not configured on this server",
                "missing_settings": missing,
            },
        )
    from app.agents.tutor_workflow import GeminiTutorWorkflow

    settings = TutorSettings.from_environment()
    return TutorService(
        workflow=GeminiTutorWorkflow(
            model=settings.gemini_model,
            timeout_seconds=settings.request_timeout_seconds,
        )
    )


def _sniff(data: bytes) -> str | None:
    for signature, mime_type in _SIGNATURES:
        if data.startswith(signature):
            return mime_type
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


async def _read_image(upload: UploadFile) -> tuple[bytes, str]:
    data = await upload.read(MAX_IMAGE_BYTES + 1)
    if not data:
        raise HTTPException(400, "canvas_image cannot be empty")
    if len(data) > MAX_IMAGE_BYTES:
        raise HTTPException(413, "canvas_image is too large")

    detected = _sniff(data)
    if detected is None:
        raise HTTPException(415, "canvas_image must be PNG, JPEG, or WebP")
    declared = (upload.content_type or "").lower()
    if declared and declared != detected:
        raise HTTPException(415, "canvas_image does not match its declared type")
    return data, detected


def _parse_prior_annotations(raw: str) -> list[NormalizedBounds]:
    try:
        return _PRIOR_ANNOTATIONS.validate_python(json.loads(raw))
    except (json.JSONDecodeError, ValidationError, TypeError) as exc:
        raise HTTPException(422, "prior_annotations must be a list of normalized bounds") from exc


@router.post("/analyze", response_model=TutorResponse)
async def analyze(
    room_id: Annotated[str, Form(min_length=1)],
    mode: Annotated[TutorMode, Form()],
    canvas_image: Annotated[UploadFile, File()],
    prior_annotations: Annotated[str, Form()] = "[]",
    service: TutorService = Depends(get_tutor_service),
) -> TutorResponse:
    image, mime_type = await _read_image(canvas_image)
    try:
        return await service.analyze(
            room_id=room_id,
            mode=mode,
            canvas_image=image,
            canvas_mime_type=mime_type,
            prior_annotations=_parse_prior_annotations(prior_annotations),
        )
    except TutorWorkflowTimeout as exc:
        raise HTTPException(504, "The tutor took too long to respond") from exc
    except TutorWorkflowError as exc:
        raise HTTPException(502, "The tutor is temporarily unavailable") from exc
