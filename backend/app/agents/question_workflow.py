"""Gemini adapter for one validated, source-grounded practice question."""

from __future__ import annotations

import asyncio
import logging
from uuid import uuid4

from google.adk.agents import LlmAgent
from google.adk.models import Gemini
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types
from pydantic import ValidationError

from app.agents.workflow_errors import QuestionWorkflowError, QuestionWorkflowTimeout
from app.prompts.question_generation import QUESTION_INSTRUCTION
from app.schemas.problems import GroundingChunk, QuestionPlan

logger = logging.getLogger(__name__)
APP_NAME = "mentora_question_generator"

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
    def __init__(self, *, model: str, timeout_seconds: float = 45) -> None:
        self.model = model
        self.timeout_seconds = timeout_seconds

    async def run(self, *, chunks: list[GroundingChunk]) -> QuestionPlan:
        allowed = {chunk.chunk_id for chunk in chunks}
        malformed: Exception | None = None
        for attempt in range(2):
            try:
                raw = await self._request(chunks=chunks, repair=attempt == 1)
                plan = QuestionPlan.model_validate(raw)
                if len(set(plan.grounding_chunk_ids)) != len(plan.grounding_chunk_ids):
                    raise ValueError("grounding chunk IDs must be unique")
                if any(chunk_id not in allowed for chunk_id in plan.grounding_chunk_ids):
                    raise ValueError("grounding chunk ID was not supplied")
                return plan
            except (ValidationError, ValueError, KeyError, TypeError) as exc:
                malformed = exc
                logger.warning("question output failed validation (attempt %d): %s", attempt + 1, exc)
            except (TimeoutError, asyncio.TimeoutError) as exc:
                raise QuestionWorkflowTimeout("question generation timed out") from exc
            except Exception:
                logger.exception("question provider request failed")
                raise QuestionWorkflowError("question generation failed") from None
        raise QuestionWorkflowError("question generation returned malformed output") from malformed

    def _agent(self) -> LlmAgent:
        return LlmAgent(
            name="course_question_generator",
            description="Creates one grounded practice problem from course excerpts.",
            model=Gemini(
                model=self.model,
                retry_options=types.HttpRetryOptions(
                    attempts=3,
                    initial_delay=0.5,
                    max_delay=4,
                    exp_base=2,
                    jitter=0.2,
                    http_status_codes=[408, 500, 502, 503, 504],
                ),
            ),
            instruction=QUESTION_INSTRUCTION,
            output_schema=QUESTION_PLAN_RESPONSE_SCHEMA,
            output_key="question_plan",
            generate_content_config=types.GenerateContentConfig(
                max_output_tokens=2_048,
                temperature=0.7,
                thinking_config=types.ThinkingConfig(thinking_level=types.ThinkingLevel.LOW),
            ),
            disallow_transfer_to_parent=True,
            disallow_transfer_to_peers=True,
        )

    async def _request(self, *, chunks: list[GroundingChunk], repair: bool) -> dict:
        session_service = InMemorySessionService()
        session_id = uuid4().hex
        runner = Runner(
            app_name=APP_NAME,
            agent=self._agent(),
            session_service=session_service,
        )
        await session_service.create_session(
            app_name=APP_NAME, user_id=APP_NAME, session_id=session_id
        )
        prefix = "Repair attempt: use only the exact chunk IDs below.\n\n" if repair else ""
        excerpts = "\n\n".join(
            f"<course-excerpt id=\"{chunk.chunk_id}\" page=\"{chunk.page}\">\n"
            f"{chunk.text}\n</course-excerpt>"
            for chunk in chunks
        )
        message = types.Content(
            role="user",
            parts=[types.Part.from_text(text=f"{prefix}{excerpts}")],
        )
        async with asyncio.timeout(self.timeout_seconds):
            async for _event in runner.run_async(
                user_id=APP_NAME, session_id=session_id, new_message=message
            ):
                pass
        session = await session_service.get_session(
            app_name=APP_NAME, user_id=APP_NAME, session_id=session_id
        )
        if session is None:
            raise ValueError("provider session unavailable")
        return session.state.get("question_plan")
