"""Load, normalize, and validate a course's skill taxonomy."""

from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path

from sqlmodel import Session, select

from app.models.course_taxonomy_version import CourseTaxonomyVersion
from app.models.enums import SkillOrigin
from app.models.skill import Skill
from app.models.skill_state import SkillState

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "courses"

_SLUG_INVALID = re.compile(r"[^a-z0-9.]+")
_SLUG_REPEAT = re.compile(r"-{2,}")

_MAX_LIST_ENTRIES = 12
_MAX_ENTRY_CHARS = 80
_MAX_SKILLS_PER_COURSE = 200


class TaxonomyError(ValueError):
    """A course's skill taxonomy failed validation on load."""


def normalize_slug(course_id: str, raw: str) -> str:
    """Lowercase, hyphenate, collapse repeats, and course-prefix a skill id.

    Idempotent: normalize_slug(c, normalize_slug(c, x)) == normalize_slug(c, x).
    """
    slug = raw.strip().lower()
    slug = _SLUG_INVALID.sub("-", slug)
    slug = _SLUG_REPEAT.sub("-", slug).strip("-")
    prefix = f"{course_id}."
    if not slug.startswith(prefix):
        slug = f"{prefix}{slug}"
    return slug


def _validate_acyclic(skills: dict[str, Skill]) -> None:
    """Depth-first search with a visiting set. Raises on any cycle."""
    WHITE, GRAY, BLACK = 0, 1, 2
    state = {skill_id: WHITE for skill_id in skills}

    def visit(skill_id: str, path: list[str]) -> None:
        state[skill_id] = GRAY
        for prereq_id in skills[skill_id].prereqs:
            if state.get(prereq_id) == GRAY:
                cycle = " -> ".join(path + [prereq_id])
                raise TaxonomyError(f"prerequisite cycle detected: {cycle}")
            if state.get(prereq_id) == WHITE:
                visit(prereq_id, path + [prereq_id])
        state[skill_id] = BLACK

    for skill_id in skills:
        if state[skill_id] == WHITE:
            visit(skill_id, [skill_id])


def _validate_string_list(skill_id: str, field: str, values: list[str]) -> None:
    """Guard the free-form keyword / question_form lists before they reach an
    embedding call: non-empty strings, at most 12 entries, each <= 80 chars."""
    if len(values) > _MAX_LIST_ENTRIES:
        raise TaxonomyError(
            f"{skill_id}: {field} has {len(values)} entries "
            f"(max {_MAX_LIST_ENTRIES})"
        )
    for entry in values:
        if not isinstance(entry, str) or not entry.strip():
            raise TaxonomyError(f"{skill_id}: {field} entries must be non-empty strings")
        if len(entry) > _MAX_ENTRY_CHARS:
            raise TaxonomyError(
                f"{skill_id}: {field} entry exceeds {_MAX_ENTRY_CHARS} chars: {entry!r}"
            )


def validate_taxonomy(skills: list[Skill]) -> None:
    """Raise TaxonomyError on any structural problem in a skill list."""
    if len(skills) > _MAX_SKILLS_PER_COURSE:
        raise TaxonomyError(
            f"course has {len(skills)} skills (max {_MAX_SKILLS_PER_COURSE}); "
            "a generator producing this many likely malfunctioned"
        )

    by_id: dict[str, Skill] = {}
    for skill in skills:
        if skill.id in by_id:
            raise TaxonomyError(f"duplicate skill id after normalization: {skill.id}")
        by_id[skill.id] = skill

    for skill in skills:
        if not (0.0 <= skill.difficulty_band <= 1.0):
            raise TaxonomyError(
                f"{skill.id}: difficulty_band {skill.difficulty_band} out of [0, 1]"
            )
        _validate_string_list(skill.id, "keywords", skill.keywords)
        _validate_string_list(skill.id, "question_forms", skill.question_forms)
        for prereq_id in skill.prereqs:
            if prereq_id not in by_id:
                raise TaxonomyError(
                    f"{skill.id}: unresolved prerequisite '{prereq_id}'"
                )

    _validate_acyclic(by_id)


def build_taxonomy(
    course_id: str, raw_skills: list[dict], origin: SkillOrigin
) -> list[Skill]:
    """Turn a list of raw skill dicts into validated Skill objects.

    The single builder for every taxonomy source — hand-authored course JSON
    and LLM-generated output alike take this same path, so a generated skill
    is held to exactly the rules a seeded one is: normalized ids, resolved
    prereqs, no cycles, bounded keyword/question-form lists. Raises
    TaxonomyError on any structural problem; raises nothing on success.
    """
    skills: list[Skill] = []
    for entry in raw_skills:
        skill_id = normalize_slug(course_id, entry["id"])
        prereqs = [normalize_slug(course_id, p) for p in entry.get("prereqs", [])]
        skills.append(
            Skill(
                id=skill_id,
                course_id=course_id,
                name=entry["name"],
                description=entry["description"],
                difficulty_band=entry["difficulty_band"],
                prereqs=prereqs,
                keywords=list(entry.get("keywords", [])),
                question_forms=list(entry.get("question_forms", [])),
                origin=origin,
            )
        )

    validate_taxonomy(skills)
    return skills


