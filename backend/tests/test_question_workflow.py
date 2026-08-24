from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

pytest.importorskip("google.genai", reason="provider adapter requires google-genai")

from app.agents.question_workflow import (  # noqa: E402
    QUESTION_PLAN_RESPONSE_SCHEMA,
    GeminiQuestionWorkflow,
)
from app.agents.workflow_errors import QuestionWorkflowError  # noqa: E402
from app.schemas.problems import GroundingChunk  # noqa: E402

pytestmark = pytest.mark.provider

CHUNKS = [GroundingChunk(chunk_id="chunk_1", page=1, text="The chain rule applies.")]


class Harness(GeminiQuestionWorkflow):
    def __init__(self, responses):
        super().__init__(api_key="test-key", model="test", timeout_seconds=1)
        self.responses = iter(responses)
        self.attempts = 0

    async def _request(self, **_kwargs):
        self.attempts += 1
        return next(self.responses)


def test_an_invented_chunk_id_gets_one_repair_attempt():
    workflow = Harness([
        {"prompt": "Question", "grounding_chunk_ids": ["invented"]},
        {"prompt": "Question", "grounding_chunk_ids": ["chunk_1"]},
    ])
    result = asyncio.run(workflow.run(chunks=CHUNKS, question_request="Conceptual"))
    assert result.grounding_chunk_ids == ["chunk_1"]
    assert workflow.attempts == 2


def test_persistently_invalid_source_ids_fail_closed():
    workflow = Harness([
        {"prompt": "Question", "grounding_chunk_ids": ["invented"]},
        {"prompt": "Question", "grounding_chunk_ids": ["still_invented"]},
    ])
    with pytest.raises(QuestionWorkflowError):
        asyncio.run(workflow.run(chunks=CHUNKS, question_request="Conceptual"))
    assert workflow.attempts == 2


def test_direct_request_sends_grounding_and_schema_configuration():
    calls: list[dict] = []

    class Models:
        async def generate_content(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(
                parsed={
                    "prompt": "Differentiate $x^2$.",
                    "grounding_chunk_ids": ["chunk_1"],
                },
                text=None,
            )

    class AsyncClient:
        models = Models()

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

    workflow = GeminiQuestionWorkflow(
        api_key="test-key",
        model="test-model",
        timeout_seconds=1,
    )
    workflow._client = lambda: SimpleNamespace(aio=AsyncClient())
    asyncio.run(workflow.run(chunks=CHUNKS, question_request="Conceptual chain rule"))

    call = calls[0]
    prompt = call["contents"].parts[0].text
    assert "Conceptual chain rule" in prompt
    assert "chunk_1" in prompt
    assert call["config"].response_schema == QUESTION_PLAN_RESPONSE_SCHEMA
    assert "dollar-delimited LaTeX" in call["config"].system_instruction
