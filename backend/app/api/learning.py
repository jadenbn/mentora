"""API routes for attempt ingestion, student mastery, and problem selection."""

from __future__ import annotations

import logging

from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlmodel import Session, select

from app.agents.workflow_errors import (
    QuestionWorkflowError,
    QuestionWorkflowTimeout,
    TutorWorkflowError,
    TutorWorkflowTimeout,
)
from app.api.dependencies import get_course_repository, get_session
from app.config import TutorSettings, missing_settings
from app.database import CourseRepository
from app.models.skill import Skill
from app.schemas.learning import (
    AttemptCreate,
    GenerationSpec,
    NextProblemResponse,
    SkillsOverviewResponse,
    StudentModelResponse,
    WorkResponse,
)
from app.services import selection, student_model_service
from app.services.question_service import (
    ContextRetrievalError,
    ContextRetrievalNotConfigured,
    DocumentNotFoundError,
    QuestionService,
)
from app.api.tutor import get_tutor_service, parse_prior_annotations, read_canvas_image
from app.schemas.tutor import TutorMode, WorkStatus
from app.services.retrieval import search_course
from app.services.tutor_service import TutorService
from app.services.skill_generation import bootstrap_first_skill
from app.services.student_model_service import UnknownSkillError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/courses/{course_id}", tags=["learning"])

_RETRIEVAL_TOP_K = 12


@router.get("/student-model", response_model=StudentModelResponse)
def get_student_model(
    course_id: str,
    student_id: str,
    session: Session = Depends(get_session),
):
    """Return this student's current mastery per skill, decayed for time elapsed."""
    return student_model_service.get_student_model(session, course_id, student_id)


@router.get("/skills-overview", response_model=SkillsOverviewResponse)
def get_skills_overview(
    course_id: str,
    student_id: str,
    session: Session = Depends(get_session),
):
    """Every skill in the course with this student's progress and unlock state.

    Read-only view for the dev/analytics dashboard: unlike /student-model this
    includes untouched skills at their seed mastery.
    """
    return student_model_service.get_skills_overview(session, course_id, student_id)


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
    if spec.question_forms:
        parts.append(
            "Questions on this skill typically take these shapes: "
            + "; ".join(spec.question_forms)
            + ". Vary the specifics rather than reusing a worked example."
        )
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
    session: Session = Depends(get_session),
) -> QuestionService:
    # Reuse the question API's own factory so both routes build the service the
    # same way (config gating, Gemini workflow, document retriever, skill
    # attribution). FastAPI resolves Depends(get_session) once per request, so
    # this is the same session next_problem's own session param gets.
    from app.api.questions import get_question_service

    return get_question_service(repository=repository, session=session)


def _course_has_no_skills(session: Session, course_id: str) -> bool:
    return session.exec(select(Skill).where(Skill.course_id == course_id)).first() is None


