"""Tests for skill taxonomy loading, normalization, and validation."""

from __future__ import annotations

import pytest

from app.models.skill import Skill
from app.services.taxonomy import (
    TaxonomyError,
    load_taxonomy,
    normalize_slug,
    validate_taxonomy,
)


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
