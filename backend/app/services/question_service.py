"""Select full or semantically retrieved context, persist a problem, and
attribute it to the skill(s) it exercises."""

from __future__ import annotations

import logging
from time import perf_counter
from typing import Protocol
from uuid import uuid4

from sqlmodel import Session, select

from app.database import CourseRepository
from app.models.enums import SkillOrigin
from app.models.skill import Skill
from app.schemas.problems import GeneratedProblem, GroundingChunk, ProblemContext, QuestionPlan
from app.schemas.taxonomy import RawSkillEntry
from app.services.taxonomy import TaxonomyError, build_taxonomy, merge_generated

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
        """Persist the model's skill analysis and return the ids to attribute
        this problem to.

        Reuses the exact same build_taxonomy + merge_generated path every
        other skill source goes through: a returned skill matching an
        existing id updates (or, for a seed skill, is safely ignored); one
        with no match is inserted as newly generated. Either way, the id is
        valid to attribute to regardless of whether the merge actually wrote
        anything — merge_generated blocking a seed-id collision protects the
        seed skill's fields, it doesn't invalidate the id.
        """
        raw_dicts = [entry.model_dump() for entry in raw_skills]
        try:
            produced = build_taxonomy(course_id, raw_dicts, SkillOrigin.GENERATED)
            merge_generated(self.session, course_id, produced)
        except TaxonomyError:
            # A malformed or over-budget skill batch must never fail the
            # student's problem request. The taxonomy write is a side effect
            # of generation, not the thing that was asked for -- so log it and
            # attribute to the skill selection already chose.
            logger.exception("skill attribution failed for course %s", course_id)
            self.session.rollback()
            return [required_skill_id] if required_skill_id else []
        skill_ids = [skill.id for skill in produced]
        if required_skill_id and required_skill_id not in skill_ids:
            skill_ids.append(required_skill_id)
        return skill_ids
