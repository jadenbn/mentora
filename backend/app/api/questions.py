"""Generate a persisted problem from one selected course document."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.agents.workflow_errors import QuestionWorkflowError, QuestionWorkflowTimeout
from app.api.dependencies import get_course_repository
from app.config import (
    TutorSettings,
    missing_indexing_settings,
    missing_settings,
    question_full_context_max_chars,
)
from app.database import CourseRepository
from app.schemas.problems import GenerateQuestionRequest, ProblemContext
from app.services.question_service import (
    ContextRetrievalError,
    ContextRetrievalNotConfigured,
    DocumentNotFoundError,
    QuestionService,
)

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
    from app.services.retrieval import search_document

    class Retriever:
        def search(self, **kwargs):
            missing_indexing = missing_indexing_settings()
            if missing_indexing:
                raise ContextRetrievalNotConfigured(missing_indexing)
            return search_document(repository=repository, **kwargs)

    settings = TutorSettings.from_environment()
    return QuestionService(
        repository=repository,
        workflow=GeminiQuestionWorkflow(
            api_key=settings.gemini_api_key,
            model=settings.gemini_model,
            thinking_level=settings.gemini_thinking_level,
            timeout_seconds=settings.request_timeout_seconds,
        ),
        retriever=Retriever(),
        full_context_max_chars=question_full_context_max_chars(),
    )


@router.post("/generate", response_model=ProblemContext)
async def generate_question(
    course_id: str,
    request: GenerateQuestionRequest,
    service: QuestionService = Depends(get_question_service),
) -> ProblemContext:
    try:
        return await service.generate(
            course_id=course_id,
            document_id=request.document_id,
            question_request=request.question_request,
        )
    except DocumentNotFoundError as exc:
        raise HTTPException(404, "Document was not found in this course") from exc
    except ContextRetrievalNotConfigured as exc:
        raise HTTPException(
            503,
            detail={
                "message": "Large-document retrieval is not configured",
                "missing_settings": exc.missing_settings,
            },
        ) from exc
    except ContextRetrievalError as exc:
        raise HTTPException(
            502,
            "Relevant textbook context could not be retrieved; retry after indexing",
        ) from exc
    except QuestionWorkflowTimeout as exc:
        raise HTTPException(504, "Question generation took too long") from exc
    except QuestionWorkflowError as exc:
        raise HTTPException(502, "Question generation is temporarily unavailable") from exc
