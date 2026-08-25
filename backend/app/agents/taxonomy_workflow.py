"""Direct Gemini adapter for proposing a course's skill taxonomy.

Mirrors agents/question_workflow.py: structured output, one repair retry on
a malformed response, a hard timeout. Returns plain skill dicts — it does
not build Skill rows or validate against the full course graph. That is
app.services.taxonomy.build_taxonomy's job (agents does not depend on
services), run downstream by the caller against every existing skill, not
just this batch.

What this workflow *does* check before returning, so a same-batch structural
problem gets Gemini's own repair pass rather than surfacing as a service
failure: ids unique within the batch, every prereq resolves to either a
batch id or a caller-supplied existing id, and the batch's own prereq graph
has no cycle. It cannot see prereqs on existing skills, so it cannot detect a
cycle that spans the existing graph — that is caught downstream.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from google import genai
from google.genai import types
from pydantic import ValidationError

from app.agents.workflow_errors import TaxonomyWorkflowError, TaxonomyWorkflowTimeout
from app.prompts.taxonomy_generation import (
    EMERGENT_SKILL_INSTRUCTION,
    TAXONOMY_INSTRUCTION,
)
from app.schemas.taxonomy import RawSkillEntry, TaxonomyPlan

logger = logging.getLogger(__name__)

_SKILL_ENTRY_SCHEMA = {
    "type": "object",
    "properties": {
        "id": {"type": "string"},
        "name": {"type": "string"},
        "description": {"type": "string"},
        "difficulty_band": {"type": "number", "minimum": 0, "maximum": 1},
        "prereqs": {"type": "array", "items": {"type": "string"}},
        "keywords": {
            "type": "array",
            "items": {"type": "string", "maxLength": 80},
        },
        "question_forms": {
            "type": "array",
            "items": {"type": "string", "maxLength": 80},
        },
    },
    "required": ["id", "name", "description", "difficulty_band"],
}

TAXONOMY_PLAN_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "skills": {"type": "array", "items": _SKILL_ENTRY_SCHEMA},
    },
    "required": ["skills"],
}


def _find_cycle(entries: list[RawSkillEntry]) -> str | None:
    """DFS over one batch's own prereq edges. Returns a description or None.

    Only edges between ids present in this batch are checked — a prereq
    pointing outside the batch (at an existing course skill) cannot
    participate in a same-batch cycle by construction.
    """
    by_id = {entry.id: entry for entry in entries}
    WHITE, GRAY, BLACK = 0, 1, 2
    state = {entry.id: WHITE for entry in entries}

    def visit(skill_id: str, path: list[str]) -> str | None:
        state[skill_id] = GRAY
        for prereq_id in by_id[skill_id].prereqs:
            if prereq_id not in by_id:
                continue
            if state[prereq_id] == GRAY:
                return " -> ".join(path + [prereq_id])
            if state[prereq_id] == WHITE:
                found = visit(prereq_id, path + [prereq_id])
                if found:
                    return found
        state[skill_id] = BLACK
        return None

    for entry in entries:
        if state[entry.id] == WHITE:
            found = visit(entry.id, [entry.id])
            if found:
                return found
    return None


def _validate_batch(plan: TaxonomyPlan, known_ids: set[str]) -> None:
    """Raise ValueError on any batch-local structural problem."""
    seen: set[str] = set()
    for entry in plan.skills:
        if entry.id in seen:
            raise ValueError(f"duplicate skill id in batch: {entry.id}")
        seen.add(entry.id)

    resolvable = seen | known_ids
    for entry in plan.skills:
        unresolved = [p for p in entry.prereqs if p not in resolvable]
        if unresolved:
            raise ValueError(
                f"{entry.id}: prereq(s) resolve nowhere: {unresolved}"
            )

    cycle = _find_cycle(plan.skills)
    if cycle:
        raise ValueError(f"prerequisite cycle detected: {cycle}")


class GeminiTaxonomyWorkflow:
    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        timeout_seconds: float = 45,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.timeout_seconds = timeout_seconds

    def _client(self) -> genai.Client:
        return genai.Client(
            api_key=self.api_key,
            http_options=types.HttpOptions(
                retry_options=types.HttpRetryOptions(
                    attempts=3,
                    initial_delay=0.5,
                    max_delay=4,
                    exp_base=2,
                    jitter=0.2,
                    http_status_codes=[408, 500, 502, 503, 504],
                )
            ),
        )

    async def run(
        self,
        *,
        source_text: str,
        existing_skills: list[dict[str, str]] | None = None,
        emergent: bool = False,
    ) -> list[dict]:
        """Propose skills from source_text.

        existing_skills: [{"id": ..., "name": ...}, ...] already in the
        course, offered as prereq targets and (for emergent=True) as the
        "don't duplicate this" context. emergent=True asks for exactly one
        new skill filling a gap rather than a full-course taxonomy.
        """
        known_ids = {s["id"] for s in (existing_skills or [])}
        malformed: Exception | None = None
        previous_error: str | None = None
        try:
            async with self._client().aio as client:
                for attempt in range(2):
                    try:
                        raw = await self._request(
                            client=client,
                            source_text=source_text,
                            existing_skills=existing_skills or [],
                            emergent=emergent,
                            previous_error=previous_error,
                        )
                        plan = TaxonomyPlan.model_validate(raw)
                        _validate_batch(plan, known_ids)
                        return [entry.model_dump(mode="json") for entry in plan.skills]
                    except (ValidationError, ValueError, KeyError, TypeError) as exc:
                        malformed = exc
                        previous_error = str(exc)
                        logger.warning(
                            "taxonomy output failed validation (attempt %d): %s",
                            attempt + 1,
                            exc,
                        )
        except (TimeoutError, asyncio.TimeoutError) as exc:
            raise TaxonomyWorkflowTimeout("taxonomy generation timed out") from exc
        except Exception:
            logger.exception("taxonomy provider request failed")
            raise TaxonomyWorkflowError("taxonomy generation failed") from None
        raise TaxonomyWorkflowError(
            "taxonomy generation returned malformed output"
        ) from malformed

    async def _request(
        self,
        *,
        client: Any,
        source_text: str,
        existing_skills: list[dict[str, str]],
        emergent: bool,
        previous_error: str | None,
    ) -> dict:
        # Echo back exactly what failed, not a generic reminder — a canned
        # "check ids and cycles" hint is useless (and was actively
        # misleading) when the real problem was e.g. difficulty_band out of
        # [0, 1]; the model needs the actual validation error to fix it.
        prefix = (
            f"Repair attempt: the previous response was rejected with this "
            f"error — fix it exactly: {previous_error}\n\n"
            if previous_error
            else ""
        )
        known = "\n".join(f"- {s['id']}: {s['name']}" for s in existing_skills)
        known_block = (
            f"<existing-skills>\n{known}\n</existing-skills>\n\n" if known else ""
        )
        message = types.Content(
            role="user",
            parts=[
                types.Part.from_text(
                    text=(
                        f"{prefix}{known_block}<course-material>\n"
                        f"{source_text}\n</course-material>"
                    )
                )
            ],
        )
        instruction = EMERGENT_SKILL_INSTRUCTION if emergent else TAXONOMY_INSTRUCTION
        async with asyncio.timeout(self.timeout_seconds):
            response = await client.models.generate_content(
                model=self.model,
                contents=message,
                config=types.GenerateContentConfig(
                    system_instruction=instruction,
                    response_mime_type="application/json",
                    response_schema=TAXONOMY_PLAN_RESPONSE_SCHEMA,
                    max_output_tokens=8_192,
                    temperature=0.4,
                    thinking_config=types.ThinkingConfig(
                        thinking_level=types.ThinkingLevel.LOW
                    ),
                ),
            )

        parsed = response.parsed
        if isinstance(parsed, dict):
            return parsed
        text = response.text
        if not text:
            raise ValueError("provider returned no structured taxonomy plan")
        loaded = json.loads(text)
        if not isinstance(loaded, dict):
            raise ValueError("provider taxonomy plan was not an object")
        return loaded
