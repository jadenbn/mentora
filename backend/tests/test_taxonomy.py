"""Tests for the flat topic list: loading, normalization, validation,
seeding from file, and appending new topics via the piggyback path."""

from __future__ import annotations

import json

import pytest
from sqlmodel import Session, SQLModel, create_engine

from app.models.enums import SkillOrigin
from app.models.skill import Skill
from app.services.taxonomy import (
    DATA_DIR,
    TaxonomyError,
    append_skills,
    build_taxonomy,
    canonical_key,
    load_taxonomy,
    normalize_slug,
    seed_all_courses,
    validate_taxonomy,
)


@pytest.fixture
def session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


def _write_course_json(directory, course_id: str, skills: list[dict]) -> None:
    (directory / f"{course_id}.json").write_text(
        json.dumps({"course_id": course_id, "skills": skills}), encoding="utf-8"
    )


class TestLoading:
    def test_load_taxonomy_returns_validated_skills(self) -> None:
        skills = load_taxonomy("calc1")
        assert skills
        assert all(isinstance(s, Skill) for s in skills)
        assert all(s.id.startswith("calc1.") for s in skills)

    def test_every_shipped_course_loads(self) -> None:
        for path in sorted(DATA_DIR.glob("*.json")):
            skills = load_taxonomy(path.stem)
            assert skills
            for skill in skills:
                assert isinstance(skill.keywords, list)
                assert isinstance(skill.question_forms, list)

    def test_load_taxonomy_reads_optional_keyword_and_form_fields(self) -> None:
        by_id = {s.id: s for s in load_taxonomy("calc1")}
        chain = by_id["calc1.derivatives.chain-rule"]
        assert "composite function" in chain.keywords
        assert chain.question_forms


class TestValidation:
    def test_rejects_overlong_keyword_list(self) -> None:
        skills = [
            Skill(id="calc1.a", course_id="calc1", name="A", description="d",
                  difficulty_band=0.5, keywords=[f"k{i}" for i in range(13)]),
        ]
        with pytest.raises(TaxonomyError, match="keywords"):
            validate_taxonomy(skills)

    def test_rejects_empty_and_overlong_entries(self) -> None:
        blank = [Skill(id="calc1.a", course_id="calc1", name="A", description="d",
                       difficulty_band=0.5, question_forms=["  "])]
        with pytest.raises(TaxonomyError, match="non-empty"):
            validate_taxonomy(blank)

        huge = [Skill(id="calc1.b", course_id="calc1", name="B", description="d",
                      difficulty_band=0.5, keywords=["x" * 81])]
        with pytest.raises(TaxonomyError, match="chars"):
            validate_taxonomy(huge)

    def test_rejects_duplicate_ids(self) -> None:
        skills = [
            Skill(id="calc1.a", course_id="calc1", name="A", description="d", difficulty_band=0.5),
            Skill(id="calc1.a", course_id="calc1", name="A again", description="d", difficulty_band=0.5),
        ]
        with pytest.raises(TaxonomyError, match="duplicate"):
            validate_taxonomy(skills)

    def test_rejects_out_of_bounds_difficulty(self) -> None:
        skills = [
            Skill(id="calc1.a", course_id="calc1", name="A", description="d", difficulty_band=1.5),
        ]
        with pytest.raises(TaxonomyError, match=r"out of \[0, 1\]"):
            validate_taxonomy(skills)

    def test_rejects_too_many_skills(self) -> None:
        skills = [
            Skill(id=f"calc1.s{i}", course_id="calc1", name=f"S{i}", description="d",
                  difficulty_band=0.5)
            for i in range(201)
        ]
        with pytest.raises(TaxonomyError, match="200"):
            validate_taxonomy(skills)

    def test_accepts_a_flat_valid_list(self) -> None:
        skills = [
            Skill(id="calc1.a", course_id="calc1", name="A", description="d", difficulty_band=0.2),
            Skill(id="calc1.b", course_id="calc1", name="B", description="d", difficulty_band=0.4),
        ]
        validate_taxonomy(skills)  # must not raise