async def _bootstrap_course(
    session: Session, course_id: str, repository: CourseRepository
) -> None:
    """Give selection one skill to start from, for a course that has none.

    Best-effort and silent: if the taxonomy provider isn't configured, or the
    call fails, this simply leaves selection with nothing — the caller's
    existing 404 for "no unlocked skills" stands, it never becomes a 500.
    """
    if missing_settings():
        return
    from app.agents.taxonomy_workflow import GeminiTaxonomyWorkflow

    settings = TutorSettings.from_environment()
    workflow = GeminiTaxonomyWorkflow(
        api_key=settings.gemini_api_key,
        model=settings.gemini_model,
        timeout_seconds=settings.request_timeout_seconds,
    )
    try:
        await bootstrap_first_skill(session, course_id, repository, workflow)
    except Exception:
        logger.exception("cold-start skill bootstrap failed for course %s", course_id)


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
    The returned problem carries server-side problem_skills rows, so the
    attempt the client posts back moves the skill(s) it actually exercised —
    the one selection chose, plus whatever else the model's own read of the
    question identified (a composite problem can span more than one skill).

    A course with ingested documents but zero skills gets exactly one
    cold-start skill proposed here before selection runs again — the one gap
    piggybacking on question generation can't fill, since there is no prior
    skill for question generation to be grounded by. Every subsequent skill
    the course grows is expected to come from that piggybacking instead.
    """
    spec = selection.select_next(session, course_id, student_id)
    if spec is None and _course_has_no_skills(session, course_id):
        await _bootstrap_course(session, course_id, repository)
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
            required_skill_id=spec.skill_id,
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
    except QuestionWorkflowTimeout as exc:
        raise HTTPException(504, "Question generation took too long") from exc
    except QuestionWorkflowError as exc:
        raise HTTPException(502, "Question generation is temporarily unavailable") from exc

    # Skill attribution already happened inside service.generate(). Record the
    # difficulty selection asked for alongside it, so grading reads it back
    # server-side instead of trusting the client to restate it.
    repository.set_problem_difficulty(
        problem_id=problem.id, target_difficulty=spec.target_difficulty
    )
    return NextProblemResponse(problem=problem, spec=spec)


@router.post("/work", response_model=WorkResponse)
async def submit_work(
    course_id: str,
    student_id: str,
    session_id: Annotated[str, Form(min_length=1)],
    mode: Annotated[TutorMode, Form()],
    canvas_image: Annotated[UploadFile, File()],
    problem_id: Annotated[str, Form(min_length=1)],
    hints_used: Annotated[int, Form(ge=0)] = 0,
    prior_annotations: Annotated[str, Form()] = "[]",
    session: Session = Depends(get_session),
    repository: CourseRepository = Depends(get_course_repository),
    tutor: TutorService = Depends(get_tutor_service),
) -> WorkResponse:
    """Grade a canvas and record the attempt, in one round trip.

    The product path for finishing a problem. POST /attempts used to take
    `correct`, `partial`, `hints_used` and `difficulty` straight from the
    browser: the server chose which skill an attempt moved, but the client
    decided whether it went up or down, on an API with no authentication. A
    one-line curl could set any student's mastery to the ceiling.

    Here the tutor's own reading of the canvas decides the outcome, and the
    difficulty comes from what selection asked for at generation time. The
    client supplies the canvas and nothing that scores it.

    Only mode="mark" records. A hint request is not a graded attempt, and
    "uncertain" means the tutor never actually read the canvas -- there is
    nothing to feed the student model in either case.
    """
    grounded = repository.get_grounded_problem(course_id=course_id, problem_id=problem_id)
    if grounded is None:
        raise HTTPException(404, "Problem was not found in this course")

    image, mime_type = await read_canvas_image(canvas_image)
    try:
        response = await tutor.analyze(
            course_id=course_id,
            mode=mode,
            canvas_image=image,
            canvas_mime_type=mime_type,
            prior_annotations=parse_prior_annotations(prior_annotations),
            problem_context=grounded.problem,
        )
    except TutorWorkflowTimeout as exc:
        raise HTTPException(504, "The tutor took too long to respond") from exc
    except TutorWorkflowError as exc:
        raise HTTPException(502, "The tutor is temporarily unavailable") from exc

    attempt = None
    if mode == TutorMode.mark and response.status != WorkStatus.uncertain:
        skills = repository.get_problem_skills(problem_id)
        difficulty = repository.get_problem_difficulty(problem_id)
        if skills and difficulty is not None:
            try:
                attempt = student_model_service.record_attempt(
                    session,
                    course_id,
                    AttemptCreate(
                        student_id=student_id,
                        session_id=session_id,
                        problem_id=problem_id,
                        expected_skills=skills,
                        difficulty=difficulty,
                        correct=response.status == WorkStatus.correct,
                        partial=response.status == WorkStatus.partial,
                        hints_used=hints_used,
                    ),
                    repository=repository,
                )
            except UnknownSkillError:
                # The problem names a skill the taxonomy no longer has (a
                # re-seed removed it, say). The grading still stands; only the
                # mastery update is lost.
                logger.exception("could not record attempt for problem %s", problem_id)
        else:
            logger.info(
                "problem %s has no skills or no recorded difficulty; graded but not recorded",
                problem_id,
            )

    return WorkResponse(tutor=response, attempt=attempt)
