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


def test_next_topic_previews_the_pick_without_serving_it():
    """The dashboard's window onto selection. Read-only: looking at the
    answer must not change it, or the dashboard would be driving the engine
    it is there to observe."""
    with TestClient(app) as client:
        first = client.get(
            "/dev/courses/calc1/next-topic", params={"student_id": "dev-1"}
        )
        second = client.get(
            "/dev/courses/calc1/next-topic", params={"student_id": "dev-1"}
        )
    assert first.status_code == 200
    assert first.json()["skill_id"] == second.json()["skill_id"]


def test_next_topic_is_404_for_a_course_with_no_topics():
    with TestClient(app) as client:
        response = client.get(
            "/dev/courses/nope/next-topic", params={"student_id": "dev-1"}
        )
    assert response.status_code == 404


def test_simulate_reports_on_the_policy_without_touching_the_database():
    with TestClient(app) as client:
        response = client.post(
            "/dev/courses/calc1/simulate",
            params={"students": 3, "questions_each": 6},
        )
        assert response.status_code == 200
        report = response.json()
        assert 0.0 < report["coverage"] <= 1.0
        assert report["students"] == 3

        # No synthetic student reached the real student model.
        overview = client.get(
            "/api/courses/calc1/skills-overview", params={"student_id": "sim-0"}
        ).json()
        assert all(s["attempts"] == 0 for s in overview["skills"])


def test_a_synthetic_attempt_also_marks_the_topic_served():
    """The dashboard has to show selection behaving as it does in production.

    On the real path a topic is served by generation before it is ever
    marked, so the recency penalty fires. A dev attempt that recorded
    without serving would let the dashboard hand back the same topic
    forever, which is not what a student would see.
    """
    with TestClient(app) as client:
        first = client.get(
            "/dev/courses/calc1/next-topic", params={"student_id": "dev-2"}
        ).json()["skill_id"]
        client.post(
            "/dev/courses/calc1/attempts",
            json={
                "student_id": "dev-2", "session_id": "dev", "problem_id": "d1",
                "expected_skills": [first], "difficulty": 0.5, "correct": False,
            },
        )
        second = client.get(
            "/dev/courses/calc1/next-topic", params={"student_id": "dev-2"}
        ).json()["skill_id"]
    assert second != first