class TestNormalizeSlug:
    def test_is_idempotent(self) -> None:
        cases = ["Chain Rule!!", "  power_rule  ", "calc1.derivatives.chain-rule", "u-substitution"]
        for raw in cases:
            once = normalize_slug("calc1", raw)
            twice = normalize_slug("calc1", once)
            assert once == twice

    def test_prefixes_course(self) -> None:
        assert normalize_slug("calc1", "chain-rule") == "calc1.chain-rule"
        assert normalize_slug("calc1", "calc1.chain-rule") == "calc1.chain-rule"

    def test_collapses_and_lowercases(self) -> None:
        assert normalize_slug("calc1", "Product   Rule") == "calc1.product-rule"

    def test_underscore_course_id_does_not_double_prefix(self) -> None:
        """Regression: a course id like "course_demo" contains a character
        (underscore) the slug substitution rewrites to a hyphen. Comparing the
        normalized slug against the raw, un-normalized course id used to miss
        the match and prepend the prefix a second time."""
        bare = normalize_slug("course_demo", "differentiation-product-rule")
        prefixed_underscore = normalize_slug(
            "course_demo", "course_demo.differentiation-product-rule"
        )
        prefixed_hyphen = normalize_slug(
            "course_demo", "course-demo.differentiation-product-rule"
        )
        assert bare == "course_demo.differentiation-product-rule"
        assert prefixed_underscore == bare
        assert prefixed_hyphen == bare

    def test_underscore_course_id_is_idempotent(self) -> None:
        cases = [
            "differentiation-product-rule",
            "course_demo.differentiation-product-rule",
            "COURSE_DEMO.Differentiation Product Rule",
        ]
        for raw in cases:
            once = normalize_slug("course_demo", raw)
            twice = normalize_slug("course_demo", once)
            assert once == twice


class TestCanonicalKey:
    def test_ignores_case_articles_and_word_order(self) -> None:
        assert canonical_key("The Chain Rule") == canonical_key("chain rule")
        assert canonical_key("Rule, Chain") == canonical_key("chain rule")

    def test_distinguishes_different_topics(self) -> None:
        assert canonical_key("Chain rule") != canonical_key("Product rule")

    def test_empty_after_stopwords_does_not_crash(self) -> None:
        assert canonical_key("the a of") == ""


class TestBuildTaxonomy:
    def test_is_the_shared_path_load_taxonomy_uses(self) -> None:
        raw = [
            {"id": "root", "name": "Root", "description": "d", "difficulty_band": 0.2},
            {"id": "child", "name": "Child", "description": "d", "difficulty_band": 0.5,
             "keywords": ["k1"], "question_forms": ["solve for x"]},
        ]
        built = build_taxonomy("calc1", raw, SkillOrigin.SEED)
        assert [s.id for s in built] == ["calc1.root", "calc1.child"]
        assert all(s.origin == SkillOrigin.SEED for s in built)

    def test_tags_generated_origin(self) -> None:
        raw = [{"id": "x", "name": "X", "description": "d", "difficulty_band": 0.3}]
        built = build_taxonomy("calc1", raw, SkillOrigin.GENERATED)
        assert built[0].origin == SkillOrigin.GENERATED

    def test_enforces_the_same_validation_as_validate_taxonomy(self) -> None:
        bad = [{"id": "a", "name": "A", "description": "d", "difficulty_band": 4.2}]
        with pytest.raises(TaxonomyError, match=r"out of \[0, 1\]"):
            build_taxonomy("calc1", bad, SkillOrigin.GENERATED)


