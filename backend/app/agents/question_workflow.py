"""Direct Gemini adapter for one validated, source-grounded question."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from google.genai import types
from pydantic import ValidationError

from app.agents.gemini import create_client, response_object
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

    async def run(
        self, *, chunks: list[GroundingChunk], question_request: str
    ) -> QuestionPlan:
        allowed = {chunk.chunk_id for chunk in chunks}
        malformed: Exception | None = None
        try:
            async with create_client(self.api_key).aio as client:
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

        return response_object(response)
