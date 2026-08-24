"""Select bounded source context and persist a generated, grounded problem."""

from __future__ import annotations

from typing import Protocol
from uuid import uuid4

from app.database import CourseRepository
from app.schemas.problems import GeneratedProblem, GroundingChunk, ProblemContext, QuestionPlan

MAX_QUESTION_CONTEXT_CHARS = 160_000


class DocumentNotFoundError(LookupError):
    pass


class QuestionWorkflow(Protocol):
    async def run(self, *, chunks: list[GroundingChunk]) -> QuestionPlan: ...


def _window(chunks: list[GroundingChunk], start: int, budget: int) -> list[GroundingChunk]:
    selected: list[GroundingChunk] = []
    used = 0
    for chunk in chunks[start:]:
        cost = len(chunk.text) + len(chunk.chunk_id) + 32
        if selected and used + cost > budget:
            break
        selected.append(chunk)
        used += cost
        if used >= budget:
            break
    return selected


def select_generation_context(
    chunks: list[GroundingChunk],
    budget: int = MAX_QUESTION_CONTEXT_CHARS,
) -> list[GroundingChunk]:
    """Keep all small documents; sample three contiguous windows from large ones."""
    if budget <= 0 or not chunks:
        return []
    total = sum(len(chunk.text) + len(chunk.chunk_id) + 32 for chunk in chunks)
    if total <= budget:
        return chunks

    per_window = max(1, budget // 3)
    average = max(1, total // len(chunks))
    estimated_window = max(1, per_window // average)
    middle_start = max(0, len(chunks) // 2 - estimated_window // 2)
    end_start = max(0, len(chunks) - estimated_window)

    selected_by_id: dict[str, GroundingChunk] = {}
    for start in (0, middle_start, end_start):
        for chunk in _window(chunks, start, per_window):
            selected_by_id[chunk.chunk_id] = chunk
    return [chunk for chunk in chunks if chunk.chunk_id in selected_by_id]


class QuestionService:
    def __init__(self, *, repository: CourseRepository, workflow: QuestionWorkflow) -> None:
        self.repository = repository
        self.workflow = workflow

    async def generate(self, *, course_id: str, document_id: str) -> GeneratedProblem:
        document = self.repository.get_document(course_id=course_id, document_id=document_id)
        if document is None:
            raise DocumentNotFoundError(document_id)
        chunks = self.repository.get_chunks(course_id=course_id, document_id=document_id)
        context = select_generation_context(chunks)
        if not context:
            raise DocumentNotFoundError(document_id)

        plan = await self.workflow.run(chunks=context)
        problem = ProblemContext(
            id=f"problem_{uuid4().hex}",
            course_id=course_id,
            document_id=document_id,
            source="generated",
            prompt=plan.prompt,
        )
        return self.repository.create_problem(
            problem=problem,
            grounding_chunk_ids=plan.grounding_chunk_ids,
        )
