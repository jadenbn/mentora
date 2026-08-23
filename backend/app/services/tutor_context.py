"""Course retrieval and compact context assembly for tutor requests."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Callable

from app.schemas.tutor import GroundingReference, TutorRequest
from app.services.embeddings import CourseIndexNotFound, query_similar


logger = logging.getLogger("uvicorn.error")


class CourseContextUnavailable(RuntimeError):
    """Raised when required course grounding cannot be retrieved."""


@dataclass(frozen=True)
class RetrievedCourseContext:
    excerpts: list[dict]
    references: list[GroundingReference]
    used_seeded_taxonomy_fallback: bool = False
    fallback_reason: str | None = None


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
    seeded_taxonomy_fallback: list[dict] | None = None,
) -> RetrievedCourseContext:
    query = build_retrieval_query(request)
    fallback_reason: str | None = None
    logger.info(
        "tutor.trace stage=retrieval_started request_id=%s course_id=%s top_k=%s",
        request.request_id,
        request.course_id,
        top_k,
    )
    try:
        results = await asyncio.to_thread(
            retriever,
            query=query,
            course_id=request.course_id,
            top_k=top_k,
        )
    except CourseIndexNotFound as exc:
        if not seeded_taxonomy_fallback:
            logger.exception(
                "tutor.trace stage=retrieval_index_missing request_id=%s "
                "course_id=%s seed_fallback_available=false",
                request.request_id,
                request.course_id,
            )
            raise CourseContextUnavailable("course context retrieval failed") from exc
        logger.warning(
            "tutor.trace stage=retrieval_index_missing request_id=%s "
            "course_id=%s seed_fallback_available=true",
            request.request_id,
            request.course_id,
        )
        results = []
        fallback_reason = "pinecone_index_missing"
    except Exception as exc:  # provider errors are translated at the API boundary
        logger.exception(
            "tutor.trace stage=retrieval_provider_error request_id=%s "
            "course_id=%s provider_exception=%s",
            request.request_id,
            request.course_id,
            type(exc).__name__,
        )
        raise CourseContextUnavailable("course context retrieval failed") from exc

    logger.info(
        "tutor.trace stage=retrieval_complete request_id=%s course_id=%s "
        "result_count=%s",
        request.request_id,
        request.course_id,
        len(results),
    )
    used_seeded_taxonomy_fallback = False
    if not results and seeded_taxonomy_fallback:
        results = seeded_taxonomy_fallback
        used_seeded_taxonomy_fallback = True
        fallback_reason = fallback_reason or "empty_results"
        logger.warning(
            "tutor.trace stage=retrieval_seed_fallback request_id=%s "
            "course_id=%s result_count=%s",
            request.request_id,
            request.course_id,
            len(results),
        )
    if not results:
        logger.error(
            "tutor.trace stage=retrieval_empty request_id=%s course_id=%s "
            "seed_fallback_available=%s",
            request.request_id,
            request.course_id,
            bool(seeded_taxonomy_fallback),
        )
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
    return RetrievedCourseContext(
        excerpts=excerpts,
        references=references,
        used_seeded_taxonomy_fallback=used_seeded_taxonomy_fallback,
        fallback_reason=fallback_reason,
    )
