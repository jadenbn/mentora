"""Record and review skills a model proposed but the course doesn't have.

Two halves, deliberately on different paths.

`record_proposals` runs during question generation. It is cheap, makes no
model call, and cannot change what any student is served -- it only counts
what the generator keeps asking for.

`review_proposals` is an explicit action. It decides which proposals are the
same as an existing skill under a different name (merge) and which are a real
gap in the taxonomy (promote). That is where a proposal can finally become a
Skill, and it is the only place a course's skill count grows outside seeding
and cold-start bootstrap.

The split is the point. Before it, every /next-problem could write skills, so
the taxonomy grew without bound with near-duplicates -- and since selection
rewards never-attempted skills, it chased its own output.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlmodel import Session, select

from app.models.enums import SkillOrigin
from app.models.skill import Skill
from app.models.skill_proposal import ProposalStatus, SkillProposal
from app.schemas.taxonomy import RawSkillEntry
from app.services.taxonomy import (
    TaxonomyError,
    build_taxonomy,
    merge_generated,
    normalize_slug,
)

logger = logging.getLogger(__name__)

# How many distinct problems must propose a skill before it is worth promoting.
# One model inventing a name once is noise.
PROMOTION_MIN_OBSERVATIONS = 3

# Cosine similarity above which a proposal is judged to be an existing skill
# wearing a different name. Tuned to merge "the chain rule" into "chain rule"
# while leaving "chain rule" and "product rule" apart.
MERGE_SIMILARITY = 0.82


@dataclass
class ReviewReport:
    promoted: list[str] = field(default_factory=list)
    merged: dict[str, str] = field(default_factory=dict)  # proposal slug -> skill id
    still_pending: list[str] = field(default_factory=list)
    skipped_semantic_check: bool = False


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _descriptive_text(name: str, description: str, keywords: list[str]) -> str:
    """What gets embedded when judging whether two skills are the same thing."""
    return " ".join([name, description, *keywords]).strip()


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


def record_proposals(
    session: Session,
    course_id: str,
    raw_skills: list[RawSkillEntry],
    existing_skill_ids: set[str],
) -> list[str]:
    """Count every proposed skill the course doesn't already have.

    Returns the slugs recorded. Never writes a Skill: a proposal is not a
    skill, and nothing a generator says on the read path may change what a
    student is served.
    """
    recorded: list[str] = []
    for entry in raw_skills:
        slug = normalize_slug(course_id, entry.id)
        if slug in existing_skill_ids:
            continue

        proposal = session.exec(
            select(SkillProposal).where(
                SkillProposal.course_id == course_id, SkillProposal.slug == slug
            )
        ).first()

        if proposal is None:
            session.add(
                SkillProposal(
                    course_id=course_id,
                    slug=slug,
                    name=entry.name,
                    description=entry.description,
                    difficulty_band=entry.difficulty_band,
                    prereqs=[normalize_slug(course_id, p) for p in entry.prereqs],
                    keywords=list(entry.keywords),
                    question_forms=list(entry.question_forms),
                )
            )
        elif proposal.status == ProposalStatus.PENDING:
            proposal.observations += 1
            proposal.last_seen = _utcnow()
            session.add(proposal)
        else:
            # Already decided. Don't reopen it, but do note it's still wanted.
            proposal.last_seen = _utcnow()
            session.add(proposal)
            continue

        recorded.append(slug)

    session.commit()
    return recorded


def resolve_to_existing(
    session: Session, course_id: str, raw_skills: list[RawSkillEntry]
) -> list[str]:
    """The subset of proposed skills that already exist in this course.

    These are the only model-proposed ids a problem may be attributed to.
    """
    existing = {
        s.id
        for s in session.exec(select(Skill).where(Skill.course_id == course_id)).all()
    }
    resolved = []
    for entry in raw_skills:
        slug = normalize_slug(course_id, entry.id)
        if slug in existing:
            resolved.append(slug)
        else:
            # A proposal previously judged to BE an existing skill still
            # attributes to that skill -- the generator's name for it was
            # just not the one the taxonomy uses.
            merged = session.exec(
                select(SkillProposal).where(
                    SkillProposal.course_id == course_id,
                    SkillProposal.slug == slug,
                    SkillProposal.status == ProposalStatus.MERGED,
                )
            ).first()
            if merged is not None and merged.resolved_skill_id in existing:
                resolved.append(merged.resolved_skill_id)
    return list(dict.fromkeys(resolved))


def review_proposals(
    session: Session,
    course_id: str,
    *,
    embed=None,
    min_observations: int = PROMOTION_MIN_OBSERVATIONS,
) -> ReviewReport:
    """Decide which pending proposals become skills and which are duplicates.

    `embed` takes a list of texts and returns a vector per text. When it is
    None -- no embedding provider configured -- the semantic merge step is
    skipped and proposals promote on observation count alone. That is the
    honest degraded mode: it grows the taxonomy more readily rather than
    silently pretending to deduplicate.
    """
    report = ReviewReport()

    pending = session.exec(
        select(SkillProposal).where(
            SkillProposal.course_id == course_id,
            SkillProposal.status == ProposalStatus.PENDING,
        )
    ).all()
    if not pending:
        return report

    ready = [p for p in pending if p.observations >= min_observations]
    report.still_pending = [p.slug for p in pending if p.observations < min_observations]
    if not ready:
        return report

    skills = session.exec(select(Skill).where(Skill.course_id == course_id)).all()

    to_promote = list(ready)
    if embed is not None and skills:
        try:
            to_promote = _merge_duplicates(session, ready, list(skills), embed, report)
        except Exception:
            logger.exception(
                "semantic duplicate check failed for %s; promoting on count alone",
                course_id,
            )
            report.skipped_semantic_check = True
    elif embed is None:
        report.skipped_semantic_check = True

    for proposal in to_promote:
        if _promote(session, course_id, proposal):
            report.promoted.append(proposal.slug)
        else:
            report.still_pending.append(proposal.slug)

    session.commit()
    return report


def _merge_duplicates(
    session: Session,
    ready: list[SkillProposal],
    skills: list[Skill],
    embed,
    report: ReviewReport,
) -> list[SkillProposal]:
    """Fold proposals that are an existing skill under another name.

    Returns the proposals that survived as genuinely new.
    """
    skill_texts = [_descriptive_text(s.name, s.description, s.keywords) for s in skills]
    proposal_texts = [
        _descriptive_text(p.name, p.description, p.keywords) for p in ready
    ]
    vectors = embed(skill_texts + proposal_texts)
    skill_vectors = vectors[: len(skills)]
    proposal_vectors = vectors[len(skills) :]

    survivors: list[SkillProposal] = []
    for proposal, vector in zip(ready, proposal_vectors):
        best_skill, best_score = None, 0.0
        for skill, skill_vector in zip(skills, skill_vectors):
            score = cosine(vector, skill_vector)
            if score > best_score:
                best_skill, best_score = skill, score

        if best_skill is not None and best_score >= MERGE_SIMILARITY:
            proposal.status = ProposalStatus.MERGED
            proposal.resolved_skill_id = best_skill.id
            session.add(proposal)
            report.merged[proposal.slug] = best_skill.id
            logger.info(
                "proposal %s merged into %s (similarity %.3f)",
                proposal.slug,
                best_skill.id,
                best_score,
            )
        else:
            survivors.append(proposal)
    return survivors


def _promote(session: Session, course_id: str, proposal: SkillProposal) -> bool:
    """Turn one proposal into a real Skill. False if it wouldn't validate."""
    raw = {
        "id": proposal.slug,
        "name": proposal.name,
        "description": proposal.description,
        "difficulty_band": proposal.difficulty_band,
        # A proposal's prereqs may name other proposals that were never
        # promoted. Keep only edges into the taxonomy as it actually is.
        "prereqs": [
            p
            for p in proposal.prereqs
            if session.get(Skill, p) is not None
        ],
        "keywords": proposal.keywords,
        "question_forms": proposal.question_forms,
    }
    try:
        produced = build_taxonomy(course_id, [raw], SkillOrigin.GENERATED)
        merge_generated(session, course_id, produced)
    except TaxonomyError:
        logger.exception("proposal %s could not be promoted", proposal.slug)
        return False

    proposal.status = ProposalStatus.PROMOTED
    proposal.resolved_skill_id = proposal.slug
    session.add(proposal)
    return True


__all__ = [
    "ReviewReport",
    "normalize_slug",
    "record_proposals",
    "resolve_to_existing",
    "review_proposals",
]
