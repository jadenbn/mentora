"""Cold-start skill generation.

A course with ingested documents but no skills gives selection nothing to
pick, so nothing can be served and no other path can propose skills either.
bootstrap_first_skill breaks that deadlock with one cheap call, once per
course. Everything after it comes from skills proposed during question
generation (see services/proposals.py).
"""

from __future__ import annotations

import logging
from typing import Protocol

from sqlmodel import Session

from app.database import CourseRepository
from app.models.enums import SkillOrigin
from app.services.taxonomy import MergeReport, build_taxonomy, merge_generated

logger = logging.getLogger(__name__)

_BOOTSTRAP_CHUNK_LIMIT = 6
_BOOTSTRAP_MAX_CHARS = 6_000


class TaxonomyWorkflow(Protocol):
    async def run(
        self,
        *,
        source_text: str,
        existing_skills: list[dict[str, str]] | None = None,
        emergent: bool = False,
    ) -> list[dict]: ...


async def bootstrap_first_skill(
    session: Session,
    course_id: str,
    repository: CourseRepository,
    workflow: TaxonomyWorkflow,
) -> MergeReport | None:
    """Propose and persist exactly one skill for a course that has none yet.

    Deliberately cheap -- a handful of chunks from the most recently updated
    document, not a course-wide sample -- because the only job is giving
    selection one skill to start from. Returns None when the course has no
    ingested text to draw from; the caller's "nothing to select" 404 then
    stands unchanged.
    """
    documents = repository.list_documents(course_id)
    if not documents:
        return None
    chunks = repository.get_chunks(
        course_id=course_id, document_id=documents[0].document_id
    )
    if not chunks:
        return None

    excerpt = "\n\n".join(c.text for c in chunks[:_BOOTSTRAP_CHUNK_LIMIT])
    excerpt = excerpt[:_BOOTSTRAP_MAX_CHARS]

    raw = await workflow.run(source_text=excerpt, existing_skills=[], emergent=True)
    produced = build_taxonomy(course_id, raw, SkillOrigin.GENERATED)
    return merge_generated(session, course_id, produced)
