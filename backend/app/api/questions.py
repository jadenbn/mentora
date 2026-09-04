"""Generate a persisted problem from one selected course document.

The one generation path. The engine is consulted here, implicitly: if the
student described what they want, their request drives the topic and the
engine only supplies a difficulty level from their overall accuracy so far.
If they left it blank, the engine also picks the topic -- there is no
separate "next problem" button or endpoint.
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from app.agents.workflow_errors import QuestionWorkflowError, QuestionWorkflowTimeout
from app.api.dependencies import get_course_repository, get_session
from app.config import (
    TutorSettings,
    missing_indexing_settings,
    missing_settings,
    question_full_context_max_chars,
)
from app.database import CourseRepository
from app.models.skill import Skill
from app.schemas.problems import (
    AttributedSkill,
    GenerateQuestionRequest,
    GeneratedProblemResponse,
)
from app.services import attribution
from app.engine import (
    PRIOR_ACCURACY,
    difficulty_bucket,
    get_profile,
    mark_served,
    pick_topic,
)
from app.services.question_service import (
    ContextRetrievalError,
    ContextRetrievalNotConfigured,
    DocumentNotFoundError,
    QuestionService,
)

router = APIRouter(prefix="/api/courses/{course_id}/questions", tags=["questions"])


def get_question_service(
    repository: CourseRepository = Depends(get_course_repository),
    session: Session = Depends(get_session),
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
            timeout_seconds=settings.request_timeout_seconds,
        ),
        retriever=Retriever(),
        full_context_max_chars=question_full_context_max_chars(),
        session=session,
    )


@dataclass(frozen=True)
class _Ask:
    #: What to write. The student's own words when they typed some, otherwise
    #: an instruction the engine authored. Whoever wrote it has the final say.
    question_request: str
    #: The level the engine believes suits this student, as one of the three
    #: words in accuracy.difficulty_bucket. Travels separately from the
    #: request so the model can tell a preference from an instruction: it
    #: applies only where the request does not state a difficulty itself.
    difficulty_word: str
    required_skill_id: str | None
    target_difficulty: float


def _build_ask(session: Session, course_id: str, request: GenerateQuestionRequest) -> _Ask:
    """Decide what to ask the generator for, and how hard it should be.

    Precedence, and it runs one way: **the question request wins.** A typed
    request is the student's own words, and the engine only offers a
    difficulty level beside them -- it never overrides what they asked for.
    An empty request means the student expressed no preference at all, so the
    engine authors the request itself and is relied on for both topic and
    difficulty. That second case is the whole of "practice next topic": a
    property of generation, not a separate button or endpoint.
    """
    typed = request.question_request.strip()
    if typed:
        # Their words decide the topic, so there is no per-topic estimate to
        # read; the course-wide one supplies a level instead. Passed beside
        # the request rather than appended to it -- appending made the
        # engine's preference read as part of the student's own sentence,
        # which is exactly the thing it must never outrank.
        difficulty = get_profile(session, course_id, request.student_id).accuracy
        return _Ask(
            question_request=typed,
            difficulty_word=difficulty_bucket(difficulty),
            required_skill_id=None,
            target_difficulty=difficulty,
        )

    topic = pick_topic(session, course_id, request.student_id)
    if topic is None:
        # A fresh course with no topics yet: the model's own read of the
        # document seeds the first ones, nothing to require attribution to.
        return _Ask(
            question_request="Write a question grounded in this material.",
            difficulty_word=difficulty_bucket(PRIOR_ACCURACY),
            required_skill_id=None,
            target_difficulty=PRIOR_ACCURACY,
        )

    parts = [f"Write a question on {topic.skill_name}: {topic.skill_description}"]
    if topic.question_forms:
        parts.append(
            "Questions on this topic typically take these shapes: "
            + "; ".join(topic.question_forms)
            + ". Vary the specifics rather than reusing a worked example."
        )
    return _Ask(
        question_request=" ".join(parts),
        difficulty_word=difficulty_bucket(topic.target_difficulty),
        required_skill_id=topic.skill_id,
        target_difficulty=topic.target_difficulty,
    )


@router.post("/generate", response_model=GeneratedProblemResponse)
async def generate_question(
    course_id: str,
    request: GenerateQuestionRequest,
    service: QuestionService = Depends(get_question_service),
    repository: CourseRepository = Depends(get_course_repository),
    session: Session = Depends(get_session),
) -> GeneratedProblemResponse:
    ask = _build_ask(session, course_id, request)

    try:
        problem = await service.generate(
            course_id=course_id,
            document_id=request.document_id,
            question_request=ask.question_request,
            difficulty_word=ask.difficulty_word,
            required_skill_id=ask.required_skill_id,
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

    # Recorded so /work can read back what this problem was asked to be
    # written at, rather than trusting the client to restate it at grading.
    repository.set_problem_difficulty(
        problem_id=problem.id, target_difficulty=ask.target_difficulty
    )
    if ask.required_skill_id is not None:
        # The topic has now been put in front of the student. Stamped here
        # rather than inside pick_topic so nothing is recorded for a
        # question that failed to generate.
        mark_served(session, course_id, request.student_id, ask.required_skill_id)

    skill_ids = attribution.get_problem_skills(session, problem.id)
    skills = (
        session.exec(select(Skill).where(Skill.id.in_(skill_ids))).all()
        if skill_ids
        else []
    )
    return GeneratedProblemResponse(
        problem=problem,
        skills=[
            AttributedSkill(id=s.id, name=s.name, difficulty_band=s.difficulty_band)
            for s in skills
        ],
    )
