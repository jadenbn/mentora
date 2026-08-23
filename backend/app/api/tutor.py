"""HTTP boundary for multimodal whiteboard tutor analysis."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from pydantic import ValidationError

from app.agents.tutor_workflow import AdkTutorWorkflow, TutorWorkflowError
from app.config import TutorSettings, missing_tutor_settings
from app.schemas.tutor import TutorRequest, TutorResponse
from app.services.learning_events import publish_learning_events
from app.services.tutor_context import CourseContextUnavailable
from app.services.tutor_service import TutorService


router = APIRouter(prefix="/api/tutor", tags=["tutor"])

MAX_IMAGE_BYTES = 10 * 1024 * 1024
ALLOWED_IMAGE_TYPES = {"image/png", "image/jpeg", "image/webp"}


def get_tutor_service() -> TutorService:
    settings = TutorSettings.from_environment()
    return TutorService(
        settings=settings,
        workflow=AdkTutorWorkflow(
            model=settings.gemini_model,
            timeout_seconds=settings.request_timeout_seconds,
        ),
    )


def _sniff_image_mime(data: bytes) -> str | None:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


async def _read_image(upload: UploadFile, *, field_name: str) -> tuple[bytes, str]:
    data = await upload.read(MAX_IMAGE_BYTES + 1)
    if not data:
        raise HTTPException(status_code=400, detail=f"{field_name} cannot be empty")
    if len(data) > MAX_IMAGE_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"{field_name} exceeds the 10 MB limit",
        )
    detected_type = _sniff_image_mime(data)
    if detected_type not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(
            status_code=415,
            detail=f"{field_name} must be PNG, JPEG, or WebP",
        )
    declared_type = (upload.content_type or "").lower()
    if declared_type in ALLOWED_IMAGE_TYPES and declared_type != detected_type:
        raise HTTPException(
            status_code=415,
            detail=f"{field_name} content does not match its declared type",
        )
    return data, detected_type


@router.post("/analyze", response_model=TutorResponse)
async def analyze_tutor_request(
    background_tasks: BackgroundTasks,
    payload: Annotated[str, Form()],
    canvas_image: Annotated[UploadFile, File()],
    selection_image: Annotated[UploadFile | None, File()] = None,
    service: TutorService = Depends(get_tutor_service),
) -> TutorResponse:
    missing = missing_tutor_settings()
    if missing:
        raise HTTPException(
            status_code=503,
            detail={
                "message": "Tutor integrations are not fully configured",
                "missing_settings": missing,
            },
        )
    try:
        request = TutorRequest.model_validate_json(payload)
    except ValidationError as exc:
        raise HTTPException(
            status_code=422,
            detail=exc.errors(include_input=False),
        ) from exc

    canvas_bytes, canvas_mime_type = await _read_image(
        canvas_image, field_name="canvas_image"
    )
    selection_bytes: bytes | None = None
    selection_mime_type: str | None = None
    if selection_image is not None:
        selection_bytes, selection_mime_type = await _read_image(
            selection_image, field_name="selection_image"
        )

    try:
        result = await service.analyze(
            request=request,
            canvas_image=canvas_bytes,
            canvas_mime_type=canvas_mime_type,
            selection_image=selection_bytes,
            selection_mime_type=selection_mime_type,
        )
    except CourseContextUnavailable as exc:
        raise HTTPException(
            status_code=502,
            detail="Required course context is temporarily unavailable",
        ) from exc
    except TutorWorkflowError as exc:
        status_code = 504 if "timed out" in str(exc) else 502
        raise HTTPException(
            status_code=status_code,
            detail="Tutor analysis is temporarily unavailable",
        ) from exc

    settings = service.settings
    if result.webhook_envelope and settings.learning_metrics_webhook_url:
        background_tasks.add_task(
            publish_learning_events,
            result.webhook_envelope,
            webhook_url=settings.learning_metrics_webhook_url,
            webhook_secret=settings.learning_metrics_webhook_secret,
        )
    return result.response
