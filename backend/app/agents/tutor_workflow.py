"""Gemini adapter.

The only module allowed to import a provider SDK. Everything here is about
surviving Gemini rather than about tutoring: schema dialect quirks, malformed
output, and translating failures into the two errors the API can map.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from google.genai import types
from pydantic import ValidationError

from app.agents.gemini import create_client, response_object
from app.agents.workflow_errors import TutorWorkflowError, TutorWorkflowTimeout
from app.prompts.tutor import ALLOWED_ACTIONS, tutor_instruction
from app.schemas.problems import GroundingChunk, ProblemContext
from app.schemas.tutor import NormalizedBounds, TutorMode, TutorPlan

logger = logging.getLogger(__name__)

_POINT = {
    "type": "object",
    "properties": {"x": {"type": "number"}, "y": {"type": "number"}},
    "required": ["x", "y"],
}
_BOUNDS = {
    "type": "object",
    "properties": {
        "x": {"type": "number"},
        "y": {"type": "number"},
        "width": {"type": "number"},
        "height": {"type": "number"},
    },
    "required": ["x", "y", "width", "height"],
}

# Gemini's response_schema endpoint rejects additionalProperties, $defs/$ref,
# and discriminated unions, so the two action shapes are flattened into one
# object with nullable fields. TutorPlan remains the real validation boundary.
TUTOR_PLAN_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "status": {
            "type": "string",
            "enum": ["correct", "incorrect", "partial", "uncertain"],
        },
        "canvas_actions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "type": {"type": "string", "enum": list(ALLOWED_ACTIONS)},
                    "position": {**_POINT, "nullable": True},
                    "text": {"type": "string", "nullable": True},
                    "target": {**_BOUNDS, "nullable": True},
                },
                "required": ["type", "position", "text", "target"],
            },
        },
        "uncertainties": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "description": {"type": "string"},
                    "target": _BOUNDS,
                },
                "required": ["description", "target"],
            },
        },
        "summary": {"type": "string", "nullable": True},
    },
    "required": ["status", "canvas_actions", "uncertainties", "summary"],
}


#: The fields each action actually carries. The provider schema is flat, so a
#: response can name a field belonging to a different action; extra="forbid"
#: would reject the whole plan and spend a repair round trip on it.
_ACTION_FIELDS = {
    "text": {"type", "position", "text"},
    "circle": {"type", "target"},
    "check": {"type", "target"},
    "cross": {"type", "target"},
}


def normalize_provider_output(value: Any) -> Any:
    """Make provider output validate on the first attempt where it can."""
    plan = drop_nulls(value)
    if not isinstance(plan, dict) or not isinstance(plan.get("canvas_actions"), list):
        return plan
    actions = []
    for action in plan["canvas_actions"]:
        allowed = _ACTION_FIELDS.get(action.get("type")) if isinstance(action, dict) else None
        actions.append(
            {k: v for k, v in action.items() if k in allowed} if allowed else action
        )
    return {**plan, "canvas_actions": actions}


def drop_nulls(value: Any) -> Any:
    """Strip provider null placeholders before strict validation.

    The provider schema must mark every field required, so absent fields come
    back as null. A strict union rejects an explicit null, so they go first.
    Only None is removed: 0, "" and False are data.
    """
    if isinstance(value, dict):
        return {k: drop_nulls(v) for k, v in value.items() if v is not None}
    if isinstance(value, list):
        return [drop_nulls(v) for v in value]
    return value


class GeminiTutorWorkflow:
    """Reads the canvas and plans annotations in a single model call."""

    def __init__(
        self, *, api_key: str = "", model: str, timeout_seconds: float = 45
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.timeout_seconds = timeout_seconds

    async def run(
        self,
        *,
        mode: TutorMode,
        canvas_image: bytes,
        canvas_mime_type: str,
        prior_annotations: list[NormalizedBounds],
        problem: ProblemContext | None = None,
        course_context: list[GroundingChunk] | None = None,
    ) -> TutorPlan:
        malformed: Exception | None = None
        # One repair attempt. Transient HTTP retries belong to the SDK; this
        # is specifically the bounded retry for unusable structured output.
        try:
            async with create_client(self.api_key).aio as client:
                for attempt in range(2):
                    try:
                        raw = await self._request_plan(
                            client=client,
                            mode=mode,
                            canvas_image=canvas_image,
                            canvas_mime_type=canvas_mime_type,
                            prior_annotations=prior_annotations,
                            problem=problem,
                            course_context=course_context or [],
                            repair=attempt == 1,
                        )
                        return TutorPlan.model_validate(normalize_provider_output(raw))
                    except (ValidationError, ValueError, KeyError, TypeError) as exc:
                        malformed = exc
                        logger.warning(
                            "tutor output failed validation (attempt %d): %s",
                            attempt + 1,
                            exc,
                        )
        except (TimeoutError, asyncio.TimeoutError) as exc:
            logger.warning("tutor provider timed out after %ss", self.timeout_seconds)
            raise TutorWorkflowTimeout("the tutor took too long to respond") from exc
        except Exception:
            # Logged in full here because the client is told nothing: a
            # provider message can quote credentials and prompt fragments.
            logger.exception("tutor provider request failed")
            raise TutorWorkflowError("the tutor request failed") from None
        logger.error("tutor returned malformed output twice: %s", malformed)
        raise TutorWorkflowError("the tutor returned malformed output") from malformed

    def _generation_config(self, mode: TutorMode) -> types.GenerateContentConfig:
        return types.GenerateContentConfig(
            system_instruction=tutor_instruction(mode),
            response_mime_type="application/json",
            response_schema=TUTOR_PLAN_RESPONSE_SCHEMA,
            max_output_tokens=1_024,
            thinking_config=types.ThinkingConfig(
                thinking_level=types.ThinkingLevel.LOW
            ),
            media_resolution=types.MediaResolution.MEDIA_RESOLUTION_MEDIUM,
        )

    async def _request_plan(
        self,
        *,
        client: Any,
        mode: TutorMode,
        canvas_image: bytes,
        canvas_mime_type: str,
        prior_annotations: list[NormalizedBounds],
        problem: ProblemContext | None,
        course_context: list[GroundingChunk],
        repair: bool,
    ) -> dict:
        """One provider round trip, returning raw structured output."""
        prompt = "Repair attempt: return only data matching the schema.\n" if repair else ""
        prompt += f"<tutor-mode>{mode.value}</tutor-mode>\n\n"
        prompt += "Regions you have already annotated (do not grade them):\n"
        prompt += json.dumps([b.model_dump() for b in prior_annotations])
        prompt += "\n\n<current-problem>\n"
        prompt += (
            problem.prompt if problem is not None else "No structured problem was supplied."
        )
        prompt += "\n</current-problem>\n\n<course-reference-data>\n"
        if course_context:
            prompt += "\n\n".join(
                f"[source {chunk.chunk_id}, page {chunk.page}]\n{chunk.text}"
                for chunk in course_context
            )
        else:
            prompt += "No recorded course excerpts were available."
        prompt += "\n</course-reference-data>"

        message = types.Content(
            role="user",
            parts=[
                types.Part.from_bytes(data=canvas_image, mime_type=canvas_mime_type),
                types.Part.from_text(text=prompt),
            ],
        )
        async with asyncio.timeout(self.timeout_seconds):
            response = await client.models.generate_content(
                model=self.model,
                contents=message,
                config=self._generation_config(mode),
            )
        return response_object(response)
