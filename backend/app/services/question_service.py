"""Select full or semantically retrieved context, persist a problem, and
attribute it to the skill(s) it exercises."""

from __future__ import annotations

import logging
from time import perf_counter
from typing import Protocol
from uuid import uuid4

from sqlmodel import Session, select

from app.database import CourseRepository
from app.models.skill import Skill
from app.schemas.problems import GeneratedProblem, GroundingChunk, ProblemContext, QuestionPlan
from app.schemas.taxonomy import RawSkillEntry
from app.services import proposals

logger = logging.getLogger(__name__)
RETRIEVAL_TOP_K = 12


class DocumentNotFoundError(LookupError):
    pass


class ContextRetrievalError(RuntimeError):
    """A large document could not supply grounded semantic context."""


class ContextRetrievalNotConfigured(ContextRetrievalError):
    def __init__(self, missing_settings: list[str]) -> None:
        super().__init__("semantic retrieval is not configured")
        self.missing_settings = missing_settings


class QuestionWorkflow(Protocol):
    async def run(
        self,
        *,
        chunks: list[GroundingChunk],
        question_request: str,
        existing_skills: list[dict[str, str]] | None = None,
    ) -> QuestionPlan: ...


class QuestionRetriever(Protocol):
    def search(
        self,
        *,
        query: str,
        course_id: str,
        document_id: str,
        top_k: int,
    ) -> list[GroundingChunk]: ...


def serialized_context_chars(chunks: list[GroundingChunk]) -> int:
    return sum(len(chunk.text) + len(chunk.chunk_id) + 32 for chunk in chunks)


class QuestionService:
    def __init__(
        self,
        *,
        repository: CourseRepository,
        workflow: QuestionWorkflow,
        retriever: QuestionRetriever,
        full_context_max_chars: int,
        session: Session,
    ) -> None:
        self.repository = repository
        self.workflow = workflow
        self.retriever = retriever
        self.full_context_max_chars = full_context_max_chars
        self.session = session

    async def generate(
        self,
        *,
        course_id: str,
        document_id: str,
        question_request: str,
        required_skill_id: str | None = None,
    ) -> GeneratedProblem:
        """required_skill_id: a skill this problem must be attributed to
        regardless of what the model's own skill analysis returns — set by
        next_problem to the skill selection actually chose, so a generated
        question always counts toward the skill it was asked for even if the
        model's independent read of the material lands somewhere adjacent.
        The model's own skills are additive on top of it, not a replacement.
        """
        started = perf_counter()
        document = self.repository.get_document(course_id=course_id, document_id=document_id)
        if document is None:
            raise DocumentNotFoundError(document_id)
        chunks = self.repository.get_chunks(course_id=course_id, document_id=document_id)
        context_chars = serialized_context_chars(chunks)
        if not chunks:
            raise DocumentNotFoundError(document_id)

        strategy = "full"
        if context_chars <= self.full_context_max_chars:
            context = chunks
        else:
            strategy = "pinecone"
            try:
                context = self.retriever.search(
                    query=question_request,
                    course_id=course_id,
                    document_id=document_id,
                    top_k=RETRIEVAL_TOP_K,
                )
            except ContextRetrievalNotConfigured:
                raise
            except Exception:
                logger.exception("large-document context retrieval failed")
                raise ContextRetrievalError(document_id) from None
            if not context:
                raise ContextRetrievalError(document_id)

        logger.info(
            "question context strategy=%s source_chars=%d selected_chunks=%d",
            strategy,
            context_chars,
            len(context),
        )
        plan = await self.workflow.run(
            chunks=context,
            question_request=question_request,
            existing_skills=self._existing_skill_context(course_id),
        )
        problem = ProblemContext(
            id=f"problem_{uuid4().hex}",
            course_id=course_id,
            document_id=document_id,
            source="generated",
            prompt=plan.prompt,
        )
        generated = self.repository.create_problem(
            problem=problem,
            grounding_chunk_ids=plan.grounding_chunk_ids,
        )
        skill_ids = self._attribute_skills(course_id, plan.skills, required_skill_id)
        self.repository.set_problem_skills(problem_id=generated.id, skill_ids=skill_ids)
        logger.info(
            "question generated strategy=%s duration_ms=%d skills=%s",
            strategy,
            round((perf_counter() - started) * 1000),
            skill_ids,
        )
        return generated

    def _existing_skill_context(self, course_id: str) -> list[dict[str, str]]:
        skills = self.session.exec(select(Skill).where(Skill.course_id == course_id)).all()
        return [{"id": s.id, "name": s.name} for s in skills]

    def _attribute_skills(
        self,
        course_id: str,
        raw_skills: list[RawSkillEntry],
        required_skill_id: str | None,
    ) -> list[str]:
        """Which skills this problem counts toward.

        Only skills the course already has. The model's read of the material
        is useful, but it runs on the read path, and a generator that can
        write the taxonomy makes the taxonomy an append-only log of names it
        invented -- which selection then chases, because a never-attempted
        skill outranks a weak one. Anything the model names that the course
        doesn't have is counted as a proposal instead (services/proposals.py)
        and decided later, off this path.
        """
        existing = {
            s.id
            for s in self.session.exec(
                select(Skill).where(Skill.course_id == course_id)
            ).all()
        }
        skill_ids = proposals.resolve_to_existing(self.session, course_id, raw_skills)

        unknown = [e for e in raw_skills if e.id and proposals.normalize_slug(course_id, e.id) not in existing]
        if unknown:
            try:
                recorded = proposals.record_proposals(
                    self.session, course_id, raw_skills, existing
                )
                if recorded:
                    logger.info(
                        "recorded %d skill proposal(s) for %s: %s",
                        len(recorded), course_id, recorded,
                    )
            except Exception:
                # Counting a proposal is bookkeeping. It must never cost the
                # student the problem they asked for.
                logger.exception("recording skill proposals failed for %s", course_id)
                self.session.rollback()

        if required_skill_id and required_skill_id not in skill_ids:
            skill_ids.append(required_skill_id)
        return skill_ids
