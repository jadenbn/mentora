"""The dev-only dashboard page and skills-import endpoint."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app


def test_dashboard_serves_html():
    with TestClient(app) as client:
        response = client.get("/dev/dashboard")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "Dev Dashboard" in response.text


def test_import_skills_persists_a_generated_batch():
    with TestClient(app) as client:
        response = client.post(
            "/dev/courses/calc1/skills/import",
            json={
                "skills": [
                    {
                        "id": "imported-skill",
                        "name": "Imported",
                        "description": "via dev endpoint",
                        "difficulty_band": 0.3,
                        "prereqs": [],
                        "keywords": ["k1"],
                        "question_forms": ["q1"],
                    }
                ]
            },
        )
        assert response.status_code == 200
        assert response.json() == {
            "added": ["calc1.imported-skill"],
            "updated": [],
            "blocked_seed_collisions": [],
        }

        overview = client.get(
            "/api/courses/calc1/skills-overview", params={"student_id": "dev"}
        ).json()
    imported = next(
        s for s in overview["skills"] if s["skill_id"] == "calc1.imported-skill"
    )
    assert imported["origin"] == "generated"
    assert imported["is_recent"] is True
    assert imported["keywords"] == ["k1"]


def test_import_skills_blocks_a_seed_collision():
    with TestClient(app) as client:
        response = client.post(
            "/dev/courses/calc1/skills/import",
            json={
                "skills": [
                    {
                        "id": "limits.evaluation",  # collides with a seeded calc1 skill
                        "name": "Overwrite attempt",
                        "description": "x",
                        "difficulty_band": 0.9,
                        "prereqs": [],
                    }
                ]
            },
        )
    assert response.status_code == 200
    body = response.json()
    assert body["added"] == []
    assert body["blocked_seed_collisions"] == ["calc1.limits.evaluation"]


def test_import_skills_rejects_an_invalid_taxonomy():
    with TestClient(app) as client:
        response = client.post(
            "/dev/courses/calc1/skills/import",
            json={
                "skills": [
                    {
                        "id": "a",
                        "name": "A",
                        "description": "d",
                        "difficulty_band": 0.5,
                        "prereqs": ["nowhere"],
                    }
                ]
            },
        )
    assert response.status_code == 400
