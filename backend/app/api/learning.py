"""API routes for attempt ingestion, student mastery, and problem selection."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session

from app.api.dependencies import get_course_repository, get_session
from app.database import CourseRepository
from app.schemas.learning import (
    AttemptCreate,
    AttemptResult,
    GenerationSpec,
    NextProblemResponse,
    StudentModelResponse,
)
from app.services import selection, student_model_service
from app.services.question_service import (
    ContextRetrievalError,
    ContextRetrievalNotConfigured,
    DocumentNotFoundError,
    QuestionService,
)
from app.services.retrieval import search_course
from app.services.student_model_service import UnknownSkillError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/courses/{course_id}", tags=["learning"])

_RETRIEVAL_TOP_K = 12


@router.post("/attempts", response_model=AttemptResult)
def create_attempt(
    course_id: str,
    payload: AttemptCreate,
    session: Session = Depends(get_session),
    repository: CourseRepository = Depends(get_course_repository),
):
    """Record an attempt, update the involved skills' mastery, and return the deltas.

    When the attempt names a problem we generated, the skills it exercised come
    from problem_skills, not the client payload.
    """
    try:
        return student_model_service.record_attempt(
            session, course_id, payload, repository=repository
        )
    except UnknownSkillError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/student-model", response_model=StudentModelResponse)
def get_student_model(
    course_id: str,
    student_id: str,
    session: Session = Depends(get_session),
):
    """Return this student's current mastery per skill, decayed for time elapsed."""
    return student_model_service.get_student_model(session, course_id, student_id)


@router.get("/next-problem-spec", response_model=GenerationSpec)
def get_next_problem_spec(
    course_id: str,
    student_id: str,
    session: Session = Depends(get_session),
):
    """Return what the next problem should target, without generating it."""
    spec = selection.select_next(session, course_id, student_id)
    if spec is None:
        raise HTTPException(404, f"no unlocked skills available for course '{course_id}'")
    return spec


def _render_question_request(spec: GenerationSpec) -> str:
    """Render the spec's intent as a plain-language request for the generator.

    A preference, never permission to break grounding — QUESTION_INSTRUCTION in
    the prompt already enforces that. Kept to a sentence or two.
    """
    if spec.target_difficulty < 0.4:
        level = "introductory"
    elif spec.target_difficulty < 0.7:
        level = "moderate"
    else:
        level = "challenging"
    parts = [
        f"Write a {level} question on {spec.skill_name}: {spec.skill_description}"
    ]
    if spec.is_review:
        parts.append("This is a review of previously covered material.")
    if spec.target_misconception is not None:
        parts.append(
            f"Probe the common misconception: {spec.target_misconception.value}."
        )
    if spec.avoid_forms:
        parts.append("Avoid these question forms: " + "; ".join(spec.avoid_forms) + ".")
    return " ".join(parts)


def _resolve_target_document(
    *, spec: GenerationSpec, course_id: str, repository: CourseRepository
) -> str:
    """Pick which course document the next problem should be grounded in.

    Rank the course's chunks against the skill's retrieval query and take the
    top chunk's document. If retrieval is unconfigured or returns nothing, fall
    back to the most recently updated document so a keyless dev demo of a small
    course still works.
    """
    try:
        chunks = search_course(
            query=spec.retrieval_query,
            course_id=course_id,
            repository=repository,
            top_k=_RETRIEVAL_TOP_K,
        )
    except ContextRetrievalNotConfigured:
        chunks = []
    except Exception:
        logger.exception("course retrieval failed for %s", course_id)
        chunks = []

    if chunks:
        hydrated = repository.get_chunks_by_ids([chunks[0].chunk_id])
        meta = hydrated.get(chunks[0].chunk_id)
        if meta is not None:
            return meta.document_id

    documents = repository.list_documents(course_id)
    if not documents:
        raise HTTPException(
            409,
            f"course '{course_id}' has no indexed documents to ground a problem in",
        )
    return documents[0].document_id


def get_question_service_dep(
    repository: CourseRepository = Depends(get_course_repository),
) -> QuestionService:
    # Reuse the question API's own factory so both routes build the service the
    # same way (config gating, Gemini workflow, document retriever).
    from app.api.questions import get_question_service

    return get_question_service(repository=repository)


@router.post("/next-problem", response_model=NextProblemResponse)
async def next_problem(
    course_id: str,
    student_id: str,
    session: Session = Depends(get_session),
    repository: CourseRepository = Depends(get_course_repository),
    service: QuestionService = Depends(get_question_service_dep),
) -> NextProblemResponse:
    """Select a skill, ground a question in the course, and tag it with the skill.

    The one route that runs the whole loop: select -> ground -> generate -> tag.
    The returned problem carries a server-side problem_skills row, so the attempt
    the client posts back moves the skill selection actually chose.
    """
    spec = selection.select_next(session, course_id, student_id)
    if spec is None:
        raise HTTPException(404, f"no unlocked skills available for course '{course_id}'")

    document_id = _resolve_target_document(
        spec=spec, course_id=course_id, repository=repository
    )
    try:
        problem = await service.generate(
            course_id=course_id,
            document_id=document_id,
            question_request=_render_question_request(spec),
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
            502, "Relevant textbook context could not be retrieved"
        ) from exc

    repository.set_problem_skills(problem_id=problem.id, skill_ids=[spec.skill_id])
    return NextProblemResponse(problem=problem, spec=spec)
