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


def test_import_skills_persists_a_new_topic():
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
                        "keywords": ["k1"],
                        "question_forms": ["q1"],
                    }
                ]
            },
        )
        assert response.status_code == 200
        assert response.json() == {"added": ["calc1.imported-skill"], "skipped": []}

        overview = client.get(
            "/api/courses/calc1/skills-overview", params={"student_id": "dev"}
        ).json()
    imported = next(
        s for s in overview["skills"] if s["skill_id"] == "calc1.imported-skill"
    )
    assert imported["origin"] == "generated"
    assert imported["is_recent"] is True
    assert imported["keywords"] == ["k1"]


def test_import_skills_skips_an_id_that_already_exists():
    with TestClient(app) as client:
        response = client.post(
            "/dev/courses/calc1/skills/import",
            json={
                "skills": [
                    {
                        "id": "derivatives.power-rule",  # already in the calc1 seed file
                        "name": "Overwrite attempt",
                        "description": "x",
                        "difficulty_band": 0.9,
                    }
                ]
            },
        )
    assert response.status_code == 200
    assert response.json() == {"added": [], "skipped": ["calc1.derivatives.power-rule"]}


def test_import_skills_rejects_a_batch_that_collides_after_normalization():
    with TestClient(app) as client:
        response = client.post(
            "/dev/courses/calc1/skills/import",
            json={
                "skills": [
                    {"id": "same-name", "name": "A", "description": "d", "difficulty_band": 0.5},
                    {"id": "same-name", "name": "B", "description": "d", "difficulty_band": 0.5},
                ]
            },
        )
    assert response.status_code == 400


def test_import_skills_rejects_an_unknown_field():
    """prereqs is gone -- topics are flat -- so a batch that still sends it
    should fail shape validation rather than being silently accepted."""
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
    assert response.status_code == 422
