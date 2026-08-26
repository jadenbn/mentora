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
from app.services.profile import DEFAULT_ACCURACY, difficulty_hint, get_profile
from app.services.question_service import (
    ContextRetrievalError,
    ContextRetrievalNotConfigured,
    DocumentNotFoundError,
    QuestionService,
)
from app.services.selection import pick_topic

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


def _level_word(difficulty: float) -> str:
    if difficulty < 0.4:
        return "introductory"
    if difficulty < 0.7:
        return "moderate"
    return "challenging"


@dataclass(frozen=True)
class _Ask:
    question_request: str
    required_skill_id: str | None
    target_difficulty: float


def _build_ask(session: Session, course_id: str, request: GenerateQuestionRequest) -> _Ask:
    """Decide what to ask the generator for, and how hard it should be.

    A typed question_request drives the topic; the engine only contributes a
    difficulty level from the student's overall accuracy. An empty one hands
    the topic choice to the engine too -- this is the whole of "practice next
    topic": a property of generation, not a separate button or endpoint.
    """
    typed = request.question_request.strip()
    if typed:
        profile = get_profile(session, course_id, request.student_id)
        difficulty = difficulty_hint(profile)
        return _Ask(
            question_request=f"{typed} (write at a {_level_word(difficulty)} "
            "difficulty for this student)",
            required_skill_id=None,
            target_difficulty=difficulty,
        )

    topic = pick_topic(session, course_id, request.student_id)
    if topic is None:
        # A fresh course with no topics yet: the model's own read of the
        # document seeds the first ones, nothing to require attribution to.
        return _Ask(
            question_request="Write a question grounded in this material.",
            required_skill_id=None,
            target_difficulty=DEFAULT_ACCURACY,
        )

    parts = [
        f"Write a {_level_word(topic.target_difficulty)} question on "
        f"{topic.skill_name}: {topic.skill_description}"
    ]
    if topic.question_forms:
        parts.append(
            "Questions on this topic typically take these shapes: "
            + "; ".join(topic.question_forms)
            + ". Vary the specifics rather than reusing a worked example."
        )
    return _Ask(
        question_request=" ".join(parts),
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
