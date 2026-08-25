from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

pytest.importorskip("google.genai", reason="provider adapter requires google-genai")

from app.agents.taxonomy_workflow import (  # noqa: E402
    TAXONOMY_PLAN_RESPONSE_SCHEMA,
    GeminiTaxonomyWorkflow,
)
from app.agents.workflow_errors import TaxonomyWorkflowError  # noqa: E402

pytestmark = pytest.mark.provider

VALID_SKILL = {
    "id": "chain-rule",
    "name": "Chain rule",
    "description": "Differentiate a composite function.",
    "difficulty_band": 0.5,
    "prereqs": [],
    "keywords": ["composite function"],
    "question_forms": ["differentiate a nested expression"],
}


class Harness(GeminiTaxonomyWorkflow):
    def __init__(self, responses):
        super().__init__(api_key="test-key", model="test", timeout_seconds=1)
        self.responses = iter(responses)
        self.attempts = 0

    async def _request(self, **_kwargs):
        self.attempts += 1
        return next(self.responses)


def test_persistently_invalid_output_fails_closed():
    # Shape violation: difficulty_band outside [0, 1]. Graph-level rules
    # (unresolved prereqs, cycles) are no longer checked here -- they are
    # enforced once, in services.taxonomy.build_taxonomy, against the whole
    # course rather than one batch's private view of it.
    broken = {**VALID_SKILL, "id": "s1", "difficulty_band": 4.2}
    workflow = Harness([{"skills": [broken]}, {"skills": [broken]}])
    with pytest.raises(TaxonomyWorkflowError):
        asyncio.run(workflow.run(source_text="text"))
    assert workflow.attempts == 2


def test_prereqs_naming_existing_skills_pass_through_unchanged():
    entry = {**VALID_SKILL, "id": "s1", "prereqs": ["calc1.limits.evaluation"]}
    workflow = Harness([{"skills": [entry]}])
    result = asyncio.run(
        workflow.run(
            source_text="text",
            existing_skills=[{"id": "calc1.limits.evaluation", "name": "Limits"}],
        )
    )
    assert result[0]["prereqs"] == ["calc1.limits.evaluation"]
    assert workflow.attempts == 1


def test_direct_request_sends_source_text_and_schema_configuration():
    calls: list[dict] = []

    class Models:
        async def generate_content(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(parsed={"skills": [VALID_SKILL]}, text=None)

    class AsyncClient:
        models = Models()

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

    workflow = GeminiTaxonomyWorkflow(api_key="test-key", model="test-model", timeout_seconds=1)
    workflow._client = lambda: SimpleNamespace(aio=AsyncClient())
    asyncio.run(workflow.run(source_text="Derivatives of composite functions."))

    call = calls[0]
    prompt = call["contents"].parts[0].text
    assert "Derivatives of composite functions" in prompt
    assert call["config"].response_schema == TAXONOMY_PLAN_RESPONSE_SCHEMA
    assert "prerequisite graph" in call["config"].system_instruction


def test_emergent_flag_selects_the_single_skill_instruction():
    calls: list[dict] = []

    class Models:
        async def generate_content(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(parsed={"skills": [VALID_SKILL]}, text=None)

    class AsyncClient:
        models = Models()

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

    workflow = GeminiTaxonomyWorkflow(api_key="test-key", model="test-model", timeout_seconds=1)
    workflow._client = lambda: SimpleNamespace(aio=AsyncClient())
    asyncio.run(
        workflow.run(
            source_text="excerpt",
            existing_skills=[{"id": "calc1.a", "name": "A"}],
            emergent=True,
        )
    )
    assert "exactly one" in calls[0]["config"].system_instruction
    assert "calc1.a" in calls[0]["contents"].parts[0].text
