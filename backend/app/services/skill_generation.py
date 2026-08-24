"""Generate a course's skill taxonomy from its documents, additively.

Orchestrates the violet path of the pipeline: gather source text from a
course's ingested chunks, call the taxonomy workflow, build the result
through the same validator every taxonomy source uses, and merge it in
without disturbing anything a student has already touched.

A content-hash guard (CourseGenerationVersion) means calling this twice for
an unchanged document set is a no-op that never reaches the model — so it is
safe to call after every upload rather than only the first one.
"""

from __future__ import annotations

import hashlib
import logging
from typing import Protocol

from sqlmodel import Session, select

from app.database import CourseRepository
from app.models.course_generation_version import CourseGenerationVersion
from app.models.enums import SkillOrigin
from app.models.skill import Skill
from app.services.taxonomy import MergeReport, build_taxonomy, merge_generated

logger = logging.getLogger(__name__)


class TaxonomyWorkflow(Protocol):
    async def run(
        self,
        *,
        source_text: str,
        existing_skills: list[dict[str, str]] | None = None,
        emergent: bool = False,
    ) -> list[dict]: ...


def _course_signature(repository: CourseRepository, course_id: str) -> str:
    """A signature that changes iff the course's document set changes.

    Document ids are content-addressed (app.services.ingestion), so hashing
    the sorted set of ids already captures additions, removals, and content
    changes to an existing filename — no need to read chunk text here.
    """
    documents = repository.list_documents(course_id)
    ids = sorted(d.document_id for d in documents)
    return hashlib.sha256("\n".join(ids).encode("utf-8")).hexdigest()


def _gather_source_text(
    repository: CourseRepository, course_id: str, max_chars: int
) -> str:
    """Sample chunk text across every document in the course, char-capped.

    Round-robins across documents so one large file can't crowd out the
    others. Good enough for a course's worth of material in v1; a course
    whose combined text badly exceeds max_chars would want map-reduce
    summarization instead of sampling — noted as a scaling follow-up, not
    implemented here.
    """
    documents = repository.list_documents(course_id)
    if not documents:
        return ""

    per_document = [
        repository.get_chunks(course_id=course_id, document_id=doc.document_id)
        for doc in documents
    ]
    parts: list[str] = []
    total = 0
    row = 0
    while total < max_chars and any(row < len(chunks) for chunks in per_document):
        for chunks in per_document:
            if row >= len(chunks):
                continue
            text = chunks[row].text
            parts.append(text)
            total += len(text)
            if total >= max_chars:
                break
        row += 1
    return "\n\n".join(parts)[:max_chars]


async def generate_taxonomy_for_course(
    session: Session,
    course_id: str,
    repository: CourseRepository,
    workflow: TaxonomyWorkflow,
    max_source_chars: int,
) -> MergeReport | None:
    """Generate and additively merge a skill taxonomy for one course.

    Returns None when there was nothing to do: no ingested documents, or the
    document set is unchanged since the last generation for this course (no
    model call is made in that case). Otherwise returns the merge report.
    """
    signature = _course_signature(repository, course_id)
    version = session.get(CourseGenerationVersion, course_id)
    if version is not None and version.content_hash == signature:
        return None

    source_text = _gather_source_text(repository, course_id, max_source_chars)
    if not source_text:
        return None

    existing = session.exec(select(Skill).where(Skill.course_id == course_id)).all()
    existing_context = [{"id": s.id, "name": s.name} for s in existing]

    raw = await workflow.run(source_text=source_text, existing_skills=existing_context)
    produced = build_taxonomy(course_id, raw, SkillOrigin.GENERATED)
    report = merge_generated(session, course_id, produced)

    if version is None:
        session.add(CourseGenerationVersion(course_id=course_id, content_hash=signature))
    else:
        version.content_hash = signature
        session.add(version)
    session.commit()

    logger.info(
        "generated taxonomy for %s: +%d added, %d updated, %d blocked",
        course_id,
        len(report.added),
        len(report.updated),
        len(report.blocked_seed_collisions),
    )
    return report
