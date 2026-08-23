"""Shared deterministic inputs and fakes for tutor tests."""

from __future__ import annotations

from uuid import uuid4

from app.agents.tutor_workflow import TutorWorkflowResult
from app.schemas.tutor import CanvasAnalysis, LearningObservation, TutorPlan, TutorRequest


PNG_BYTES = (
    b"\x89PNG\r\n\x1a\n"
    b"\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
    b"\x00\x00\x00\rIDAT\x08\xd7c\xf8\xcf\xc0\xf0\x1f\x00\x05\x00\x01\xff"
    b"\x89\x99=\x1d\x00\x00\x00\x00IEND\xaeB`\x82"
)


def tutor_request(*, mode: str = "hint") -> TutorRequest:
    return TutorRequest.model_validate(
        {
            "request_id": str(uuid4()),
            "user_id": "user_1",
            "course_id": "course_1",
            "session_id": "session_1",
            "problem_id": "problem_1",
            "mode": mode,
            "problem": {
                "prompt_text": "Differentiate f(x) = x^2.",
                "topic": "derivatives",
                "difficulty": "easy",
                "expected_skills": ["power rule"],
            },
            "course": {
                "name": "Calculus I",
                "covered_topics": ["power rule"],
            },
            "canvas": {
                "image_width": 1200,
                "image_height": 800,
                "shapes": [
                    {
                        "id": "student_step",
                        "owner": "student",
                        "shape_type": "text",
                        "text": "f'(x) = x",
                        "bounds": {
                            "x": 0.2,
                            "y": 0.35,
                            "width": 0.2,
                            "height": 0.1,
                        },
                    },
                    {
                        "id": "old_hint",
                        "owner": "ai",
                        "shape_type": "text",
                        "text": "The AI said 2x",
                        "bounds": {
                            "x": 0.5,
                            "y": 0.35,
                            "width": 0.2,
                            "height": 0.1,
                        },
                    },
                ],
            },
            "selection": {
                "shape_ids": ["student_step"],
                "bounds": {"x": 0.2, "y": 0.35, "width": 0.2, "height": 0.1},
            },
        }
    )


def workflow_result(
    *,
    status: str = "partial",
    learning_observations: list[LearningObservation] | None = None,
) -> TutorWorkflowResult:
    return TutorWorkflowResult(
        analysis=CanvasAnalysis.model_validate(
            {
                "status": status,
                "confidence": 0.9,
                "current_work_summary": "The student omitted the power-rule coefficient.",
                "issues": ["Missing coefficient 2"],
                "learning_observations": learning_observations or [],
            }
        ),
        plan=TutorPlan.model_validate(
            {
                "status": status,
                "confidence": 0.88,
                "canvas_actions": [
                    {
                        "type": "text",
                        "position": {"x": 0.43, "y": 0.35},
                        "text": "What happens to the exponent?",
                    },
                    {
                        "type": "circle",
                        "target": {
                            "x": 0.2,
                            "y": 0.35,
                            "width": 0.2,
                            "height": 0.1,
                        },
                    },
                ],
                "summary": "A restrained power-rule hint.",
            }
        ),
    )


def retrieval_results() -> list[dict]:
    return [
        {
            "text": "For x^n, use d/dx x^n = n x^(n-1).",
            "filename": "lecture-3.pdf",
            "page": 4,
            "document_type": "lecture",
            "score": 0.94,
        }
    ]
