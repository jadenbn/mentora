"""Direct Gemini adapter for one validated, source-grounded question.

Also attributes the question to the skill(s) it exercises, in the same call
— no second round trip. A skill entry either names an existing course skill
by id or names a new one; either way, app.services.question_service resolves
it against the course's topic list (existing, name-similarity match, or
newly appended) -- see QuestionService._attribute_skills.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from google.genai import types
from pydantic import ValidationError

from app.agents.gemini import create_client, response_object
from app.schemas.taxonomy import SKILL_ENTRY_SCHEMA
from app.agents.workflow_errors import QuestionWorkflowError, QuestionWorkflowTimeout
from app.prompts.question_generation import QUESTION_INSTRUCTION
from app.schemas.problems import GroundingChunk, QuestionPlan

logger = logging.getLogger(__name__)

QUESTION_PLAN_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "prompt": {"type": "string"},
        "grounding_chunk_ids": {
            "type": "array",
            "items": {"type": "string"},
        },
        "skills": {
            "type": "array",
            "items": SKILL_ENTRY_SCHEMA,
        },
    },
    "required": ["prompt", "grounding_chunk_ids", "skills"],
}


class GeminiQuestionWorkflow:
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

    async def run(
        self,
        *,
        chunks: list[GroundingChunk],
        question_request: str,
        difficulty_word: str | None = None,
        existing_skills: list[dict[str, str]] | None = None,
    ) -> QuestionPlan:
        """difficulty_word: the engine's preferred level, sent in its own
        block rather than inside the request, so the model can tell a
        preference from the instruction it must honour.

        existing_skills: [{"id": ..., "name": ...}, ...] already in the
        course, offered as skill-attribution targets so the model reuses an
        id instead of proposing a near-duplicate."""
        allowed = {chunk.chunk_id for chunk in chunks}
        malformed: Exception | None = None
        previous_error: str | None = None
        try:
            async with create_client(self.api_key).aio as client:
                for attempt in range(2):
                    try:
                        raw = await self._request(
                            client=client,
                            chunks=chunks,
                            question_request=question_request,
                            difficulty_word=difficulty_word,
                            existing_skills=existing_skills or [],
                            previous_error=previous_error,
                        )
                        plan = QuestionPlan.model_validate(raw)
                        if len(set(plan.grounding_chunk_ids)) != len(
                            plan.grounding_chunk_ids
                        ):
                            raise ValueError("grounding chunk IDs must be unique")
                        if any(
                            chunk_id not in allowed
                            for chunk_id in plan.grounding_chunk_ids
                        ):
                            raise ValueError("grounding chunk ID was not supplied")
                        return plan
                    except (ValidationError, ValueError, KeyError, TypeError) as exc:
                        malformed = exc
                        previous_error = str(exc)
                        logger.warning(
                            "question output failed validation (attempt %d): %s",
                            attempt + 1,
                            exc,
                        )
        except (TimeoutError, asyncio.TimeoutError) as exc:
            raise QuestionWorkflowTimeout("question generation timed out") from exc
        except Exception:
            logger.exception("question provider request failed")
            raise QuestionWorkflowError("question generation failed") from None
        raise QuestionWorkflowError(
            "question generation returned malformed output"
        ) from malformed

    async def _request(
        self,
        *,
        client: Any,
        chunks: list[GroundingChunk],
        question_request: str,
        difficulty_word: str | None,
        existing_skills: list[dict[str, str]],
        previous_error: str | None,
    ) -> dict:
        # Echo back exactly what failed, not a generic reminder — a canned
        # "use only the exact chunk IDs below" hint is useless when the real
        # problem was e.g. a duplicate skill id or an out-of-range
        # difficulty_band; the model needs the actual validation error.
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
        difficulty_block = (
            f"<preferred-difficulty>{difficulty_word}</preferred-difficulty>\n\n"
            if difficulty_word
            else ""
        )
        excerpts = "\n\n".join(
            f"<course-excerpt id=\"{chunk.chunk_id}\" page=\"{chunk.page}\">\n"
            f"{chunk.text}\n</course-excerpt>"
            for chunk in chunks
        )
        message = types.Content(
            role="user",
            parts=[
                types.Part.from_text(
                    text=(
                        f"{prefix}<question-request-json>\n"
                        f"{json.dumps(question_request)}\n"
                        f"</question-request-json>\n\n"
                        f"{difficulty_block}{known_block}{excerpts}"
                    )
                )
            ],
        )
        async with asyncio.timeout(self.timeout_seconds):
            response = await client.models.generate_content(
                model=self.model,
                contents=message,
                config=types.GenerateContentConfig(
                    system_instruction=QUESTION_INSTRUCTION,
                    response_mime_type="application/json",
                    response_schema=QUESTION_PLAN_RESPONSE_SCHEMA,
                    max_output_tokens=6_144,
                    temperature=0.7,
                    thinking_config=types.ThinkingConfig(
                        thinking_level=types.ThinkingLevel.LOW
                    ),
                ),
            )

        return response_object(response)
