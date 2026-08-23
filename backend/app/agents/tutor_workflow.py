"""Low-latency, single-pass whiteboard tutor workflow."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, Literal, Protocol

from google.adk.agents import LlmAgent
from google.adk.models import Gemini
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types
from pydantic import BaseModel, Field, TypeAdapter, ValidationError, model_validator

from app.prompts.tutor import tutor_instruction
from app.schemas.tutor import (
    CanvasAction,
    CourseBoundaryDecision,
    LearningObservation,
    TextAction,
    TutorMode,
    WorkStatus,
)


APP_NAME = "mentora_tutor"
logger = logging.getLogger("uvicorn.error")

class _WirePoint(BaseModel):
    x: float
    y: float

    @model_validator(mode="after")
    def valid_point(self) -> "_WirePoint":
        if not (0 <= self.x <= 1 and 0 <= self.y <= 1):
            raise ValueError("point must remain inside the image")
        return self


class _WireBounds(_WirePoint):
    width: float
    height: float

    @model_validator(mode="after")
    def valid_bounds(self) -> "_WireBounds":
        if (
            self.width <= 0
            or self.height <= 0
            or self.x + self.width > 1
            or self.y + self.height > 1
        ):
            raise ValueError("bounds must be positive and remain inside the image")
        return self


class _WireAction(BaseModel):
    type: Literal["text", "math", "arrow", "circle", "underline", "highlight", "check", "cross"]
    purpose: str | None
    position: _WirePoint | None
    text: str | None
    latex: str | None
    start: _WirePoint | None
    end: _WirePoint | None
    target: _WireBounds | None
    label: str | None


class _WireUncertainty(BaseModel):
    description: str
    target: _WireBounds


class _WireLearningObservation(BaseModel):
    type: Literal["strength", "mistake", "progress", "help_usage"]
    topic: str
    skill: str
    outcome: WorkStatus
    evidence: str
    mistake_tag: str | None
    confidence: float


class _WireCourseBoundary(BaseModel):
    requires_confirmation: bool
    technique: str | None
    message: str | None
    alternatives_available: bool


class TutorWireOutput(BaseModel):
    status: WorkStatus
    confidence: float
    observed_work: str
    uncertainties: list[_WireUncertainty]
    issues: list[str]
    canvas_actions: list[_WireAction]
    summary: str | None
    warnings: list[str]
    learning_observations: list[_WireLearningObservation]
    course_boundary: _WireCourseBoundary


class TutorAgentOutput(BaseModel):
    status: WorkStatus
    confidence: float = Field(ge=0, le=1)
    observed_work: str = Field(max_length=2_000)
    uncertainties: list[_WireUncertainty] = Field(default_factory=list, max_length=20)
    issues: list[str] = Field(default_factory=list, max_length=30)
    canvas_actions: list[CanvasAction] = Field(default_factory=list, max_length=12)
    summary: str | None = Field(default=None, max_length=1_000)
    warnings: list[str] = Field(default_factory=list, max_length=20)
    learning_observations: list[LearningObservation] = Field(
        default_factory=list, max_length=20
    )
    course_boundary: CourseBoundaryDecision = Field(
        default_factory=CourseBoundaryDecision
    )


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


def _validation_locations(exc: ValidationError, *, prefix: str = "") -> list[str]:
    locations: list[str] = []
    for error in exc.errors(include_input=False)[:8]:
        location = ".".join(str(item) for item in error.get("loc", ()))
        field = f"{prefix}{location}" if location else prefix.rstrip(".")
        locations.append(f"{field}:{error.get('type', 'validation_error')}")
    return locations


def validate_tutor_output(raw: Any) -> tuple[TutorAgentOutput, list[str]]:
    if not isinstance(raw, dict):
        raise ValueError("ADK tutor result was not a structured object")

    empty_lists = {key: [] for key in (
        "uncertainties", "issues", "warnings", "learning_observations"
    )}
    header = {**empty_lists, "summary": None, **raw}
    boundary = header.get("course_boundary")
    if isinstance(boundary, dict):
        header["course_boundary"] = {"technique": None, "message": None, **boundary}
    observations = header.get("learning_observations")
    if isinstance(observations, list):
        header["learning_observations"] = [
            {"mistake_tag": None, **item} if isinstance(item, dict) else item
            for item in observations
        ]
    header["canvas_actions"] = []
    wire = TutorWireOutput.model_validate(header)

    raw_actions = raw.get("canvas_actions", [])
    actions: list[CanvasAction] = []
    dropped_actions = 0
    locations: list[str] = []
    if not isinstance(raw_actions, list):
        raw_actions = []
        locations.append("canvas_actions:list_type")
    for index, raw_action in enumerate(raw_actions):
        if not isinstance(raw_action, dict):
            dropped_actions += 1
            locations.append(f"canvas_actions.{index}:dict_type")
            continue
        try:
            action = _WireAction.model_validate(
                dict.fromkeys(_WireAction.model_fields) | raw_action
            )
            data = action.model_dump(exclude_none=True)
            actions.append(
                _CANVAS_ACTION_ADAPTER.validate_python(
                    {
                        key: value
                        for key, value in data.items()
                        if key in _ACTION_FIELDS[action.type]
                    }
                )
            )
        except ValidationError as exc:
            dropped_actions += 1
            locations.extend(
                _validation_locations(exc, prefix=f"canvas_actions.{index}.")
            )

    status = WorkStatus.uncertain if wire.uncertainties else wire.status
    warnings = list(wire.warnings)
    issues = [issue[:500] for issue in wire.issues if issue.strip()]
    if wire.status == WorkStatus.correct and issues:
        status = WorkStatus.partial
        warnings.append("Tutor status was adjusted because its grading evidence conflicted.")

    if raw_actions and not actions:
        fallback_text = next(iter(issues), wire.summary or "")
        if fallback_text:
            position = {"x": 0.5, "y": 0.5}
            if wire.uncertainties:
                position = {
                    "x": wire.uncertainties[0].target.x,
                    "y": wire.uncertainties[0].target.y,
                }
            actions.append(
                TextAction(
                    type="text",
                    position=position,
                    text=fallback_text[:240],
                    purpose="safe_local_recovery",
                )
            )
    if dropped_actions:
        warnings.append("Some invalid tutor actions were omitted.")

    return (
        TutorAgentOutput(
            status=status,
            confidence=wire.confidence,
            observed_work=wire.observed_work,
            uncertainties=wire.uncertainties,
            issues=issues,
            canvas_actions=actions,
            summary=wire.summary,
            warnings=warnings[:20],
            learning_observations=[
                LearningObservation.model_validate(item.model_dump())
                for item in wire.learning_observations
            ],
            course_boundary=CourseBoundaryDecision.model_validate(
                wire.course_boundary.model_dump()
            ),
        ),
        locations,
    )


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
    pass


class TutorRateLimitError(TutorWorkflowError):
    pass


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
    ) -> TutorAgentOutput: ...


class AdkTutorWorkflow:
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
                http_status_codes=[408, 500, 502, 503, 504],
            ),
        )
        return LlmAgent(
            name="whiteboard_tutor",
            description="Reads student work and returns validated spatial feedback.",
            model=model,
            instruction=tutor_instruction(mode),
            output_schema=TutorWireOutput,
            output_key="tutor_result",
            generate_content_config=types.GenerateContentConfig(
                max_output_tokens=1_024,
                thinking_config=types.ThinkingConfig(
                    thinking_level=types.ThinkingLevel.MINIMAL
                ),
                media_resolution=types.MediaResolution.MEDIA_RESOLUTION_MEDIUM,
            ),
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
    ) -> TutorAgentOutput:
        started = time.perf_counter()
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
                round((time.perf_counter() - started) * 1_000),
            )
            return result
        except (ValidationError, ValueError, KeyError) as exc:
            fields = (
                ",".join(_validation_locations(exc))
                if isinstance(exc, ValidationError)
                else type(exc).__name__
            )
            logger.warning(
                "tutor.trace stage=workflow_output_invalid interaction_id=%s "
                "mode=%s fields=%s",
                interaction_id,
                mode.value,
                fields,
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
    ) -> TutorAgentOutput:
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
        parts.append(
            types.Part.from_text(
                text="Structured tutor context:\n"
                + json.dumps(context, separators=(",", ":"), default=str)
            )
        )
        async for _event in runner.run_async(
            user_id=user_id,
            session_id=interaction_id,
            new_message=types.Content(role="user", parts=parts),
        ):
            pass

        session = await session_service.get_session(
            app_name=APP_NAME,
            user_id=user_id,
            session_id=interaction_id,
        )
        if session is None:
            raise ValueError("ADK session was not available after workflow completion")
        result, locations = validate_tutor_output(session.state.get("tutor_result"))
        if locations:
            logger.warning(
                "tutor.trace stage=workflow_output_recovered interaction_id=%s "
                "mode=%s fields=%s",
                interaction_id,
                mode.value,
                ",".join(locations),
            )
        return result
