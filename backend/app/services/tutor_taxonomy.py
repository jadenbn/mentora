"""Course-grounding fallback built from Ren's validated seed taxonomy."""

from __future__ import annotations

import json
import re

from sqlmodel import Session, select

from app.models.enums import SkillOrigin
from app.models.skill import Skill
from app.services.taxonomy import TaxonomyError, load_taxonomy


def build_seeded_taxonomy_fallback(
    session: Session,
    *,
    course_id: str,
    expected_skill_ids: list[str],
    limit: int,
) -> list[dict]:
    """Return expected skills and their direct prerequisites for seeded courses.

    The seed file is loaded first so a database row alone cannot opt an
    arbitrary course into fallback grounding. Pinecone still owns the primary
    retrieval path; this material is used only when that lookup succeeds with
    zero excerpts.
    """

    if (
        not expected_skill_ids
        or limit <= 0
        or re.fullmatch(r"[a-z0-9][a-z0-9_-]*", course_id) is None
    ):
        return []
    try:
        validated_seed = load_taxonomy(course_id)
    except (FileNotFoundError, json.JSONDecodeError, KeyError, TypeError, TaxonomyError):
        return []

    validated_ids = {skill.id for skill in validated_seed}
    requested_ids = [
        skill_id for skill_id in expected_skill_ids if skill_id in validated_ids
    ]
    if not requested_ids:
        return []

    rows = session.exec(
        select(Skill).where(
            Skill.course_id == course_id,
            Skill.origin == SkillOrigin.SEED,
        )
    ).all()
    by_id = {skill.id: skill for skill in rows if skill.id in validated_ids}

    ordered_ids: list[str] = []
    for skill_id in requested_ids:
        if skill_id in by_id and skill_id not in ordered_ids:
            ordered_ids.append(skill_id)
    for skill_id in requested_ids:
        skill = by_id.get(skill_id)
        if not skill:
            continue
        for prereq_id in skill.prereqs:
            if prereq_id in by_id and prereq_id not in ordered_ids:
                ordered_ids.append(prereq_id)

    filename = f"{course_id}-seeded-taxonomy"
    results: list[dict] = []
    requested_set = set(requested_ids)
    for skill_id in ordered_ids[:limit]:
        skill = by_id[skill_id]
        prerequisite_names = [
            by_id[prereq_id].name
            for prereq_id in skill.prereqs
            if prereq_id in by_id
        ]
        prerequisite_text = (
            ", ".join(prerequisite_names) if prerequisite_names else "None"
        )
        results.append(
            {
                "text": (
                    f"Skill: {skill.name} ({skill.id})\n"
                    f"Description: {skill.description}\n"
                    f"Direct prerequisites: {prerequisite_text}"
                ),
                "filename": filename,
                "page": 1,
                "document_type": "course_taxonomy",
                "score": 1.0 if skill_id in requested_set else 0.9,
            }
        )
    return results
