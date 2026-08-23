"""Load, normalize, and validate a course's skill taxonomy."""

from __future__ import annotations

import json
import re
from pathlib import Path

from sqlmodel import Session, select

from app.models.skill import Skill

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "courses"

_SLUG_INVALID = re.compile(r"[^a-z0-9.]+")
_SLUG_REPEAT = re.compile(r"-{2,}")


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


def validate_taxonomy(skills: list[Skill]) -> None:
    """Raise TaxonomyError on any structural problem in a skill list."""
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
        for prereq_id in skill.prereqs:
            if prereq_id not in by_id:
                raise TaxonomyError(
                    f"{skill.id}: unresolved prerequisite '{prereq_id}'"
                )

    _validate_acyclic(by_id)


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

    skills: list[Skill] = []
    for entry in raw["skills"]:
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
                origin="seed",
            )
        )

    validate_taxonomy(skills)
    return skills


def seed_all_courses(session: Session, data_dir: Path | None = None) -> None:
    """Load every data/courses/*.json into the DB, skipping courses already seeded.

    Called once on startup. Safe to call repeatedly: a course with any Skill
    rows already present is left untouched.
    """
    directory = data_dir or DATA_DIR
    for path in sorted(directory.glob("*.json")):
        course_id = path.stem
        already_seeded = session.exec(
            select(Skill).where(Skill.course_id == course_id)
        ).first()
        if already_seeded:
            continue
        for skill in load_taxonomy(course_id, data_dir=directory):
            session.add(skill)
    session.commit()
