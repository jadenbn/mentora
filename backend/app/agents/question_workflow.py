"""Direct Gemini adapter for one validated, source-grounded question."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from google import genai
from google.genai import types
from pydantic import BaseModel, ValidationError

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
    },
    "required": ["prompt", "grounding_chunk_ids"],
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
        self, *, chunks: list[GroundingChunk], question_request: str
    ) -> QuestionPlan:
        allowed = {chunk.chunk_id for chunk in chunks}
        malformed: Exception | None = None
        try:
            async with self._client().aio as client:
                for attempt in range(2):
                    try:
                        raw = await self._request(
                            client=client,
                            chunks=chunks,
                            question_request=question_request,
                            repair=attempt == 1,
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
        repair: bool,
    ) -> dict:
        prefix = "Repair attempt: use only the exact chunk IDs below.\n\n" if repair else ""
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
                        f"</question-request-json>\n\n{excerpts}"
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
                    max_output_tokens=2_048,
                    temperature=0.7,
                    thinking_config=types.ThinkingConfig(
                        thinking_level=types.ThinkingLevel.LOW
                    ),
                ),
            )

        parsed = response.parsed
        if isinstance(parsed, BaseModel):
            return parsed.model_dump(mode="json")
        if isinstance(parsed, dict):
            return parsed
        text = response.text
        if not text:
            raise ValueError("provider returned no structured question plan")
        loaded = json.loads(text)
        if not isinstance(loaded, dict):
            raise ValueError("provider question plan was not an object")
        return loaded
