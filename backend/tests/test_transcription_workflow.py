"""The speech-to-text provider adapter.

Everything here is about surviving the provider rather than about tutoring:
the upload/transcribe/delete round trip, and turning provider failures into
the two error types the API layer maps to status codes.

No test reaches a network. The provider client is replaced wholesale, which is
also what lets these assert on the *shape* of the call — a dedicated
transcription model takes no prompt, no response schema, and no thinking
budget, and passing one anyway is the regression this file exists to catch.
"""

from __future__ import annotations

import asyncio

import pytest

pytest.importorskip("google.genai", reason="provider adapter requires google-genai")

from app.agents import transcription_workflow as module  # noqa: E402
from app.agents.transcription_workflow import GeminiTranscriptionWorkflow  # noqa: E402
from app.agents.workflow_errors import (  # noqa: E402
    TranscriptionWorkflowError,
    TranscriptionWorkflowTimeout,
)
from tests import factories as f  # noqa: E402

pytestmark = pytest.mark.provider


# --- a provider that never leaves the process ------------------------------


class FakeFiles:
    def __init__(self, *, upload_error=None, delete_error=None):
        self._upload_error = upload_error
        self._delete_error = delete_error
        self.uploads: list[dict] = []
        self.deleted: list[str] = []

    async def upload(self, *, file, config):
        if self._upload_error is not None:
            raise self._upload_error
        self.uploads.append({"data": file.read(), "mime_type": config.mime_type})
        return _UploadedFile()

    async def delete(self, *, name):
        if self._delete_error is not None:
            raise self._delete_error
        self.deleted.append(name)


class _UploadedFile:
    name = "files/recording-1"
    uri = "https://generativelanguage.example/files/recording-1"
    mime_type = "audio/wav"


class FakeInteractions:
    def __init__(self, *, output_text="why can't I do this?", error=None):
        self._output_text = output_text
        self._error = error
        self.calls: list[dict] = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        if self._error is not None:
            raise self._error
        return _Interaction(self._output_text)


class _Interaction:
    def __init__(self, output_text):
        self.output_text = output_text


class FakeClient:
    def __init__(self, *, files: FakeFiles, interactions: FakeInteractions):
        self.files = files
        self.interactions = interactions

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


def provider(monkeypatch, *, files=None, interactions=None):
    """Install a fake provider and hand back the pieces to assert on."""
    fake = FakeClient(
        files=files or FakeFiles(),
        interactions=interactions or FakeInteractions(),
    )
    monkeypatch.setattr(module, "create_client", lambda api_key: _Holder(fake))
    return fake


class _Holder:
    """Mirrors `create_client(key).aio` without an SDK."""

    def __init__(self, client):
        self.aio = client


def workflow(**over) -> GeminiTranscriptionWorkflow:
    return GeminiTranscriptionWorkflow(
        api_key="test-key",
        model=over.get("model", "gemini-3.5-transcribe"),
        timeout_seconds=over.get("timeout_seconds", 5),
    )


def transcribe(work: GeminiTranscriptionWorkflow) -> str:
    return asyncio.run(work.run(audio=f.WAV, audio_mime_type="audio/wav"))


# --- the round trip --------------------------------------------------------


