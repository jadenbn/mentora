"""Low-latency Google ADK workflow for whiteboard interpretation and tutoring."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass
from typing import Any, Protocol

from google.adk.agents import LlmAgent
from google.adk.models import Gemini
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types
from pydantic import TypeAdapter, ValidationError

from app.prompts.tutor import CANVAS_ANALYST_INSTRUCTION, tutor_planner_instruction
from app.schemas.tutor import (
    CanvasAction,
    CanvasAnalysis,
    TextAction,
    TutorMode,
    TutorPlan,
    WorkStatus,
)


APP_NAME = "mentora_tutor"
logger = logging.getLogger("uvicorn.error")


_STATUS = {"type": "string", "enum": ["correct", "incorrect", "partial", "uncertain"]}
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
_COURSE_BOUNDARY = {
    "type": "object",
    "properties": {
        "requires_confirmation": {"type": "boolean"},
        "technique": {"type": "string", "nullable": True},
        "message": {"type": "string", "nullable": True},
        "alternatives_available": {"type": "boolean"},
    },
    "required": [
        "requires_confirmation",
        "technique",
        "message",
        "alternatives_available",
    ],
}

# ADK 2.x sends output_schema through Gemini's legacy response_schema API. Keep
# these provider schemas intentionally simple: that endpoint rejects Pydantic's
# additionalProperties and complex discriminated unions. The full strict models
# below remain the authoritative validation boundary.
CANVAS_ANALYSIS_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "status": _STATUS,
        "confidence": {"type": "number"},
        "current_work_summary": {"type": "string"},
        "student_intent": {"type": "string", "nullable": True},
        "identified_steps": {"type": "array", "items": {"type": "string"}},
        "strengths": {"type": "array", "items": {"type": "string"}},
        "issues": {"type": "array", "items": {"type": "string"}},
        "learning_observations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "type": {
                        "type": "string",
                        "enum": ["strength", "mistake", "progress", "help_usage"],
                    },
                    "topic": {"type": "string"},
                    "skill": {"type": "string"},
                    "outcome": _STATUS,
                    "evidence": {"type": "string"},
                    "mistake_tag": {"type": "string", "nullable": True},
                    "confidence": {"type": "number"},
                },
                "required": [
                    "type",
                    "topic",
                    "skill",
                    "outcome",
                    "evidence",
                    "mistake_tag",
                    "confidence",
                ],
            },
        },
        "course_boundary": _COURSE_BOUNDARY,
    },
    "required": [
        "status",
        "confidence",
        "current_work_summary",
        "student_intent",
        "identified_steps",
        "strengths",
        "issues",
        "learning_observations",
        "course_boundary",
    ],
}

TUTOR_PLAN_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "status": _STATUS,
        "confidence": {"type": "number"},
        "canvas_actions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "type": {
                        "type": "string",
                        "enum": [
                            "text",
                            "math",
                            "arrow",
                            "circle",
                            "underline",
                            "highlight",
                            "check",
                            "cross",
                        ],
                    },
                    "purpose": {"type": "string", "nullable": True},
                    "position": {**_POINT, "nullable": True},
                    "text": {"type": "string", "nullable": True},
                    "latex": {"type": "string", "nullable": True},
                    "start": {**_POINT, "nullable": True},
                    "end": {**_POINT, "nullable": True},
                    "target": {**_BOUNDS, "nullable": True},
                    "label": {"type": "string", "nullable": True},
                },
                "required": [
                    "type",
                    "purpose",
                    "position",
                    "text",
                    "latex",
                    "start",
                    "end",
                    "target",
                    "label",
                ],
            },
        },
        "summary": {"type": "string", "nullable": True},
        "warnings": {"type": "array", "items": {"type": "string"}},
        "course_boundary": _COURSE_BOUNDARY,
    },
    "required": [
        "status",
        "confidence",
        "canvas_actions",
        "summary",
        "warnings",
        "course_boundary",
    ],
}

TUTOR_WORKFLOW_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "analysis": CANVAS_ANALYSIS_RESPONSE_SCHEMA,
        "plan": TUTOR_PLAN_RESPONSE_SCHEMA,
    },
    "required": ["analysis", "plan"],
}


def _drop_nulls(value: Any) -> Any:
    """Remove provider-only null placeholders before strict union validation."""
    if isinstance(value, dict):
        return {
            key: _drop_nulls(item)
            for key, item in value.items()
            if item is not None
        }
    if isinstance(value, list):
        return [_drop_nulls(item) for item in value]
    return value


_ACTION_FIELDS = {
    "text": {"type", "purpose", "position", "text"},
    "math": {"type", "purpose", "position", "latex"},
    "arrow": {"type", "purpose", "start", "end", "label"},
    "circle": {"type", "purpose", "target", "label"},
    "underline": {"type", "purpose", "target", "label"},
    "highlight": {"type", "purpose", "target", "label"},
    "check": {"type", "purpose", "target", "label"},
    "cross": {"type", "purpose", "target", "label"},
}
_CANVAS_ACTION_ADAPTER = TypeAdapter(CanvasAction)


def _normalize_provider_output(value: Any) -> Any:
    """Remove nullable union placeholders and irrelevant per-action fields."""
    normalized = _drop_nulls(value)
    if not isinstance(normalized, dict):
        return normalized
    plan = normalized.get("plan")
    if not isinstance(plan, dict) or not isinstance(plan.get("canvas_actions"), list):
        return normalized
    actions = []
    for action in plan["canvas_actions"]:
        if not isinstance(action, dict):
            actions.append(action)
            continue
        allowed = _ACTION_FIELDS.get(action.get("type"))
        actions.append(
            {key: item for key, item in action.items() if key in allowed}
            if allowed
            else action
        )
    plan["canvas_actions"] = actions
    return normalized


def _validation_locations(exc: ValidationError, *, prefix: str = "") -> list[str]:
    """Return safe schema locations and error categories, never rejected values."""
    locations: list[str] = []
    for error in exc.errors(include_input=False)[:8]:
        location = ".".join(str(item) for item in error.get("loc", ()))
        field = f"{prefix}{location}" if location else prefix.rstrip(".")
        locations.append(f"{field}:{error.get('type', 'validation_error')}")
    return locations


def _fallback_plan(analysis: CanvasAnalysis) -> TutorPlan:
    if analysis.status == WorkStatus.correct:
        text = "This work is correct—no additional step is required."
    elif analysis.status == WorkStatus.uncertain:
        text = "I can’t read this clearly—could you rewrite or select the step?"
    else:
        text = next(
            (issue.strip() for issue in analysis.issues if issue.strip()),
            analysis.current_work_summary.strip() or "Please review the current step.",
        )
    return TutorPlan(
        status=analysis.status,
        confidence=analysis.confidence,
        canvas_actions=[
            TextAction(
                type="text",
                position={"x": 0.5, "y": 0.5},
                text=text[:240],
                purpose="safe_local_recovery",
            )
        ],
        summary=(analysis.current_work_summary[:1_000] or None),
        warnings=["Tutor feedback was simplified after an invalid model action."],
        course_boundary=analysis.course_boundary,
    )


def _validate_or_recover_plan(
    raw_plan: Any,
    analysis: CanvasAnalysis,
) -> tuple[TutorPlan, int, list[str]]:
    """Keep valid actions and recover locally without another provider request."""
    if not isinstance(raw_plan, dict):
        return _fallback_plan(analysis), 0, ["plan:object_type"]

    raw_actions = raw_plan.get("canvas_actions")
    valid_actions: list[CanvasAction] = []
    dropped_actions = 0
    locations: list[str] = []
    if isinstance(raw_actions, list):
        for index, action in enumerate(raw_actions):
            try:
                valid_actions.append(_CANVAS_ACTION_ADAPTER.validate_python(action))
            except ValidationError as exc:
                dropped_actions += 1
                locations.extend(
                    _validation_locations(exc, prefix=f"plan.canvas_actions.{index}.")
                )
    else:
        locations.append("plan.canvas_actions:list_type")

    candidate = dict(raw_plan)
    candidate["canvas_actions"] = valid_actions
    try:
        plan = TutorPlan.model_validate(candidate)
    except ValidationError as exc:
        locations.extend(_validation_locations(exc, prefix="plan."))
        return _fallback_plan(analysis), dropped_actions, locations

    if isinstance(raw_actions, list) and raw_actions and not valid_actions:
        return _fallback_plan(analysis), dropped_actions, locations
    if dropped_actions:
        plan.warnings = [
            *plan.warnings[:19],
            "Some invalid tutor actions were omitted.",
        ]
    return plan, dropped_actions, locations


def _is_rate_limit_error(exc: BaseException) -> bool:
    current: BaseException | None = exc
    visited: set[int] = set()
    while current is not None and id(current) not in visited:
        visited.add(id(current))
        if getattr(current, "code", None) == 429:
            return True
        status = str(getattr(current, "status", "")).upper()
        name = type(current).__name__.replace("_", "").lower()
        if status == "RESOURCE_EXHAUSTED" or "resourceexhausted" in name:
            return True
        current = current.__cause__ or current.__context__
    return False


class TutorWorkflowError(RuntimeError):
    """Safe boundary for provider, timeout, and malformed-output errors."""


class TutorRateLimitError(TutorWorkflowError):
    """The configured tutor provider has exhausted its current request quota."""


@dataclass(frozen=True)
class TutorWorkflowResult:
    analysis: CanvasAnalysis
    plan: TutorPlan


class TutorWorkflow(Protocol):
    async def run(
        self,
        *,
        interaction_id: str,
        user_id: str,
        mode: TutorMode,
        context: dict,
        canvas_image: bytes,
        canvas_mime_type: str,
        selection_image: bytes | None,
        selection_mime_type: str | None,
    ) -> TutorWorkflowResult: ...


class AdkTutorWorkflow:
    """Runs analyst and planner roles in one schema-bound multimodal call."""

    def __init__(self, *, model: str, timeout_seconds: float = 8) -> None:
        self.model = model
        self.timeout_seconds = timeout_seconds

    def _build_agent(self, mode: TutorMode) -> LlmAgent:
        model = Gemini(
            model=self.model,
            retry_options=types.HttpRetryOptions(
                attempts=3,
                initial_delay=0.5,
                max_delay=4,
                exp_base=2,
                jitter=0.2,
                # A 429 can carry a long provider Retry-After value (43 seconds
                # on the free tier). Retrying cannot fix a daily quota and
                # makes an interactive canvas request appear to hang.
                http_status_codes=[408, 500, 502, 503, 504],
            ),
        )
        generation_config = types.GenerateContentConfig(
            max_output_tokens=1_024,
            # Canvas feedback is an interactive, schema-bound task. Minimal
            # thinking and medium image resolution reduce latency while keeping
            # handwriting readable.
            thinking_config=types.ThinkingConfig(
                thinking_level=types.ThinkingLevel.MINIMAL
            ),
            media_resolution=types.MediaResolution.MEDIA_RESOLUTION_MEDIUM,
        )
        return LlmAgent(
            name="whiteboard_tutor",
            description=(
                "Interprets student work and plans validated spatial tutor feedback."
            ),
            model=model,
            instruction=(
                CANVAS_ANALYST_INSTRUCTION
                + "\n\nAfter completing that analysis, perform the Tutor Planner "
                "role below in the same response. Keep analysis and plan as "
                "separate top-level objects named 'analysis' and 'plan'.\n\n"
                + tutor_planner_instruction(mode)
            ),
            output_schema=TUTOR_WORKFLOW_RESPONSE_SCHEMA,
            output_key="tutor_result",
            generate_content_config=generation_config,
            disallow_transfer_to_parent=True,
            disallow_transfer_to_peers=True,
        )

    async def run(
        self,
        *,
        interaction_id: str,
        user_id: str,
        mode: TutorMode,
        context: dict,
        canvas_image: bytes,
        canvas_mime_type: str,
        selection_image: bytes | None,
        selection_mime_type: str | None,
    ) -> TutorWorkflowResult:
        attempt_started = time.perf_counter()
        logger.info(
            "tutor.trace stage=workflow_attempt interaction_id=%s mode=%s attempt=1",
            interaction_id,
            mode.value,
        )
        try:
            async with asyncio.timeout(self.timeout_seconds):
                result = await self._run_once(
                    interaction_id=interaction_id,
                    user_id=user_id,
                    mode=mode,
                    context=context,
                    canvas_image=canvas_image,
                    canvas_mime_type=canvas_mime_type,
                    selection_image=selection_image,
                    selection_mime_type=selection_mime_type,
                )
            logger.info(
                "tutor.trace stage=workflow_attempt_complete interaction_id=%s "
                "mode=%s attempt=1 elapsed_ms=%s",
                interaction_id,
                mode.value,
                round((time.perf_counter() - attempt_started) * 1_000),
            )
            return result
        except ValidationError as exc:
            logger.warning(
                "tutor.trace stage=workflow_output_invalid interaction_id=%s "
                "mode=%s fields=%s",
                interaction_id,
                mode.value,
                ",".join(_validation_locations(exc, prefix="analysis.")),
            )
            raise TutorWorkflowError("tutor returned malformed analysis output") from exc
        except (ValueError, KeyError, json.JSONDecodeError) as exc:
            logger.warning(
                "tutor.trace stage=workflow_output_invalid interaction_id=%s "
                "mode=%s exception=%s",
                interaction_id,
                mode.value,
                type(exc).__name__,
            )
            raise TutorWorkflowError("tutor returned malformed structured output") from exc
        except TimeoutError as exc:
            logger.error(
                "tutor.trace stage=workflow_timeout interaction_id=%s mode=%s",
                interaction_id,
                mode.value,
            )
            raise TutorWorkflowError("tutor workflow timed out") from exc
        except Exception as exc:
            if _is_rate_limit_error(exc):
                logger.warning(
                    "tutor.trace stage=workflow_rate_limited interaction_id=%s "
                    "mode=%s provider_exception=%s",
                    interaction_id,
                    mode.value,
                    type(exc).__name__,
                )
                raise TutorRateLimitError("tutor provider quota exhausted") from exc
            logger.error(
                "tutor.trace stage=workflow_provider_error interaction_id=%s "
                "mode=%s provider_exception=%s",
                interaction_id,
                mode.value,
                type(exc).__name__,
            )
            raise TutorWorkflowError("tutor provider request failed") from exc

    async def _run_once(
        self,
        *,
        interaction_id: str,
        user_id: str,
        mode: TutorMode,
        context: dict,
        canvas_image: bytes,
        canvas_mime_type: str,
        selection_image: bytes | None,
        selection_mime_type: str | None,
    ) -> TutorWorkflowResult:
        session_service = InMemorySessionService()
        runner = Runner(
            app_name=APP_NAME,
            node=self._build_agent(mode),
            session_service=session_service,
        )
        await session_service.create_session(
            app_name=APP_NAME,
            user_id=user_id,
            session_id=interaction_id,
        )

        parts = [types.Part.from_bytes(data=canvas_image, mime_type=canvas_mime_type)]
        if selection_image and selection_mime_type:
            parts.append(
                types.Part.from_bytes(
                    data=selection_image,
                    mime_type=selection_mime_type,
                )
            )
        request_text = "Structured tutor request and retrieved course context:\n"
        request_text += json.dumps(context, separators=(",", ":"), default=str)
        parts.append(types.Part.from_text(text=request_text))

        message = types.Content(role="user", parts=parts)
        async for _event in runner.run_async(
            user_id=user_id,
            session_id=interaction_id,
            new_message=message,
        ):
            pass

        session = await session_service.get_session(
            app_name=APP_NAME,
            user_id=user_id,
            session_id=interaction_id,
        )
        if session is None:
            raise ValueError("ADK session was not available after workflow completion")
        output = _normalize_provider_output(session.state.get("tutor_result"))
        if not isinstance(output, dict):
            raise ValueError("ADK tutor result was not a structured object")
        analysis = CanvasAnalysis.model_validate(output.get("analysis"))
        plan, dropped_actions, locations = _validate_or_recover_plan(
            output.get("plan"), analysis
        )
        if locations:
            logger.warning(
                "tutor.trace stage=workflow_plan_recovered interaction_id=%s "
                "mode=%s dropped_actions=%s fields=%s",
                interaction_id,
                mode.value,
                dropped_actions,
                ",".join(locations),
            )
        return TutorWorkflowResult(analysis=analysis, plan=plan)
