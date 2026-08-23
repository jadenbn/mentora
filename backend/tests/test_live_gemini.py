"""Opt-in provider test; excluded unless explicitly enabled by a developer."""

from __future__ import annotations

import asyncio
import base64
import json
import os
import time
from pathlib import Path

import pytest
from dotenv import load_dotenv

from app.agents.tutor_workflow import AdkTutorWorkflow, TutorWorkflowError
from app.schemas.tutor import TutorMode


FIXTURES = Path(__file__).parent / "fixtures"
load_dotenv(Path(__file__).parents[1] / ".env")


@pytest.mark.live
@pytest.mark.skipif(
    os.getenv("RUN_LIVE_GEMINI_TEST") != "1" or not os.getenv("GEMINI_API_KEY"),
    reason="set RUN_LIVE_GEMINI_TEST=1 and GEMINI_API_KEY to call Gemini",
)
@pytest.mark.parametrize(
    ("fixture_name", "student_text", "is_correct"),
    [
        ("chain_rule_wrong.png.b64", "y' = 4(3x² + 1)6x", False),
        ("chain_rule_correct.png.b64", "y' = 4(3x² + 1)³(6x)", True),
    ],
)
def test_live_gemini_grades_literal_chain_rule_notation(
    fixture_name: str,
    student_text: str,
    is_correct: bool,
) -> None:
    context = json.loads((FIXTURES / "calculus_context.json").read_text())
    context["request"]["canvas"]["shapes"][0]["text"] = student_text
    image = base64.b64decode((FIXTURES / fixture_name).read_text().strip())
    workflow = AdkTutorWorkflow(
        model=os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite"),
        timeout_seconds=90,
    )

    started_at = time.perf_counter()
    try:
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
    except TutorWorkflowError as exc:
        causes: list[str] = []
        cause: BaseException | None = exc
        while cause is not None:
            causes.append(str(cause))
            cause = cause.__cause__
        if any("RESOURCE_EXHAUSTED" in message for message in causes):
            elapsed_seconds = time.perf_counter() - started_at
            pytest.fail(
                "Gemini quota is exhausted; wait for reset or use a project "
                f"with available quota (failed after {elapsed_seconds:.2f}s)",
                pytrace=False,
            )
        raise
    elapsed_seconds = time.perf_counter() - started_at

    assert 0 <= result.confidence <= 1
    assert len(result.canvas_actions) <= 12
    if is_correct:
        assert result.status.value == "correct"
        assert all(action.type != "cross" for action in result.canvas_actions)
    else:
        assert result.status.value in {"partial", "incorrect"}
        assert "³" not in result.observed_work

    validation_summary = {
        "validation": "passed",
        "model": workflow.model,
        "elapsed_seconds": round(elapsed_seconds, 2),
        "result": result.model_dump(mode="json"),
        "checks": {
            "confidence_in_range": True,
            "canvas_action_count": len(result.canvas_actions),
            "canvas_action_limit": 12,
        },
    }
    print("\nValidated Gemini tutor result:")
    print(json.dumps(validation_summary, indent=2))
