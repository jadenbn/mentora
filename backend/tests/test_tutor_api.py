"""The HTTP boundary.

Everything crossing it is hostile until proven otherwise: image bytes are
sniffed rather than trusted, and no provider or configuration detail is ever
echoed back to the caller.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app.agents.workflow_errors import TutorWorkflowError, TutorWorkflowTimeout
from app.api.tutor import get_tutor_service
from app.main import app
from app.services.tutor_service import TutorService
from tests import factories as f


@pytest.fixture
def workflow():
    return f.StubWorkflow()


@pytest.fixture
def client(workflow, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    app.dependency_overrides[get_tutor_service] = lambda: TutorService(workflow=workflow)
    yield TestClient(app)
    app.dependency_overrides.clear()


def post(client, *, image=f.PNG, mime="image/png", **over):
    data = {"room_id": "room_demo", "mode": "hint"}
    data.update({k: v for k, v in over.items() if v is not None})
    files = {"canvas_image": ("canvas.png", image, mime)} if image is not None else {}
    return client.post("/api/tutor/analyze", data=data, files=files)


class TestHappyPath:
    def test_a_valid_request_returns_a_tutor_response(self, client):
        response = post(client)
        assert response.status_code == 200
        body = response.json()
        assert set(body) == {"interaction_id", "status", "canvas_actions", "summary"}

    def test_the_mode_is_forwarded_to_the_workflow(self, client, workflow):
        post(client, mode="explain")
        assert workflow.last_call["mode"].value == "explain"

    def test_prior_annotations_are_parsed_and_forwarded(self, client, workflow):
        prior = [f.bounds(), f.bounds(x=0.6)]
        post(client, prior_annotations=json.dumps(prior))
        assert len(workflow.last_call["prior_annotations"]) == 2

    def test_prior_annotations_default_to_empty(self, client, workflow):
        post(client)
        assert workflow.last_call["prior_annotations"] == []

    @pytest.mark.parametrize("image,mime", [(f.PNG, "image/png"), (f.JPEG, "image/jpeg"), (f.WEBP, "image/webp")])
    def test_every_supported_image_format_is_accepted(self, client, image, mime):
        assert post(client, image=image, mime=mime).status_code == 200


class TestRequestValidation:
    def test_an_unknown_mode_is_rejected(self, client):
        assert post(client, mode="roast").status_code == 422

    def test_a_missing_room_id_is_rejected(self, client):
        response = client.post(
            "/api/tutor/analyze",
            data={"mode": "hint"},
            files={"canvas_image": ("c.png", f.PNG, "image/png")},
        )
        assert response.status_code == 422

    def test_a_missing_image_is_rejected(self, client):
        assert post(client, image=None).status_code == 422

    def test_malformed_prior_annotations_are_rejected(self, client):
        assert post(client, prior_annotations="not json").status_code == 422

    def test_prior_annotations_outside_the_canvas_are_rejected(self, client):
        off_canvas = json.dumps([{"x": 0.9, "y": 0.1, "width": 0.5, "height": 0.1}])
        assert post(client, prior_annotations=off_canvas).status_code == 422


class TestImageHandling:
    def test_an_empty_upload_is_rejected(self, client):
        assert post(client, image=b"").status_code == 400

    def test_a_non_image_upload_is_rejected_on_its_content(self, client):
        # Declared image/png, actually a PDF. The declaration is not evidence.
        assert post(client, image=f.NOT_AN_IMAGE, mime="image/png").status_code == 415

    def test_a_declared_type_that_contradicts_the_bytes_is_rejected(self, client):
        assert post(client, image=f.PNG, mime="image/jpeg").status_code == 415

    def test_an_oversized_image_is_rejected_before_it_reaches_a_provider(self, client, workflow):
        oversized = f.PNG + b"\x00" * (10 * 1024 * 1024)
        assert post(client, image=oversized).status_code == 413
        assert workflow.calls == []


class TestConfiguration:
    def test_an_unconfigured_server_reports_not_ready(self, monkeypatch):
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        with TestClient(app) as bare:
            response = post(bare)
        assert response.status_code == 503
        assert "GEMINI_API_KEY" in json.dumps(response.json())

    def test_configuration_errors_never_disclose_a_secret(self, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY", "super-secret-value")
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        with TestClient(app) as bare:
            body = json.dumps(post(bare).json())
        assert "super-secret-value" not in body

    def test_health_reports_readiness_without_naming_values(self, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY", "super-secret-value")
        with TestClient(app) as ready:
            body = ready.get("/health").json()
        assert body["status"] == "ok"
        assert "super-secret-value" not in json.dumps(body)


class TestProviderFailure:
    def _client(self, error, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY", "test-key")
        stub = f.StubWorkflow(error=error)
        app.dependency_overrides[get_tutor_service] = lambda: TutorService(workflow=stub)
        return TestClient(app)

    def test_a_provider_failure_becomes_a_bad_gateway(self, monkeypatch):
        client = self._client(TutorWorkflowError("upstream refused"), monkeypatch)
        assert post(client).status_code == 502
        app.dependency_overrides.clear()

    def test_a_timeout_is_distinguishable_from_a_failure(self, monkeypatch):
        client = self._client(TutorWorkflowTimeout("took too long"), monkeypatch)
        assert post(client).status_code == 504
        app.dependency_overrides.clear()

    def test_a_provider_error_message_never_reaches_the_client(self, monkeypatch):
        client = self._client(TutorWorkflowError("API key sk-abc123 was rejected"), monkeypatch)
        assert "sk-abc123" not in json.dumps(post(client).json())
        app.dependency_overrides.clear()
