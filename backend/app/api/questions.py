"""Generate a persisted problem from one selected course document."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.agents.workflow_errors import QuestionWorkflowError, QuestionWorkflowTimeout
from app.api.dependencies import get_course_repository
from app.config import TutorSettings, missing_settings
from app.database import CourseRepository
from app.schemas.problems import GenerateQuestionRequest, ProblemContext
from app.services.question_service import DocumentNotFoundError, QuestionService

router = APIRouter(prefix="/api/courses/{course_id}/questions", tags=["questions"])


def get_question_service(
    repository: CourseRepository = Depends(get_course_repository),
) -> QuestionService:
    missing = missing_settings()
    if missing:
        raise HTTPException(
            503,
            detail={
                "message": "Question generation is not configured on this server",
                "missing_settings": missing,
            },
        )
    from app.agents.question_workflow import GeminiQuestionWorkflow

    settings = TutorSettings.from_environment()
    return QuestionService(
        repository=repository,
        workflow=GeminiQuestionWorkflow(
            model=settings.gemini_model,
            timeout_seconds=settings.request_timeout_seconds,
        ),
    )


@router.post("/generate", response_model=ProblemContext)
async def generate_question(
    course_id: str,
    request: GenerateQuestionRequest,
    service: QuestionService = Depends(get_question_service),
) -> ProblemContext:
    try:
        return await service.generate(course_id=course_id, document_id=request.document_id)
    except DocumentNotFoundError as exc:
        raise HTTPException(404, "Document was not found in this course") from exc
    except QuestionWorkflowTimeout as exc:
        raise HTTPException(504, "Question generation took too long") from exc
    except QuestionWorkflowError as exc:
        raise HTTPException(502, "Question generation is temporarily unavailable") from exc
