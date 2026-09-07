"""The voice HTTP boundary.

Same posture as the tutor boundary: audio is sniffed rather than trusted, an
unconfigured server refuses before a provider is reached, and no provider or
configuration detail is echoed back.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app.agents.workflow_errors import (
    TranscriptionWorkflowError,
    TranscriptionWorkflowTimeout,
)
from app.api.voice import MAX_AUDIO_BYTES, get_transcription_service
from app.main import app
from app.schemas.voice import MAX_TRANSCRIPT_CHARS
from app.services.transcription_service import TranscriptionService
from tests import factories as f


@pytest.fixture
def workflow():
    return f.StubTranscriptionWorkflow()


@pytest.fixture
def client(workflow, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    app.dependency_overrides[get_transcription_service] = lambda: TranscriptionService(
        workflow=workflow
    )
    yield TestClient(app)
    app.dependency_overrides.clear()


def post(client, *, audio=f.WAV, mime="audio/wav"):
    files = {"audio": ("speech.wav", audio, mime)} if audio is not None else {}
    return client.post("/api/voice/transcribe", files=files)


class TestHappyPath:
    def test_a_recording_comes_back_as_a_transcript(self, client):
        response = post(client)
        assert response.status_code == 200
        assert response.json() == {"transcript": "why can't I do this?"}

    def test_the_audio_reaches_the_workflow_as_wav(self, client, workflow):
        post(client)
        assert workflow.last_call["audio"] == f.WAV
        assert workflow.last_call["audio_mime_type"] == "audio/wav"

    def test_surrounding_whitespace_is_trimmed_before_it_leaves(self, client):
        app.dependency_overrides[get_transcription_service] = lambda: TranscriptionService(
            workflow=f.StubTranscriptionWorkflow(result="  why  is   this wrong?\n")
        )
        assert post(client).json()["transcript"] == "why is this wrong?"

    def test_an_over_long_transcript_is_truncated_rather_than_lost(self, client):
        # The student did say something; dropping the whole utterance is a
        # worse answer than dropping its tail.
        app.dependency_overrides[get_transcription_service] = lambda: TranscriptionService(
            workflow=f.StubTranscriptionWorkflow(result="a" * (MAX_TRANSCRIPT_CHARS + 500))
        )
        response = post(client)
        assert response.status_code == 200
        assert len(response.json()["transcript"]) == MAX_TRANSCRIPT_CHARS


class TestAudioHandling:
    def test_a_missing_recording_is_rejected(self, client):
        assert post(client, audio=None).status_code == 422

    def test_an_empty_recording_is_rejected(self, client):
        assert post(client, audio=b"").status_code == 400

    def test_a_non_audio_upload_is_rejected_on_its_content(self, client, workflow):
        # Declared audio/wav, actually a PDF. The declaration is not evidence.
        assert post(client, audio=f.NOT_AUDIO).status_code == 415
        assert workflow.calls == []

    def test_a_declared_type_that_contradicts_the_bytes_is_rejected(self, client):
        assert post(client, audio=f.WAV, mime="audio/webm").status_code == 415

    def test_a_riff_container_that_is_not_wave_is_rejected(self, client):
        assert post(client, audio=f.WEBP).status_code == 415

    def test_an_oversized_recording_is_rejected_before_it_reaches_a_provider(
        self, client, workflow
    ):
        oversized = f.WAV + b"\x00" * (5 * 1024 * 1024)
        assert post(client, audio=oversized).status_code == 413
        assert workflow.calls == []


class TestTheUploadBound:
    """The cap and the browser's longest recording have to agree.

    They are set in different languages in different repositories' halves, so
    each side pins the pair — see frontend/tests/wav.test.ts.
    """

    #: frontend/lib/voice/voiceCapture.ts MAX_RECORDING_MS, at WAV_SAMPLE_RATE.
    LONGEST_RECORDING_BYTES = 60 * 16_000 * 2 + 44

    def test_the_cap_admits_the_longest_recording_the_browser_can_make(self):
        assert self.LONGEST_RECORDING_BYTES < MAX_AUDIO_BYTES

    def test_a_recording_at_that_length_is_accepted(self, client):
        padded = f.WAV + b"\x00" * (self.LONGEST_RECORDING_BYTES - len(f.WAV))
        assert post(client, audio=padded).status_code == 200


class TestSilence:
    @pytest.mark.parametrize("said", ["", "   ", "\n\t "])
    def test_a_recording_with_no_words_in_it_is_refused(self, client, said):
        app.dependency_overrides[get_transcription_service] = lambda: TranscriptionService(
            workflow=f.StubTranscriptionWorkflow(result=said)
        )
        response = post(client)
        assert response.status_code == 422
        assert "speech" in response.json()["detail"].lower()


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


class TestProviderFailure:
    def _client(self, error, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY", "test-key")
        stub = f.StubTranscriptionWorkflow(error=error)
        app.dependency_overrides[get_transcription_service] = lambda: TranscriptionService(
            workflow=stub
        )
        return TestClient(app)

    def test_a_provider_failure_becomes_a_bad_gateway(self, monkeypatch):
        client = self._client(TranscriptionWorkflowError("upstream refused"), monkeypatch)
        assert post(client).status_code == 502
        app.dependency_overrides.clear()

    def test_a_timeout_is_distinguishable_from_a_failure(self, monkeypatch):
        client = self._client(TranscriptionWorkflowTimeout("took too long"), monkeypatch)
        assert post(client).status_code == 504
        app.dependency_overrides.clear()

    def test_a_provider_error_message_never_reaches_the_client(self, monkeypatch):
        client = self._client(
            TranscriptionWorkflowError("API key sk-abc123 was rejected"), monkeypatch
        )
        assert "sk-abc123" not in json.dumps(post(client).json())
        app.dependency_overrides.clear()
