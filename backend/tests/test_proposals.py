"""Skill proposals: counting on the read path, deciding off it."""

from __future__ import annotations

import pytest
from sqlmodel import Session, SQLModel, create_engine, select

from app.models.enums import SkillOrigin
from app.models.skill import Skill
from app.models.skill_proposal import ProposalStatus, SkillProposal
from app.schemas.taxonomy import RawSkillEntry
from app.services import proposals


@pytest.fixture
def session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


def _entry(id_, name="Chain rule", description="Differentiate a composite.", **kw):
    return RawSkillEntry(
        id=id_,
        name=name,
        description=description,
        difficulty_band=kw.get("difficulty_band", 0.5),
        prereqs=kw.get("prereqs", []),
        keywords=kw.get("keywords", []),
        question_forms=kw.get("question_forms", []),
    )


def _skill(session, skill_id, name, description="d", keywords=None):
    session.add(
        Skill(
            id=skill_id, course_id="calc1", name=name, description=description,
            difficulty_band=0.5, prereqs=[], keywords=keywords or [],
            origin=SkillOrigin.SEED,
        )
    )
    session.commit()


def _record(session, entries, existing=frozenset()):
    return proposals.record_proposals(session, "calc1", entries, set(existing))


class TestRecording:
    def test_a_new_name_becomes_a_pending_proposal_not_a_skill(self, session):
        _record(session, [_entry("chain-rule")])

        assert session.get(Skill, "calc1.chain-rule") is None
        proposal = session.exec(select(SkillProposal)).one()
        assert proposal.slug == "calc1.chain-rule"
        assert proposal.status == ProposalStatus.PENDING
        assert proposal.observations == 1

    def test_repeat_proposals_accumulate_on_one_row(self, session):
        for _ in range(4):
            _record(session, [_entry("chain-rule")])

        proposal = session.exec(select(SkillProposal)).one()
        assert proposal.observations == 4

    def test_an_existing_skill_is_never_proposed(self, session):
        _skill(session, "calc1.chain-rule", "Chain rule")
        _record(session, [_entry("chain-rule")], existing={"calc1.chain-rule"})

        assert session.exec(select(SkillProposal)).all() == []


class TestResolution:
    def test_only_existing_skills_are_attributable(self, session):
        _skill(session, "calc1.chain-rule", "Chain rule")
        resolved = proposals.resolve_to_existing(
            session, "calc1", [_entry("chain-rule"), _entry("invented", name="Invented")]
        )
        assert resolved == ["calc1.chain-rule"]

    def test_a_merged_proposal_resolves_to_the_skill_it_merged_into(self, session):
        _skill(session, "calc1.chain-rule", "Chain rule")
        session.add(
            SkillProposal(
                course_id="calc1", slug="calc1.the-chain-rule", name="The chain rule",
                description="d", difficulty_band=0.5,
                status=ProposalStatus.MERGED, resolved_skill_id="calc1.chain-rule",
            )
        )
        session.commit()

        resolved = proposals.resolve_to_existing(
            session, "calc1", [_entry("the-chain-rule", name="The chain rule")]
        )
        assert resolved == ["calc1.chain-rule"]


class TestReview:
    def test_a_proposal_below_the_threshold_stays_pending(self, session):
        _record(session, [_entry("chain-rule")])
        report = proposals.review_proposals(session, "calc1", min_observations=3)

        assert report.promoted == []
        assert report.still_pending == ["calc1.chain-rule"]
        assert session.get(Skill, "calc1.chain-rule") is None

    def test_a_repeatedly_named_gap_is_promoted_to_a_real_skill(self, session):
        for _ in range(3):
            _record(session, [_entry("chain-rule")])

        report = proposals.review_proposals(session, "calc1", min_observations=3)

        assert report.promoted == ["calc1.chain-rule"]
        promoted = session.get(Skill, "calc1.chain-rule")
        assert promoted is not None
        assert promoted.origin == SkillOrigin.GENERATED
        proposal = session.exec(select(SkillProposal)).one()
        assert proposal.status == ProposalStatus.PROMOTED

    def test_a_near_duplicate_merges_into_the_existing_skill(self, session):
        _skill(session, "calc1.chain-rule", "Chain rule", keywords=["composite"])
        for _ in range(3):
            _record(session, [_entry("the-chain-rule", name="The chain rule")])

        # Stand-in embedder: identical vectors for the two chain-rule texts.
        def embed(texts):
            return [[1.0, 0.0] if "hain rule" in t else [0.0, 1.0] for t in texts]

        report = proposals.review_proposals(
            session, "calc1", embed=embed, min_observations=3
        )

        assert report.merged == {"calc1.the-chain-rule": "calc1.chain-rule"}
        assert report.promoted == []
        assert session.get(Skill, "calc1.the-chain-rule") is None

    def test_a_genuinely_different_skill_survives_the_duplicate_check(self, session):
        _skill(session, "calc1.chain-rule", "Chain rule")
        for _ in range(3):
            _record(session, [_entry("integration-by-parts", name="Integration by parts")])

        def embed(texts):
            return [[1.0, 0.0] if "hain rule" in t else [0.0, 1.0] for t in texts]

        report = proposals.review_proposals(
            session, "calc1", embed=embed, min_observations=3
        )

        assert report.promoted == ["calc1.integration-by-parts"]
        assert report.merged == {}

    def test_without_an_embedder_promotion_says_it_skipped_the_check(self, session):
        _skill(session, "calc1.chain-rule", "Chain rule")
        for _ in range(3):
            _record(session, [_entry("the-chain-rule", name="The chain rule")])

        report = proposals.review_proposals(session, "calc1", min_observations=3)

        assert report.skipped_semantic_check is True
        assert report.promoted == ["calc1.the-chain-rule"]

    def test_a_prereq_naming_an_unpromoted_proposal_is_dropped_not_fatal(self, session):
        for _ in range(3):
            _record(session, [_entry("quotient-rule", name="Quotient rule",
                                     prereqs=["never-promoted"])])

        report = proposals.review_proposals(session, "calc1", min_observations=3)

        assert report.promoted == ["calc1.quotient-rule"]
        assert session.get(Skill, "calc1.quotient-rule").prereqs == []
