"""Normalize and validate a course's flat topic list, and get it into the DB.

A topic is a label for grouping attempts, not a node in a curriculum: there
is no prerequisite graph and nothing here gates what a student can be served.

Topics are model-generated. data/courses/{course_id}.json only bootstraps a
course that has none yet; after that the database is the source of truth and
add_skills is the only way the list grows.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from sqlmodel import Session, select

from app.models.enums import SkillOrigin
from app.models.skill import Skill

logger = logging.getLogger(__name__)


# Read-only: nothing writes to these files. seed_all_courses takes a data_dir
# override for tests that need their own bootstrap set.
DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "courses"

_SLUG_INVALID = re.compile(r"[^a-z0-9.]+")
_SLUG_REPEAT = re.compile(r"-{2,}")

# Dropped from a canonical-name key: they carry no identity ("the chain rule"
# and "chain rule" are the same topic; "power rule" and "product rule" are not).
_STOPWORDS = {"a", "an", "the", "of", "for", "to", "and", "rule", "rules"}

_MAX_LIST_ENTRIES = 12
_MAX_ENTRY_CHARS = 80
_MAX_SKILLS_PER_COURSE = 200


class TaxonomyError(ValueError):
    """A course's topic list failed validation."""


def normalize_slug(course_id: str, raw: str) -> str:
    """Lowercase, hyphenate, collapse repeats, and course-prefix a topic id.

    Idempotent: normalize_slug(c, normalize_slug(c, x)) == normalize_slug(c, x).

    A course id containing characters outside [a-z0-9.] (e.g. "course_demo")
    goes through the same substitution as the raw slug before either is
    compared -- otherwise a raw id that already includes the course prefix
    (e.g. a model echoing "course_demo.foo" back) fails the startswith check
    against the unnormalized course_id and gets prefixed a second time.
    """
    slug = raw.strip().lower()
    slug = _SLUG_INVALID.sub("-", slug)
    slug = _SLUG_REPEAT.sub("-", slug).strip("-")

    normalized_course_id = _SLUG_INVALID.sub("-", course_id.strip().lower())
    normalized_course_id = _SLUG_REPEAT.sub("-", normalized_course_id).strip("-")
    normalized_prefix = f"{normalized_course_id}."
    if slug.startswith(normalized_prefix):
        slug = slug[len(normalized_prefix):]

    return f"{course_id}.{slug}"


def canonical_key(name: str) -> str:
    """A name-similarity key: same words, any order, any article or case.

    Two names reduce to the same key when they share the same significant
    words regardless of order, casing, or stopwords -- enough to catch a
    model re-describing an existing topic in different words without an
    embedding call. Two genuinely different topics sharing this key would be
    a false merge; that is the accepted tradeoff for a check this cheap.
    """
    words = re.findall(r"[a-z0-9]+", name.lower())
    return "-".join(sorted(w for w in words if w not in _STOPWORDS))


def _validate_string_list(skill_id: str, field: str, values: list[str]) -> None:
    """Guard the free-form keyword / question_form lists: non-empty strings,
    at most 12 entries, each <= 80 chars."""
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
    """Raise TaxonomyError on any structural problem in a topic list."""
    if len(skills) > _MAX_SKILLS_PER_COURSE:
        raise TaxonomyError(
            f"course has {len(skills)} skills (max {_MAX_SKILLS_PER_COURSE}); "
            "a generator producing this many likely malfunctioned"
        )

    seen: set[str] = set()
    for skill in skills:
        if skill.id in seen:
            raise TaxonomyError(f"duplicate skill id after normalization: {skill.id}")
        seen.add(skill.id)
        if not (0.0 <= skill.difficulty_band <= 1.0):
            raise TaxonomyError(
                f"{skill.id}: difficulty_band {skill.difficulty_band} out of [0, 1]"
            )
        _validate_string_list(skill.id, "keywords", skill.keywords)
        _validate_string_list(skill.id, "question_forms", skill.question_forms)


def build_taxonomy(
    course_id: str, raw_skills: list[dict], origin: SkillOrigin
) -> list[Skill]:
    """Turn a list of raw skill dicts into validated Skill objects.

    The single builder for every topic source -- bootstrap course JSON and
    model-identified topics alike take this same path. Raises TaxonomyError
    on any structural problem; raises nothing on success.
    """
    skills = [
        Skill(
            id=normalize_slug(course_id, entry["id"]),
            course_id=course_id,
            name=entry["name"],
            description=entry["description"],
            difficulty_band=entry["difficulty_band"],
            keywords=list(entry.get("keywords", [])),
            question_forms=list(entry.get("question_forms", [])),
            origin=origin,
        )
        for entry in raw_skills
    ]
    validate_taxonomy(skills)
    return skills


def load_taxonomy(course_id: str, data_dir: Path | None = None) -> list[Skill]:
    """Load a course's bootstrap topic list from data/courses/{course_id}.json.

    Normalizes every id and validates the result before returning. Raises
    TaxonomyError on any structural problem.
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


def seed_all_courses(session: Session, data_dir: Path | None = None) -> None:
    """Give every course in data/courses a starting topic list, once.

    Called on startup. A course that already has skills is skipped entirely:
    the database is the source of truth, and everything the model has added
    since lives only there.
    """
    directory = data_dir or DATA_DIR
    for path in sorted(directory.glob("*.json")):
        course_id = path.stem
        already_seeded = session.exec(
            select(Skill.id).where(Skill.course_id == course_id).limit(1)
        ).first()
        if already_seeded:
            continue

        for skill in load_taxonomy(course_id, data_dir=directory):
            session.add(skill)

    session.commit()


def add_skills(session: Session, course_id: str, produced: list[Skill]) -> list[str]:
    """Insert newly-identified topics, skipping ids the course already has.

    An existing topic's fields are never rewritten by a later question's read
    of it. Returns the ids actually added.
    """
    if not produced:
        return []

    existing_ids = set(
        session.exec(select(Skill.id).where(Skill.course_id == course_id)).all()
    )

    added: list[str] = []
    for skill in produced:
        if skill.id in existing_ids:
            continue
        session.add(skill)
        existing_ids.add(skill.id)
        added.append(skill.id)

    if added:
        session.commit()

    return added