class TestSeedAllCourses:
    def test_reseed_reflects_a_changed_file(self, session, tmp_path) -> None:
        _write_course_json(tmp_path, "calc1", [
            {"id": "root", "name": "Root", "description": "v1", "difficulty_band": 0.2},
        ])
        seed_all_courses(session, data_dir=tmp_path)
        assert session.get(Skill, "calc1.root").description == "v1"

        _write_course_json(tmp_path, "calc1", [
            {"id": "root", "name": "Root", "description": "v2", "difficulty_band": 0.2},
            {"id": "extra", "name": "Extra", "description": "new", "difficulty_band": 0.3},
        ])
        seed_all_courses(session, data_dir=tmp_path)

        assert session.get(Skill, "calc1.root").description == "v2"
        assert session.get(Skill, "calc1.extra") is not None

    def test_unchanged_file_is_a_noop(self, session, tmp_path) -> None:
        _write_course_json(tmp_path, "calc1", [
            {"id": "root", "name": "Root", "description": "d", "difficulty_band": 0.2},
        ])
        seed_all_courses(session, data_dir=tmp_path)
        # A row seed_all_courses didn't put there -- if the no-op guard fires
        # correctly, the unrelated file hash match means this call never
        # touches Skill rows for the course at all, and this survives.
        session.add(Skill(id="calc1.untracked", course_id="calc1", name="Untracked",
                          description="d", difficulty_band=0.4, origin=SkillOrigin.GENERATED))
        session.commit()

        seed_all_courses(session, data_dir=tmp_path)
        assert session.get(Skill, "calc1.untracked") is not None
        assert session.get(Skill, "calc1.root") is not None

    def test_reseed_after_append_skills_keeps_the_appended_topic(self, session, tmp_path) -> None:
        """append_skills writes into the same file seeding reads from, so a
        topic it added is not lost even if something else forces a reseed."""
        _write_course_json(tmp_path, "calc1", [
            {"id": "root", "name": "Root", "description": "d", "difficulty_band": 0.2},
        ])
        seed_all_courses(session, data_dir=tmp_path)

        produced = build_taxonomy(
            "calc1",
            [{"id": "piggyback", "name": "Piggyback", "description": "d", "difficulty_band": 0.4}],
            SkillOrigin.GENERATED,
        )
        append_skills(session, "calc1", produced, data_dir=tmp_path)

        # Something external changes the file -- forces a real reseed pass.
        _write_course_json(tmp_path, "calc1", json.loads(
            (tmp_path / "calc1.json").read_text(encoding="utf-8")
        )["skills"] + [{"id": "another", "name": "Another", "description": "d", "difficulty_band": 0.6}])
        seed_all_courses(session, data_dir=tmp_path)

        assert session.get(Skill, "calc1.piggyback") is not None
        assert session.get(Skill, "calc1.another") is not None


class TestAppendSkills:
    def test_adds_a_new_topic_to_the_file_and_the_db(self, session, tmp_path) -> None:
        _write_course_json(tmp_path, "calc1", [
            {"id": "root", "name": "Root", "description": "d", "difficulty_band": 0.2},
        ])
        produced = build_taxonomy(
            "calc1",
            [{"id": "new-topic", "name": "New topic", "description": "d", "difficulty_band": 0.3}],
            SkillOrigin.GENERATED,
        )
        added = append_skills(session, "calc1", produced, data_dir=tmp_path)

        assert added == ["calc1.new-topic"]
        assert session.get(Skill, "calc1.new-topic") is not None
        on_disk = json.loads((tmp_path / "calc1.json").read_text(encoding="utf-8"))
        assert any(s["id"] == "calc1.new-topic" for s in on_disk["skills"])

    def test_skips_an_id_that_already_exists(self, session, tmp_path) -> None:
        _write_course_json(tmp_path, "calc1", [
            {"id": "root", "name": "Root", "description": "d", "difficulty_band": 0.2},
        ])
        produced = build_taxonomy(
            "calc1",
            [{"id": "root", "name": "Overwrite attempt", "description": "x", "difficulty_band": 0.9}],
            SkillOrigin.GENERATED,
        )
        added = append_skills(session, "calc1", produced, data_dir=tmp_path)

        assert added == []
        on_disk = json.loads((tmp_path / "calc1.json").read_text(encoding="utf-8"))
        assert on_disk["skills"] == [
            {"id": "calc1.root", "name": "Root", "description": "d", "difficulty_band": 0.2}
        ] or on_disk["skills"][0]["name"] == "Root"  # untouched, not overwritten

    def test_never_deletes_an_existing_topic(self, session, tmp_path) -> None:
        _write_course_json(tmp_path, "calc1", [
            {"id": "old", "name": "Old", "description": "d", "difficulty_band": 0.3},
        ])
        seed_all_courses(session, data_dir=tmp_path)

        produced = build_taxonomy(
            "calc1",
            [{"id": "new", "name": "New", "description": "d", "difficulty_band": 0.4}],
            SkillOrigin.GENERATED,
        )
        append_skills(session, "calc1", produced, data_dir=tmp_path)

        assert session.get(Skill, "calc1.old") is not None
        assert session.get(Skill, "calc1.new") is not None

    def test_empty_batch_is_a_noop(self, session, tmp_path) -> None:
        _write_course_json(tmp_path, "calc1", [])
        assert append_skills(session, "calc1", [], data_dir=tmp_path) == []
