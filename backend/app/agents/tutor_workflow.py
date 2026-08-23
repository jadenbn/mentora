"""Two-stage Google ADK workflow for whiteboard interpretation and tutoring."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Protocol

from google.adk.agents import LlmAgent
from google.adk.models import Gemini
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.adk.workflow import START, Workflow
from google.genai import types
from pydantic import ValidationError

from app.prompts.tutor import CANVAS_ANALYST_INSTRUCTION, tutor_planner_instruction
from app.schemas.tutor import CanvasAnalysis, TutorMode, TutorPlan


APP_NAME = "mentora_tutor"


class TutorWorkflowError(RuntimeError):
    """Safe boundary for provider, timeout, and malformed-output errors."""


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
    """Runs specialist ADK agents sequentially with structured state handoff."""

    def __init__(self, *, model: str, timeout_seconds: float = 45) -> None:
        self.model = model
        self.timeout_seconds = timeout_seconds

    def _build_agent(self, mode: TutorMode) -> Workflow:
        model = Gemini(
            model=self.model,
            retry_options=types.HttpRetryOptions(
                attempts=3,
                initial_delay=0.5,
                max_delay=4,
                exp_base=2,
                jitter=0.2,
            ),
        )
        generation_config = types.GenerateContentConfig(
            temperature=0.2,
            max_output_tokens=8_192,
        )
        analyst = LlmAgent(
            name="canvas_analyst",
            description="Interprets student work and produces learning evidence.",
            model=model,
            instruction=CANVAS_ANALYST_INSTRUCTION,
            output_schema=CanvasAnalysis,
            output_key="canvas_analysis",
            generate_content_config=generation_config,
            disallow_transfer_to_parent=True,
            disallow_transfer_to_peers=True,
        )
        planner = LlmAgent(
            name="tutor_planner",
            description="Plans validated, spatial whiteboard tutor actions.",
            model=model,
            instruction=(
                tutor_planner_instruction(mode)
                + "\n\nValidated Canvas Analyst result:\n{canvas_analysis}"
            ),
            output_schema=TutorPlan,
            output_key="tutor_plan",
            generate_content_config=generation_config,
            disallow_transfer_to_parent=True,
            disallow_transfer_to_peers=True,
        )
        return Workflow(
            name="whiteboard_tutor_workflow",
            description="Analyzes the canvas, then plans restrained tutor feedback.",
            edges=[(START, analyst, planner)],
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
        last_error: Exception | None = None
        # ADK/Gemini performs transient HTTP retries. This second attempt is
        # specifically the bounded repair path for malformed structured output.
        for attempt in range(2):
            try:
                return await self._run_once(
                    interaction_id=f"{interaction_id}_{attempt}",
                    user_id=user_id,
                    mode=mode,
                    context=context,
                    canvas_image=canvas_image,
                    canvas_mime_type=canvas_mime_type,
                    selection_image=selection_image,
                    selection_mime_type=selection_mime_type,
                    repair_attempt=attempt == 1,
                )
            except (ValidationError, ValueError, KeyError, json.JSONDecodeError) as exc:
                last_error = exc
                continue
            except TimeoutError as exc:
                raise TutorWorkflowError("tutor workflow timed out") from exc
            except Exception as exc:
                raise TutorWorkflowError("tutor provider request failed") from exc
        raise TutorWorkflowError("tutor returned malformed structured output") from last_error

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
        repair_attempt: bool,
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
        request_text = (
            "This is a repair attempt. Return only data matching the supplied schema.\n"
            if repair_attempt
            else ""
        )
        request_text += "Structured tutor request and retrieved course context:\n"
        request_text += json.dumps(context, separators=(",", ":"), default=str)
        parts.append(types.Part.from_text(text=request_text))

        message = types.Content(role="user", parts=parts)
        async with asyncio.timeout(self.timeout_seconds):
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
        analysis = CanvasAnalysis.model_validate(session.state.get("canvas_analysis"))
        plan = TutorPlan.model_validate(session.state.get("tutor_plan"))
        return TutorWorkflowResult(analysis=analysis, plan=plan)
