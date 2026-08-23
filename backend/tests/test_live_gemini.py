"""Opt-in provider test; excluded unless explicitly enabled by a developer."""

from __future__ import annotations

import asyncio
import base64
import json
import os
from pathlib import Path

import pytest
from dotenv import load_dotenv

from app.agents.tutor_workflow import AdkTutorWorkflow
from app.schemas.tutor import TutorMode


FIXTURES = Path(__file__).parent / "fixtures"
load_dotenv(Path(__file__).parents[1] / ".env")


@pytest.mark.live
@pytest.mark.skipif(
    os.getenv("RUN_LIVE_GEMINI_TEST") != "1" or not os.getenv("GEMINI_API_KEY"),
    reason="set RUN_LIVE_GEMINI_TEST=1 and GEMINI_API_KEY to call Gemini",
)
def test_live_gemini_returns_validated_analysis_and_actions() -> None:
    context = json.loads((FIXTURES / "calculus_context.json").read_text())
    image = base64.b64decode(
        (FIXTURES / "calculus_canvas.png.b64").read_text().strip()
    )
    workflow = AdkTutorWorkflow(
        model=os.getenv("GEMINI_MODEL", "gemini-3.7-flash"),
        timeout_seconds=90,
    )

    result = asyncio.run(
        workflow.run(
            interaction_id="live_test_interaction",
            user_id="live_test_user",
            mode=TutorMode.hint,
            context=context,
            canvas_image=image,
            canvas_mime_type="image/png",
            selection_image=None,
            selection_mime_type=None,
        )
    )

    assert 0 <= result.analysis.confidence <= 1
    assert 0 <= result.plan.confidence <= 1
    assert len(result.plan.canvas_actions) <= 12
