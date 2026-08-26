"""API routes for grading work and the dev dashboard's overview query.

There is no "what's next" or "what do I know" route on this API: topic
selection happens implicitly inside question generation (app.api.questions),
and per-topic accuracy is never shown to a student -- only to the dashboard.
"""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlmodel import Session

from app.agents.workflow_errors import TutorWorkflowError, TutorWorkflowTimeout
from app.api.dependencies import get_course_repository, get_session
from app.api.tutor import get_tutor_service, parse_prior_annotations, read_canvas_image
from app.database import CourseRepository
from app.schemas.learning import AttemptCreate, SkillsOverviewResponse, WorkResponse
from app.schemas.tutor import TutorMode, WorkStatus
from app.services import attribution, student_model_service
from app.services.student_model_service import UnknownSkillError
from app.services.tutor_service import TutorService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/courses/{course_id}", tags=["learning"])


@router.get("/skills-overview", response_model=SkillsOverviewResponse)
def get_skills_overview(
    course_id: str,
    student_id: str,
    session: Session = Depends(get_session),
):
    """Every topic in the course with this student's attempt history.

    Dev dashboard only -- there is no equivalent on the product surface.
    """
    return student_model_service.get_skills_overview(session, course_id, student_id)


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
    one-line curl could set any student's accuracy to the ceiling.

    Here the tutor's own reading of the canvas decides the outcome, and the
    difficulty comes from what generation asked for at question-creation
    time (app.api.questions). The client supplies the canvas and nothing
    that scores it.

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
        skills = attribution.get_problem_skills(session, problem_id)
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
                )
            except UnknownSkillError:
                # The problem names a skill the taxonomy no longer has (a
                # re-seed removed it, say). The grading still stands; only the
                # accuracy update is lost.
                logger.exception("could not record attempt for problem %s", problem_id)
        else:
            logger.info(
                "problem %s has no skills or no recorded difficulty; graded but not recorded",
                problem_id,
            )

    return WorkResponse(tutor=response, attempt=attempt)
