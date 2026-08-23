"""Tests for skill taxonomy loading, normalization, and validation."""

from __future__ import annotations

import pytest
from sqlmodel import Session, SQLModel, create_engine

from app.models.skill import Skill
from app.services.taxonomy import (
    TaxonomyError,
    load_taxonomy,
    normalize_slug,
    validate_taxonomy,
)
from app.services.tutor_taxonomy import build_seeded_taxonomy_fallback


def test_load_taxonomy_returns_fifteen_validated_skills() -> None:
    skills = load_taxonomy("calc1")
    assert len(skills) == 15
    assert all(isinstance(s, Skill) for s in skills)
    assert all(s.id.startswith("calc1.") for s in skills)


def test_normalize_slug_is_idempotent() -> None:
    cases = ["Chain Rule!!", "  power_rule  ", "calc1.derivatives.chain-rule", "u-substitution"]
    for raw in cases:
        once = normalize_slug("calc1", raw)
        twice = normalize_slug("calc1", once)
        assert once == twice


def test_normalize_slug_prefixes_course() -> None:
    assert normalize_slug("calc1", "chain-rule") == "calc1.chain-rule"
    assert normalize_slug("calc1", "calc1.chain-rule") == "calc1.chain-rule"


def test_normalize_slug_collapses_and_lowercases() -> None:
    assert normalize_slug("calc1", "Product   Rule") == "calc1.product-rule"


def test_validate_taxonomy_rejects_unresolved_prereq() -> None:
    skills = [
        Skill(
            id="calc1.a",
            course_id="calc1",
            name="A",
            description="d",
            difficulty_band=0.5,
            prereqs=["calc1.does-not-exist"],
        )
    ]
    with pytest.raises(TaxonomyError, match="unresolved prerequisite"):
        validate_taxonomy(skills)


def test_validate_taxonomy_rejects_cycle() -> None:
    skills = [
        Skill(id="calc1.a", course_id="calc1", name="A", description="d",
              difficulty_band=0.5, prereqs=["calc1.b"]),
        Skill(id="calc1.b", course_id="calc1", name="B", description="d",
              difficulty_band=0.5, prereqs=["calc1.a"]),
    ]
    with pytest.raises(TaxonomyError, match="cycle"):
        validate_taxonomy(skills)


def test_validate_taxonomy_rejects_duplicate_ids() -> None:
    skills = [
        Skill(id="calc1.a", course_id="calc1", name="A", description="d",
              difficulty_band=0.5, prereqs=[]),
        Skill(id="calc1.a", course_id="calc1", name="A again", description="d",
              difficulty_band=0.5, prereqs=[]),
    ]
    with pytest.raises(TaxonomyError, match="duplicate"):
        validate_taxonomy(skills)


def test_validate_taxonomy_rejects_out_of_bounds_difficulty() -> None:
    skills = [
        Skill(id="calc1.a", course_id="calc1", name="A", description="d",
              difficulty_band=1.5, prereqs=[]),
    ]
    with pytest.raises(TaxonomyError, match="out of \\[0, 1\\]"):
        validate_taxonomy(skills)


def test_validate_taxonomy_accepts_valid_dag() -> None:
    skills = [
        Skill(id="calc1.a", course_id="calc1", name="A", description="d",
              difficulty_band=0.2, prereqs=[]),
        Skill(id="calc1.b", course_id="calc1", name="B", description="d",
              difficulty_band=0.4, prereqs=["calc1.a"]),
        Skill(id="calc1.c", course_id="calc1", name="C", description="d",
              difficulty_band=0.6, prereqs=["calc1.a", "calc1.b"]),
    ]
    validate_taxonomy(skills)  # must not raise


def test_tutor_fallback_contains_only_expected_skills_and_direct_prerequisites() -> None:
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        session.add_all(load_taxonomy("calc1"))
        session.commit()

        results = build_seeded_taxonomy_fallback(
            session,
            course_id="calc1",
            expected_skill_ids=["calc1.derivatives.chain-rule"],
            limit=5,
        )

    assert [result["score"] for result in results] == [1.0, 0.9]
    assert "calc1.derivatives.chain-rule" in results[0]["text"]
    assert "calc1.derivatives.power-rule" in results[1]["text"]
    assert all(result["filename"] == "calc1-seeded-taxonomy" for result in results)


def test_tutor_fallback_rejects_courses_without_a_validated_seed() -> None:
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(
            Skill(
                id="custom.skill",
                course_id="custom",
                name="Custom skill",
                description="Not a validated seed file.",
                difficulty_band=0.5,
                prereqs=[],
            )
        )
        session.commit()

        assert build_seeded_taxonomy_fallback(
            session,
            course_id="custom",
            expected_skill_ids=["custom.skill"],
            limit=5,
        ) == []
