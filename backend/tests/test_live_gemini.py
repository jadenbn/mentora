"""Opt-in end-to-end check against the real provider.

Not part of the default run: it costs a real request and needs a real key.

    RUN_LIVE_GEMINI=1 .venv/bin/python -m pytest -q -m live -s
"""

from __future__ import annotations

import asyncio
import base64
import os
import time
from pathlib import Path

import pytest

from app.config import TutorSettings
from app.schemas.tutor import TutorMode, WorkStatus

pytestmark = pytest.mark.live

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def canvas() -> bytes:
    return base64.b64decode((FIXTURES / "calculus_canvas.png.b64").read_text())


@pytest.fixture
def workflow():
    if not os.getenv("RUN_LIVE_GEMINI"):
        pytest.skip("set RUN_LIVE_GEMINI=1 to spend a real provider request")
    from app.agents.tutor_workflow import GeminiTutorWorkflow

    settings = TutorSettings.from_environment()
    return GeminiTutorWorkflow(
        api_key=settings.gemini_api_key,
        model=settings.gemini_model,
        timeout_seconds=60,
    )


def test_a_real_request_returns_a_renderable_plan(workflow, canvas):
    started = time.perf_counter()
    plan = asyncio.run(
        workflow.run(
            mode=TutorMode.hint,
            canvas_image=canvas,
            canvas_mime_type="image/png",
            prior_annotations=[],
        )
    )
    elapsed = time.perf_counter() - started

    assert isinstance(plan.status, WorkStatus)
    assert all(a.type in {"text", "circle", "check", "cross"} for a in plan.canvas_actions)
    print(f"\nlive plan in {elapsed:.2f}s: {plan.model_dump_json(indent=2)}")


def test_a_real_request_stays_within_interactive_latency(workflow, canvas):
    # Not a hard SLA, but a regression here means the tutor stopped feeling
    # interactive, which is the whole product.
    started = time.perf_counter()
    asyncio.run(
        workflow.run(
            mode=TutorMode.mark,
            canvas_image=canvas,
            canvas_mime_type="image/png",
            prior_annotations=[],
        )
    )
    assert time.perf_counter() - started < 20
