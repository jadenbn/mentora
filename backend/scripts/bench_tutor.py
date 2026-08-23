"""Measure tutor latency against a real canvas image.

    cd backend && PYTHONPATH=. .venv/bin/python scripts/bench_tutor.py [runs]

Spends one Gemini request per run. The free tier rate-limits aggressively, so
runs are spaced; a 429 surfaces as a failed run rather than a timing.
"""
from __future__ import annotations

import asyncio
import base64
import statistics
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from app.agents.tutor_workflow import GeminiTutorWorkflow  # noqa: E402
from app.config import TutorSettings  # noqa: E402
from app.schemas.tutor import TutorMode  # noqa: E402

FIXTURE = Path(__file__).resolve().parent.parent / "tests/fixtures/chain_rule_wrong.png.b64"
SPACING_SECONDS = 12


def main(runs: int = 3) -> None:
    image = base64.b64decode(FIXTURE.read_text())
    settings = TutorSettings.from_environment()
    workflow = GeminiTutorWorkflow(model=settings.gemini_model, timeout_seconds=90)
    print(f"model {settings.gemini_model}, {len(image)} byte canvas, {runs} runs\n")

    timings: list[float] = []
    for i in range(runs):
        if i:
            time.sleep(SPACING_SECONDS)
        started = time.perf_counter()
        try:
            plan = asyncio.run(
                workflow.run(
                    mode=TutorMode.mark,
                    canvas_image=image,
                    canvas_mime_type="image/png",
                    prior_annotations=[],
                )
            )
        except Exception as exc:
            print(f"  run {i + 1}: failed — {exc}")
            continue
        elapsed = time.perf_counter() - started
        timings.append(elapsed)
        print(f"  run {i + 1}: {elapsed:5.2f}s  {plan.status.value} / {len(plan.canvas_actions)} actions")

    if timings:
        print(f"\n  median {statistics.median(timings):.2f}s   min {min(timings):.2f}s   n={len(timings)}")


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 3)
