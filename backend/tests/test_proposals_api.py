"""The dev proposals surface: list, review, and the dashboard panel."""

from fastapi.testclient import TestClient
from app.main import app
from app.db import engine
from sqlmodel import Session
from app.models.skill_proposal import SkillProposal

def test_proposals_endpoints_round_trip():
    with Session(engine) as s:
        s.add(SkillProposal(course_id="calc1", slug="calc1.gap", name="Gap",
                            description="a real gap", difficulty_band=0.4, observations=3))
        s.commit()
    with TestClient(app) as c:
        listed = c.get("/dev/courses/calc1/proposals").json()
        assert listed["proposals"][0]["slug"] == "calc1.gap"
        assert listed["min_observations"] == 3
        r = c.post("/dev/courses/calc1/proposals/review").json()
        assert r["promoted"] == ["calc1.gap"], r
        after = c.get("/dev/courses/calc1/proposals").json()
        assert after["proposals"][0]["status"] == "promoted"
        page = c.get("/dev/dashboard")
        assert "Skill proposals" in page.text
