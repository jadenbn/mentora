"""The dev/analytics overview: all skills, unlock state, seed defaults."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlmodel import Session, SQLModel, create_engine

from app.models.enums import SkillOrigin
from app.models.skill import Skill
from app.schemas.learning import AttemptCreate
from app.services import student_model_service


@pytest.fixture
def session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


def _seed(session):
    session.add(Skill(id="calc1.a", course_id="calc1", name="A", description="root",
                      difficulty_band=0.3, prereqs=[]))
    session.add(Skill(id="calc1.b", course_id="calc1", name="B", description="child",
                      difficulty_band=0.5, prereqs=["calc1.a"]))
    session.commit()


def test_overview_lists_every_skill_including_untouched(session):
    _seed(session)
    ov = student_model_service.get_skills_overview(session, "calc1", "stu1")
    ids = {s.skill_id for s in ov.skills}
    assert ids == {"calc1.a", "calc1.b"}
    for s in ov.skills:
        assert s.has_state is False
        assert s.attempts == 0
        assert s.mastery == pytest.approx(0.5)  # cold-start seed


def test_overview_unlock_state_tracks_prereq_mastery(session):
    _seed(session)
    # Root has no prereqs -> unlocked; child's prereq is at seed 0.5 < 0.6 -> locked.
    ov = student_model_service.get_skills_overview(session, "calc1", "stu1")
    by_id = {s.skill_id: s for s in ov.skills}
    assert by_id["calc1.a"].unlocked is True
    assert by_id["calc1.b"].unlocked is False

    # Raise the root past the unlock threshold with correct attempts.
    for i in range(6):
        student_model_service.record_attempt(
            session, "calc1",
            AttemptCreate(student_id="stu1", session_id="s", problem_id=f"p{i}",
                          expected_skills=["calc1.a"], difficulty=0.3, correct=True),
        )
    ov2 = student_model_service.get_skills_overview(session, "calc1", "stu1")
    by_id2 = {s.skill_id: s for s in ov2.skills}
    assert by_id2["calc1.a"].mastery >= 0.6
    assert by_id2["calc1.b"].unlocked is True
    assert by_id2["calc1.a"].has_state is True
    assert ov2.next_skill_id in {"calc1.a", "calc1.b"}


def test_overview_exposes_origin_keywords_and_recency(session):
    now = datetime.now(timezone.utc)
    session.add(Skill(id="calc1.old", course_id="calc1", name="Old", description="d",
                      difficulty_band=0.3, prereqs=[], origin=SkillOrigin.SEED,
                      created_at=now - timedelta(days=30)))
    session.add(Skill(id="calc1.new", course_id="calc1", name="New", description="d",
                      difficulty_band=0.4, prereqs=[], keywords=["k1"],
                      question_forms=["solve for x"], origin=SkillOrigin.GENERATED,
                      created_at=now))
    session.commit()

    ov = student_model_service.get_skills_overview(session, "calc1", "stu1")
    by_id = {s.skill_id: s for s in ov.skills}

    assert by_id["calc1.old"].origin == SkillOrigin.SEED
    assert by_id["calc1.old"].is_recent is False

    fresh = by_id["calc1.new"]
    assert fresh.origin == SkillOrigin.GENERATED
    assert fresh.is_recent is True
    assert fresh.keywords == ["k1"]
    assert fresh.question_forms == ["solve for x"]
