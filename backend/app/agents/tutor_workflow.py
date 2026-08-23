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
from uuid import uuid4

from google.adk.agents import LlmAgent
from google.adk.models import Gemini
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types
from pydantic import ValidationError

from app.agents.workflow_errors import TutorWorkflowError, TutorWorkflowTimeout
from app.prompts.tutor import ALLOWED_ACTIONS, tutor_instruction
from app.schemas.tutor import NormalizedBounds, TutorMode, TutorPlan

logger = logging.getLogger(__name__)

APP_NAME = "mentora_tutor"

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

    def __init__(self, *, model: str, timeout_seconds: float = 45) -> None:
        self.model = model
        self.timeout_seconds = timeout_seconds

    async def run(
        self,
        *,
        mode: TutorMode,
        canvas_image: bytes,
        canvas_mime_type: str,
        prior_annotations: list[NormalizedBounds],
    ) -> TutorPlan:
        malformed: Exception | None = None
        # One repair attempt. Transient HTTP retries belong to the SDK; this
        # is specifically the bounded retry for unusable structured output.
        for attempt in range(2):
            try:
                raw = await self._request_plan(
                    mode=mode,
                    canvas_image=canvas_image,
                    canvas_mime_type=canvas_mime_type,
                    prior_annotations=prior_annotations,
                    repair=attempt == 1,
                )
                return TutorPlan.model_validate(normalize_provider_output(raw))
            except (ValidationError, ValueError, KeyError, TypeError) as exc:
                malformed = exc
                logger.warning("tutor output failed validation (attempt %d): %s", attempt + 1, exc)
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

    def _build_agent(self, mode: TutorMode) -> LlmAgent:
        return LlmAgent(
            name="whiteboard_tutor",
            description="Reads student work and plans restrained canvas feedback.",
            model=Gemini(
                model=self.model,
                retry_options=types.HttpRetryOptions(
                    attempts=3,
                    initial_delay=0.5,
                    max_delay=4,
                    exp_base=2,
                    jitter=0.2,
                    # 429 is excluded on purpose: retrying cannot fix an
                    # exhausted daily quota, and the provider's Retry-After can
                    # be long enough to make an interactive tap look hung.
                    http_status_codes=[408, 500, 502, 503, 504],
                ),
            ),
            instruction=tutor_instruction(mode),
            output_schema=TUTOR_PLAN_RESPONSE_SCHEMA,
            output_key="tutor_plan",
            generate_content_config=types.GenerateContentConfig(
                # A four-action plan needs far less than this; the ceiling is
                # only here to stop a runaway response.
                max_output_tokens=1_024,
                thinking_config=types.ThinkingConfig(
                    thinking_level=types.ThinkingLevel.MINIMAL
                ),
                # Vision tokens dominate a canvas request. Handwriting stays
                # legible at medium, so the default high resolution is paid
                # latency for no accuracy.
                media_resolution=types.MediaResolution.MEDIA_RESOLUTION_MEDIUM,
            ),
            disallow_transfer_to_parent=True,
            disallow_transfer_to_peers=True,
        )

    async def _request_plan(
        self,
        *,
        mode: TutorMode,
        canvas_image: bytes,
        canvas_mime_type: str,
        prior_annotations: list[NormalizedBounds],
        repair: bool,
    ) -> dict:
        """One provider round trip, returning raw structured output."""
        session_service = InMemorySessionService()
        session_id = uuid4().hex
        runner = Runner(
            app_name=APP_NAME,
            agent=self._build_agent(mode),
            session_service=session_service,
        )
        await session_service.create_session(
            app_name=APP_NAME, user_id=APP_NAME, session_id=session_id
        )

        prompt = "Repair attempt: return only data matching the schema.\n" if repair else ""
        prompt += "Regions you have already annotated (do not grade them):\n"
        prompt += json.dumps([b.model_dump() for b in prior_annotations])

        message = types.Content(
            role="user",
            parts=[
                types.Part.from_bytes(data=canvas_image, mime_type=canvas_mime_type),
                types.Part.from_text(text=prompt),
            ],
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
            raise ValueError("provider session was unavailable after the run")
        return session.state.get("tutor_plan")