def load_taxonomy(course_id: str, data_dir: Path | None = None) -> list[Skill]:
    """Load a course's seed taxonomy from data/courses/{course_id}.json.

    Normalizes every id (including hand-authored ones) and validates the
    result before returning. Raises TaxonomyError on any structural problem.
    """
    directory = data_dir or DATA_DIR
    path = directory / f"{course_id}.json"
    raw = json.loads(path.read_text(encoding="utf-8"))

    if raw.get("course_id") != course_id:
        raise TaxonomyError(
            f"{path}: course_id mismatch (expected {course_id}, "
            f"got {raw.get('course_id')})"
        )

    return build_taxonomy(course_id, raw["skills"], SkillOrigin.SEED)


def _course_content_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def seed_all_courses(session: Session, data_dir: Path | None = None) -> None:
    """Load every data/courses/*.json into the DB, re-seeding on file change.

    Called once on startup. Safe to call repeatedly: a course is re-seeded
    only when its JSON file's content hash differs from what was last seeded.
    Editing a course file and restarting therefore takes effect, instead of
    being silently ignored because rows already exist.

    Re-seeding deletes and reinserts only that course's origin=SEED rows.
    Generated skills (origin=GENERATED — from bootstrap_first_skill or any
    future generation path) are never touched by this function: a course
    that has both hand-authored and generated skills must survive a restart
    with its generated skills intact, not have them wiped because the seed
    file happened to change (or even because it didn't — deleting "every
    Skill row for this course" was the trap this scoping fixes).

    SkillState is keyed by skill_id and is left untouched regardless, so
    per-student progress survives; but a seed skill renamed or removed in the
    edit orphans its SkillState, which is logged rather than dropped quietly.
    """
    directory = data_dir or DATA_DIR
    for path in sorted(directory.glob("*.json")):
        course_id = path.stem
        content_hash = _course_content_hash(path)

        version = session.get(CourseTaxonomyVersion, course_id)
        existing_seed = session.exec(
            select(Skill).where(
                Skill.course_id == course_id, Skill.origin == SkillOrigin.SEED
            )
        ).all()
        if version is not None and version.content_hash == content_hash and existing_seed:
            continue

        loaded = load_taxonomy(course_id, data_dir=directory)

        if existing_seed:
            old_ids = {s.id for s in existing_seed}
            new_ids = {s.id for s in loaded}
            orphaned = sorted(old_ids - new_ids)
            if orphaned:
                stranded = [
                    skill_id
                    for skill_id in orphaned
                    if session.exec(
                        select(SkillState).where(SkillState.skill_id == skill_id)
                    ).first()
                    is not None
                ]
                if stranded:
                    logger.warning(
                        "re-seeding %s orphaned SkillState for removed/renamed "
                        "skills (progress preserved but unreachable): %s",
                        course_id,
                        stranded,
                    )
            for skill in existing_seed:
                session.delete(skill)
            session.flush()

        for skill in loaded:
            session.add(skill)

        if version is None:
            session.add(
                CourseTaxonomyVersion(course_id=course_id, content_hash=content_hash)
            )
        else:
            version.content_hash = content_hash
            session.add(version)

    session.commit()


@dataclass(frozen=True)
class MergeReport:
    added: list[str]
    updated: list[str]
    blocked_seed_collisions: list[str]


def merge_generated(session: Session, course_id: str, produced: list[Skill]) -> MergeReport:
    """Additively merge a freshly generated (or emergent) batch into a course.

    Upserts by id: a produced skill whose id already belongs to a GENERATED
    skill updates its describing fields (name, description, difficulty,
    keywords, question_forms). SkillState is never touched here — it is
    keyed by skill_id in a different table and survives any update to the
    Skill row it names. A seed skill is read-only: a produced id colliding
    with an origin=SEED skill is skipped and logged, never overwritten.

    Nothing already in the course is ever deleted by this function. Removal
    is a separate, deliberate operation and is out of scope here.

    Validates the graph this merge would *produce* — every existing skill
    this batch doesn't touch, plus the batch — as one unit, so a new skill's
    prereq on an existing skill resolves, and so no addition introduces a
    cycle spanning old and new skills, not just within the new batch.
    """
    existing = session.exec(select(Skill).where(Skill.course_id == course_id)).all()
    existing_by_id = {s.id: s for s in existing}

    to_apply: list[Skill] = []
    blocked: list[str] = []
    for skill in produced:
        current = existing_by_id.get(skill.id)
        if current is not None and current.origin != SkillOrigin.GENERATED:
            blocked.append(skill.id)
            continue
        to_apply.append(skill)

    if blocked:
        logger.warning(
            "merge_generated for %s: %d produced skill(s) collided with "
            "non-generated (seed) skill ids and were not applied: %s",
            course_id,
            len(blocked),
            blocked,
        )

    apply_ids = {s.id for s in to_apply}
    resulting = [s for s in existing if s.id not in apply_ids] + to_apply
    validate_taxonomy(resulting)

    added: list[str] = []
    updated: list[str] = []
    for skill in to_apply:
        current = existing_by_id.get(skill.id)
        if current is None:
            session.add(skill)
            added.append(skill.id)
        else:
            current.name = skill.name
            current.description = skill.description
            current.difficulty_band = skill.difficulty_band
            current.prereqs = skill.prereqs
            current.keywords = skill.keywords
            current.question_forms = skill.question_forms
            session.add(current)
            updated.append(skill.id)

    session.commit()
    return MergeReport(added=added, updated=updated, blocked_seed_collisions=blocked)