class TestTheTranscriptionCall:
    def test_the_recording_is_uploaded_before_it_is_transcribed(self, monkeypatch):
        fake = provider(monkeypatch)
        transcribe(workflow())
        assert fake.files.uploads == [{"data": f.WAV, "mime_type": "audio/wav"}]

    def test_the_interaction_points_at_the_uploaded_recording(self, monkeypatch):
        fake = provider(monkeypatch)
        transcribe(workflow())
        assert fake.interactions.calls[0]["input"] == [
            {
                "type": "audio",
                "uri": _UploadedFile.uri,
                "mime_type": _UploadedFile.mime_type,
            }
        ]

    def test_the_configured_model_is_the_one_asked(self, monkeypatch):
        fake = provider(monkeypatch)
        transcribe(workflow(model="gemini-3.5-transcribe-preview"))
        assert fake.interactions.calls[0]["model"] == "gemini-3.5-transcribe-preview"

    def test_the_transcript_is_read_from_the_documented_text_output(self, monkeypatch):
        provider(
            monkeypatch,
            interactions=FakeInteractions(output_text="is this less than or equal to zero?"),
        )
        assert transcribe(workflow()) == "is this less than or equal to zero?"

    @pytest.mark.parametrize(
        "unsupported",
        ["config", "generation_config", "response_schema", "thinking_config",
         "system_instruction", "response_mime_type"],
    )
    def test_nothing_the_transcription_model_rejects_is_sent(
        self, monkeypatch, unsupported
    ):
        # A transcription model does one job. The previous adapter targeted a
        # general multimodal model and asked for JSON with a thinking budget;
        # sending either here is a 400, not a slower answer.
        fake = provider(monkeypatch)
        transcribe(workflow())
        assert unsupported not in fake.interactions.calls[0]

    def test_silence_comes_back_as_words_the_service_can_reject(self, monkeypatch):
        # Empty is a legitimate answer; the service turns it into a 422.
        provider(monkeypatch, interactions=FakeInteractions(output_text=""))
        assert transcribe(workflow()) == ""


class TestCleanup:
    def test_the_uploaded_recording_is_deleted_once_transcribed(self, monkeypatch):
        fake = provider(monkeypatch)
        transcribe(workflow())
        assert fake.files.deleted == [_UploadedFile.name]

    def test_a_failed_transcription_still_takes_its_recording_with_it(self, monkeypatch):
        fake = provider(
            monkeypatch,
            interactions=FakeInteractions(error=RuntimeError("upstream refused")),
        )
        with pytest.raises(TranscriptionWorkflowError):
            transcribe(workflow())
        assert fake.files.deleted == [_UploadedFile.name]

    def test_a_timeout_still_takes_its_recording_with_it(self, monkeypatch):
        # The delete is awaited after the timeout scope has closed, which is
        # the only reason it can run at all on this path.
        async def never(**kwargs):
            await asyncio.sleep(3600)

        interactions = FakeInteractions()
        interactions.create = never
        fake = provider(monkeypatch, interactions=interactions)
        with pytest.raises(TranscriptionWorkflowTimeout):
            transcribe(workflow(timeout_seconds=0.01))
        assert fake.files.deleted == [_UploadedFile.name]

    def test_a_failed_delete_does_not_cost_the_student_their_answer(self, monkeypatch):
        provider(
            monkeypatch,
            files=FakeFiles(delete_error=RuntimeError("delete refused")),
        )
        assert transcribe(workflow()) == "why can't I do this?"

    def test_nothing_is_deleted_when_the_upload_never_landed(self, monkeypatch):
        fake = provider(
            monkeypatch, files=FakeFiles(upload_error=RuntimeError("upload refused"))
        )
        with pytest.raises(TranscriptionWorkflowError):
            transcribe(workflow())
        assert fake.files.deleted == []


class TestFailureTranslation:
    def test_a_timeout_raises_a_timeout(self, monkeypatch):
        async def never(**kwargs):
            await asyncio.sleep(3600)

        interactions = FakeInteractions()
        interactions.create = never
        provider(monkeypatch, interactions=interactions)
        with pytest.raises(TranscriptionWorkflowTimeout):
            transcribe(workflow(timeout_seconds=0.01))

    def test_a_provider_exception_is_wrapped(self, monkeypatch):
        provider(
            monkeypatch,
            interactions=FakeInteractions(error=RuntimeError("connection reset")),
        )
        with pytest.raises(TranscriptionWorkflowError):
            transcribe(workflow())

    def test_a_provider_exception_message_is_not_re_raised_verbatim(self, monkeypatch):
        provider(
            monkeypatch,
            interactions=FakeInteractions(error=RuntimeError("key sk-live-999 rejected")),
        )
        with pytest.raises(TranscriptionWorkflowError) as caught:
            transcribe(workflow())
        assert "sk-live-999" not in str(caught.value)

    def test_a_response_without_text_is_unreadable_rather_than_empty(self, monkeypatch):
        # Provider output is not trusted to honour its own contract; "" and
        # "no text at all" are different answers.
        provider(monkeypatch, interactions=FakeInteractions(output_text=None))
        with pytest.raises(TranscriptionWorkflowError):
            transcribe(workflow())
