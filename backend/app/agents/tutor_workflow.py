"""Gemini adapter.

The only module allowed to import a provider SDK. Everything here is about
surviving Gemini rather than about tutoring: schema dialect quirks, malformed
output, and translating failures into the two errors the API can map.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any

from google.genai import types
from pydantic import ValidationError

from app.agents.gemini import as_thinking_level, create_client, response_object
from app.agents.workflow_errors import TutorWorkflowError, TutorWorkflowTimeout
from app.prompts.tutor import ALLOWED_ACTIONS, tutor_instruction
from app.schemas.problems import GroundingChunk, ProblemContext
from app.schemas.tutor import NormalizedBounds, TutorMode, TutorPlan

logger = logging.getLogger(__name__)

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
# and discriminated unions, so the target action is represented by one flat
# object with a nullable target. TutorPlan remains the real validation boundary.
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
                    "target": {**_BOUNDS, "nullable": True},
                },
                "required": ["type", "target"],
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
        "summary": {"type": "string"},
    },
    "required": ["status", "canvas_actions", "uncertainties", "summary"],
}


#: The fields each action actually carries. The provider schema is flat, so a
#: response can name a field belonging to a different action; extra="forbid"
#: would reject the whole plan and spend a repair round trip on it.
_ACTION_FIELDS = {
    "highlight": {"type", "target"},
    "circle": {"type", "target"},
    "check": {"type", "target"},
    "cross": {"type", "target"},
}


def _canvas_state(canvas_image: bytes | None) -> str:
    if canvas_image is None:
        return (
            "<canvas-state>\n"
            "No student-work image was supplied because the student has not drawn anything yet. "
            "Use the structured problem to give the first useful scaffold. Do not say that "
            "the handwriting is unreadable or ask the student to rewrite a step.\n"
            "</canvas-state>"
        )
    return (
        "<canvas-state>\n"
        "A student-work image is supplied above. Base grading and coordinates on what is "
        "visible in that image.\n"
        "</canvas-state>"
    )


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
        self,
        *,
        api_key: str = "",
        model: str,
        thinking_level: str = "low",
        timeout_seconds: float = 45,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.thinking_level = thinking_level
        self.timeout_seconds = timeout_seconds

    async def run(
        self,
        *,
        mode: TutorMode,
        canvas_image: bytes | None,
        canvas_mime_type: str | None,
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
                thinking_level=as_thinking_level(self.thinking_level)
            ),
            media_resolution=types.MediaResolution.MEDIA_RESOLUTION_MEDIUM,
        )

    async def _request_plan(
        self,
        *,
        client: Any,
        mode: TutorMode,
        canvas_image: bytes | None,
        canvas_mime_type: str | None,
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
        prompt += "\n\n" + _canvas_state(canvas_image) + "\n\n<current-problem>\n"
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

        parts = [types.Part.from_text(text=prompt)]
        if canvas_image is not None:
            if canvas_mime_type is None:
                raise ValueError("canvas_mime_type is required with canvas_image")
            parts.insert(0, types.Part.from_bytes(data=canvas_image, mime_type=canvas_mime_type))
        message = types.Content(role="user", parts=parts)
        if os.getenv("TUTOR_DEBUG_LOG_REQUESTS") == "1":
            request_log = {
                "model": self.model,
                "mode": mode.value,
                "repair": repair,
                "system_instruction": tutor_instruction(mode),
                "contents": {
                    "role": "user",
                    "parts": [
                        *(
                            [
                                {
                                    "type": "image",
                                    "mime_type": canvas_mime_type,
                                    "bytes": len(canvas_image or b""),
                                }
                            ]
                            if canvas_image is not None
                            else []
                        ),
                        {"type": "text", "text": prompt},
                    ],
                },
                "context": {
                    "prior_annotations": [b.model_dump(mode="json") for b in prior_annotations],
                    "problem": problem.model_dump(mode="json") if problem else None,
                    "course_context": [
                        chunk.model_dump(mode="json") for chunk in course_context
                    ],
                },
                "generation_config": {
                    "response_mime_type": "application/json",
                    "response_schema": TUTOR_PLAN_RESPONSE_SCHEMA,
                    "max_output_tokens": 1_024,
                    "thinking_level": "LOW",
                    "media_resolution": "MEDIUM",
                },
            }
            print(
                "tutor_gemini_request=" + json.dumps(request_log, ensure_ascii=False),
                flush=True,
            )
        async with asyncio.timeout(self.timeout_seconds):
            response = await client.models.generate_content(
                model=self.model,
                contents=message,
                config=self._generation_config(mode),
            )
        return response_object(response)
