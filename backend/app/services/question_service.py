"""Select full or semantically retrieved context, persist a problem, and
attribute it to the skill(s) it exercises."""

from __future__ import annotations

import asyncio
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
from app.services import attribution
from app.services.taxonomy import (
    TaxonomyError,
    append_skills,
    build_taxonomy,
    canonical_key,
    normalize_slug,
)

logger = logging.getLogger(__name__)
RETRIEVAL_TOP_K = 12

# How many topics one question may add to a course. The piggyback is how the
# taxonomy grows, but a single pathological response should not be able to
# mint four topics at once -- and a question genuinely covering more than one
# unheard-of topic is a question that is not grounded in the material.
MAX_NEW_TOPICS_PER_QUESTION = 1


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
        difficulty_word: str | None = None,
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
        difficulty_word: str | None = None,
        required_skill_id: str | None = None,
    ) -> GeneratedProblem:
        """difficulty_word: the level the engine believes suits this student,
        offered to the generator as a preference. It never overrides a
        difficulty the question_request states itself -- see
        api/questions.py::_build_ask for which of the two authored the
        request, and prompts/question_generation.py for the rule the model
        is given.

        required_skill_id: a topic this problem must be attributed to
        regardless of what the model's own reading returns -- set when a
        topic was picked for the student (services/selection.py) rather than
        named by them, so a generated question always counts toward the
        topic it was asked for even if the model's own read of the material
        lands somewhere adjacent. The model's own topics are additive on top
        of it, not a replacement.
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
                context = await asyncio.to_thread(
                    self.retriever.search,
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
            difficulty_word=difficulty_word,
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
        attribution.set_problem_skills(self.session, generated.id, skill_ids)
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
        """Which topics this problem counts toward -- the piggyback.

        Each topic the model names either matches an existing one (by
        normalized id, or by a name-similarity key when the model described
        it in different words) or is genuinely new, in which case it is
        appended to the course's skills file and inserted. This is the only
        place a course's topic list grows outside seeding, and it may add at
        most MAX_NEW_TOPICS_PER_QUESTION of them.

        Order matters downstream: the first id is the problem's primary
        skill, and the primary is the only one an attempt's outcome moves.
        When selection required a topic, that topic leads.
        """
        existing = self.session.exec(
            select(Skill).where(Skill.course_id == course_id)
        ).all()
        by_slug = {s.id: s for s in existing}
        by_key = {canonical_key(s.name): s for s in existing}

        skill_ids: list[str] = []
        to_create: list[RawSkillEntry] = []
        for entry in raw_skills:
            slug = normalize_slug(course_id, entry.id)
            matched = by_slug.get(slug) or by_key.get(canonical_key(entry.name))
            if matched is not None:
                skill_ids.append(matched.id)
            else:
                to_create.append(entry)

        if to_create:
            try:
                produced = build_taxonomy(
                    course_id,
                    [e.model_dump() for e in to_create],
                    SkillOrigin.GENERATED,
                )
                # Capped after validation, not before: truncating first would
                # let a malformed batch slip through by dropping the entry it
                # collided with.
                if len(produced) > MAX_NEW_TOPICS_PER_QUESTION:
                    logger.info(
                        "course %s: capping new topics at %d, not creating %s",
                        course_id,
                        MAX_NEW_TOPICS_PER_QUESTION,
                        [s.name for s in produced[MAX_NEW_TOPICS_PER_QUESTION:]],
                    )
                    produced = produced[:MAX_NEW_TOPICS_PER_QUESTION]
                added_ids = append_skills(self.session, course_id, produced)
                skill_ids.extend(added_ids)
            except TaxonomyError:
                # A malformed batch must never cost the student the problem
                # they asked for -- only the topic attribution it would add.
                logger.exception("skill identification failed for course %s", course_id)
                self.session.rollback()

        if required_skill_id:
            # Lead with the topic selection asked for: it is what the
            # question was written to exercise, so it is what the outcome
            # should count toward.
            skill_ids.insert(0, required_skill_id)
        return list(dict.fromkeys(skill_ids))
