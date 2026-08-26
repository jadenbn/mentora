"""The dev dashboard's overview query: every topic, accuracy, origin, recency."""

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
    session.add(Skill(id="calc1.a", course_id="calc1", name="A", description="d",
                      difficulty_band=0.3))
    session.add(Skill(id="calc1.b", course_id="calc1", name="B", description="d",
                      difficulty_band=0.5))
    session.commit()


def test_overview_lists_every_topic_including_untouched(session):
    _seed(session)
    ov = student_model_service.get_skills_overview(session, "calc1", "stu1")
    ids = {s.skill_id for s in ov.skills}
    assert ids == {"calc1.a", "calc1.b"}
    for s in ov.skills:
        assert s.has_signal is False
        assert s.attempts == 0
        assert s.accuracy is None


def test_overview_reflects_recorded_attempts(session):
    _seed(session)
    for i in range(3):
        student_model_service.record_attempt(
            session, "calc1",
            AttemptCreate(student_id="stu1", session_id="s", problem_id=f"p{i}",
                          expected_skills=["calc1.a"], difficulty=0.3, correct=True),
        )
    ov = student_model_service.get_skills_overview(session, "calc1", "stu1")
    by_id = {s.skill_id: s for s in ov.skills}

    assert by_id["calc1.a"].accuracy == pytest.approx(1.0)
    assert by_id["calc1.a"].attempts == 3
    assert by_id["calc1.a"].has_signal is True
    assert by_id["calc1.b"].accuracy is None


def test_overview_exposes_origin_keywords_and_recency(session):
    now = datetime.now(timezone.utc)
    session.add(Skill(id="calc1.old", course_id="calc1", name="Old", description="d",
                      difficulty_band=0.3, origin=SkillOrigin.SEED,
                      created_at=now - timedelta(days=30)))
    session.add(Skill(id="calc1.new", course_id="calc1", name="New", description="d",
                      difficulty_band=0.4, keywords=["k1"],
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
