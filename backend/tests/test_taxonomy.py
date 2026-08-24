"""Tests for skill taxonomy loading, normalization, and validation."""

from __future__ import annotations

import pytest

from app.models.enums import SkillOrigin
from app.models.skill import Skill
from app.services.taxonomy import (
    DATA_DIR,
    TaxonomyError,
    build_taxonomy,
    load_taxonomy,
    normalize_slug,
    validate_taxonomy,
)


def test_load_taxonomy_returns_fifteen_validated_skills() -> None:
    skills = load_taxonomy("calc1")
    assert len(skills) == 15
    assert all(isinstance(s, Skill) for s in skills)
    assert all(s.id.startswith("calc1.") for s in skills)


def test_every_course_json_still_loads() -> None:
    """All shipped courses load; the new fields are optional and default empty."""
    for path in sorted(DATA_DIR.glob("*.json")):
        skills = load_taxonomy(path.stem)
        assert skills
        for skill in skills:
            assert isinstance(skill.keywords, list)
            assert isinstance(skill.question_forms, list)


def test_load_taxonomy_reads_optional_keyword_and_form_fields() -> None:
    by_id = {s.id: s for s in load_taxonomy("calc1")}
    chain = by_id["calc1.derivatives.chain-rule"]
    assert "composite function" in chain.keywords
    assert chain.question_forms  # calc1 populates these


def test_validate_taxonomy_rejects_overlong_keyword_list() -> None:
    skills = [
        Skill(id="calc1.a", course_id="calc1", name="A", description="d",
              difficulty_band=0.5, prereqs=[], keywords=[f"k{i}" for i in range(13)]),
    ]
    with pytest.raises(TaxonomyError, match="keywords"):
        validate_taxonomy(skills)


def test_validate_taxonomy_rejects_empty_and_overlong_entries() -> None:
    blank = [Skill(id="calc1.a", course_id="calc1", name="A", description="d",
                   difficulty_band=0.5, prereqs=[], question_forms=["  "])]
    with pytest.raises(TaxonomyError, match="non-empty"):
        validate_taxonomy(blank)

    huge = [Skill(id="calc1.b", course_id="calc1", name="B", description="d",
                  difficulty_band=0.5, prereqs=[], keywords=["x" * 81])]
    with pytest.raises(TaxonomyError, match="chars"):
        validate_taxonomy(huge)


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


def test_build_taxonomy_is_the_shared_path_for_load_taxonomy() -> None:
    """load_taxonomy is build_taxonomy(..., SEED) over the course file's raw dicts."""
    raw = [
        {"id": "root", "name": "Root", "description": "d", "difficulty_band": 0.2},
        {"id": "child", "name": "Child", "description": "d", "difficulty_band": 0.5,
         "prereqs": ["root"], "keywords": ["k1"], "question_forms": ["solve for x"]},
    ]
    built = build_taxonomy("calc1", raw, SkillOrigin.SEED)
    assert [s.id for s in built] == ["calc1.root", "calc1.child"]
    assert built[1].prereqs == ["calc1.root"]
    assert all(s.origin == SkillOrigin.SEED for s in built)


def test_build_taxonomy_tags_generated_origin() -> None:
    raw = [{"id": "x", "name": "X", "description": "d", "difficulty_band": 0.3}]
    built = build_taxonomy("calc1", raw, SkillOrigin.GENERATED)
    assert built[0].origin == SkillOrigin.GENERATED


def test_build_taxonomy_enforces_the_same_validation_as_load_taxonomy() -> None:
    cyclic = [
        {"id": "a", "name": "A", "description": "d", "difficulty_band": 0.5, "prereqs": ["b"]},
        {"id": "b", "name": "B", "description": "d", "difficulty_band": 0.5, "prereqs": ["a"]},
    ]
    with pytest.raises(TaxonomyError, match="cycle"):
        build_taxonomy("calc1", cyclic, SkillOrigin.GENERATED)


def test_validate_taxonomy_rejects_too_many_skills() -> None:
    skills = [
        Skill(id=f"calc1.s{i}", course_id="calc1", name=f"S{i}", description="d",
              difficulty_band=0.5, prereqs=[])
        for i in range(201)
    ]
    with pytest.raises(TaxonomyError, match="200"):
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
