"""Direct Gemini adapter.

The only module allowed to import a provider SDK. Everything here is about
surviving Gemini rather than about tutoring: schema dialect quirks, malformed
output, and translating failures into the two errors the API can map.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from google import genai
from google.genai import types
from pydantic import BaseModel, ValidationError

from app.agents.workflow_errors import TutorWorkflowError, TutorWorkflowTimeout
from app.prompts.tutor import ALLOWED_ACTIONS, tutor_instruction
from app.schemas.problems import GroundingChunk, ProblemContext
from app.schemas.tutor import ErrorTag, NormalizedBounds, TutorMode, TutorPlan
from app.engine import LearnerContext

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
        "summary": {"type": "string", "nullable": True},
        "error_tag": {"type": "string", "enum": [t.value for t in ErrorTag], "nullable": True},
    },
    "required": ["status", "canvas_actions", "summary", "error_tag"],
}


def _render_learner(learner: LearnerContext | None) -> str:
    """The one sentence of student-model context the tutor gets.

    Never a bare number: the prompt in prompts/tutor.py tells the model not
    to quote this back, and rendering it as a sentence rather than a field
    named "estimate" is a second layer of the same discipline.
    """
    if learner is None:
        return "No student history is available for this topic."
    if learner.attempts == 0:
        return f"This is the student's first attempt on {learner.skill_name}."
    return (
        f"On {learner.skill_name}, this student's estimated accuracy is "
        f"{learner.estimate:.2f} over {learner.attempts} attempt(s). "
        f"They have taken {learner.hints_on_this_problem} hint(s) on this problem so far."
    )


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
                    # Quota exhaustion is not transient. Respecting a long
                    # Retry-After would make an interactive tap appear hung.
                    http_status_codes=[408, 500, 502, 503, 504],
                )
            ),
        )

    async def run(
        self,
        *,
        mode: TutorMode,
        canvas_image: bytes,
        canvas_mime_type: str,
        prior_annotations: list[NormalizedBounds],
        problem: ProblemContext | None = None,
        course_context: list[GroundingChunk] | None = None,
        learner: LearnerContext | None = None,
    ) -> TutorPlan:
        malformed: Exception | None = None
        try:
            # Reuse one direct SDK client across the normal and repair calls.
            async with self._client().aio as client:
                # One repair attempt. Transient HTTP retries belong to the SDK;
                # this is specifically for unusable structured output.
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
                            learner=learner,
                            repair=attempt == 1,
                        )
                        return TutorPlan.model_validate(drop_nulls(raw))
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
        learner: LearnerContext | None,
        repair: bool,
    ) -> dict:
        """One provider round trip, returning raw structured output."""
        prompt = "Repair attempt: return only data matching the schema.\n" if repair else ""
        prompt += f"<tutor-mode>{mode.value}</tutor-mode>\n\n"
        prompt += "Regions you have already annotated (do not grade them):\n"
        prompt += json.dumps([b.model_dump() for b in prior_annotations])
        prompt += "\n\n<current-problem>\n"
        prompt += problem.prompt if problem is not None else "No structured problem was supplied."
        prompt += "\n</current-problem>"
        prompt += "\n\n<learner>\n"
        prompt += _render_learner(learner)
        prompt += "\n</learner>"
        prompt += "\n\n<course-reference-data>\n"
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
                types.Part.from_text(text=prompt),
                types.Part.from_bytes(data=canvas_image, mime_type=canvas_mime_type),
            ],
        )
        async with asyncio.timeout(self.timeout_seconds):
            response = await client.models.generate_content(
                model=self.model,
                contents=message,
                config=types.GenerateContentConfig(
                    system_instruction=tutor_instruction(mode),
                    response_mime_type="application/json",
                    response_schema=TUTOR_PLAN_RESPONSE_SCHEMA,
                    max_output_tokens=2_048,
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
            raise ValueError("provider returned no structured tutor plan")
        loaded = json.loads(text)
        if not isinstance(loaded, dict):
            raise ValueError("provider tutor plan was not an object")
        return loaded
