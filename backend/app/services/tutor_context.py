"""Course retrieval and compact context assembly for tutor requests."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Callable

from app.schemas.tutor import GroundingReference, TutorRequest
from app.services.embeddings import query_similar


class CourseContextUnavailable(RuntimeError):
    """Raised when required course grounding cannot be retrieved."""


@dataclass(frozen=True)
class RetrievedCourseContext:
    excerpts: list[dict]
    references: list[GroundingReference]


def build_retrieval_query(request: TutorRequest) -> str:
    """Build a focused query without treating prior AI content as student work."""

    parts = [request.problem.prompt_text, f"Tutor mode: {request.mode.value}"]
    if request.problem.topic:
        parts.append(f"Topic: {request.problem.topic}")
    if request.problem.expected_skills:
        parts.append("Expected skills: " + ", ".join(request.problem.expected_skills))
    student_text = [
        shape.text
        for shape in request.canvas.shapes
        if shape.owner.value == "student" and shape.text
    ]
    if student_text:
        parts.append("Student work: " + " | ".join(student_text[:20]))
    if request.transcript:
        parts.append("Student transcript: " + request.transcript)
    if request.instruction:
        parts.append("Student instruction: " + request.instruction)
    return "\n".join(parts)


async def retrieve_course_context(
    request: TutorRequest,
    *,
    top_k: int,
    retriever: Callable[..., list[dict]] = query_similar,
) -> RetrievedCourseContext:
    query = build_retrieval_query(request)
    try:
        results = await asyncio.to_thread(
            retriever,
            query=query,
            course_id=request.course_id,
            top_k=top_k,
        )
    except Exception as exc:  # provider errors are translated at the API boundary
        raise CourseContextUnavailable("course context retrieval failed") from exc

    if not results:
        raise CourseContextUnavailable("no course context was found for this request")

    excerpts: list[dict] = []
    references: list[GroundingReference] = []
    for result in results:
        excerpts.append(
            {
                "text": str(result.get("text", ""))[:8_000],
                "filename": str(result.get("filename", "unknown")),
                "page": int(result.get("page", 0)),
                "document_type": str(result.get("document_type", "other")),
            }
        )
        references.append(
            GroundingReference(
                filename=str(result.get("filename", "unknown")),
                page=max(0, int(result.get("page", 0))),
                score=float(result.get("score", 0)),
            )
        )
    return RetrievedCourseContext(excerpts=excerpts, references=references)
