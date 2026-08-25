"""Select full or semantically retrieved context and persist a problem."""

from __future__ import annotations

import logging
import asyncio
from time import perf_counter
from typing import Protocol
from uuid import uuid4

from app.database import CourseRepository
from app.schemas.problems import GeneratedProblem, GroundingChunk, ProblemContext, QuestionPlan

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
        self, *, chunks: list[GroundingChunk], question_request: str
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
    ) -> None:
        self.repository = repository
        self.workflow = workflow
        self.retriever = retriever
        self.full_context_max_chars = full_context_max_chars

    async def generate(
        self, *, course_id: str, document_id: str, question_request: str
    ) -> GeneratedProblem:
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
        logger.info(
            "question generated strategy=%s duration_ms=%d",
            strategy,
            round((perf_counter() - started) * 1000),
        )
        return generated
