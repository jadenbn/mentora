"""Deterministic tests for the public tutor API contract."""

from __future__ import annotations

import unittest
from uuid import uuid4

from pydantic import TypeAdapter, ValidationError

from app.schemas.tutor import (
    CanvasAction,
    CanvasContext,
    CourseMetadata,
    NormalizedBounds,
    ProblemContext,
    TutorRequest,
)


ACTION_ADAPTER = TypeAdapter(CanvasAction)


def valid_request_data() -> dict:
    return {
        "request_id": str(uuid4()),
        "user_id": "user_1",
        "course_id": "course_1",
        "session_id": "session_1",
        "problem_id": "problem_1",
        "mode": "hint",
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
                    "id": "problem",
                    "owner": "system",
                    "shape_type": "text",
                    "text": "Differentiate f(x) = x^2.",
                    "bounds": {"x": 0.1, "y": 0.1, "width": 0.3, "height": 0.1},
                },
                {
                    "id": "student_step",
                    "owner": "student",
                    "shape_type": "draw",
                    "bounds": {"x": 0.2, "y": 0.35, "width": 0.2, "height": 0.1},
                },
                {
                    "id": "old_hint",
                    "owner": "ai",
                    "shape_type": "text",
                    "text": "Recall the power rule",
                    "bounds": {"x": 0.5, "y": 0.35, "width": 0.2, "height": 0.1},
                },
            ],
        },
        "selection": {
            "shape_ids": ["student_step"],
            "bounds": {"x": 0.2, "y": 0.35, "width": 0.2, "height": 0.1},
        },
    }


class TutorSchemaTests(unittest.TestCase):
    def test_problem_solution_reference_is_optional_and_backward_compatible(self) -> None:
        without_reference = TutorRequest.model_validate(valid_request_data())
        self.assertIsNone(without_reference.problem.solution_reference)

        with_reference = without_reference.model_copy(
            update={
                "problem": without_reference.problem.model_copy(
                    update={
                        "solution_reference": (
                            "4(3x² + 1)³(6x) and 24x(3x² + 1)³ are equivalent."
                        )
                    }
                )
            }
        )
        self.assertIn("equivalent", with_reference.problem.solution_reference or "")

    def test_accepts_context_with_all_shape_owners(self) -> None:
        request = TutorRequest.model_validate(valid_request_data())

        self.assertEqual(
            {shape.owner.value for shape in request.canvas.shapes},
            {"system", "student", "ai"},
        )

    def test_rejects_bounds_outside_image(self) -> None:
        with self.assertRaises(ValidationError):
            NormalizedBounds(x=0.9, y=0.2, width=0.2, height=0.1)

    def test_rejects_unknown_selected_shape(self) -> None:
        payload = valid_request_data()
        payload["selection"]["shape_ids"] = ["does_not_exist"]

        with self.assertRaises(ValidationError):
            TutorRequest.model_validate(payload)

    def test_rejects_duplicate_shape_ids(self) -> None:
        payload = valid_request_data()
        duplicate = payload["canvas"]["shapes"][0].copy()
        payload["canvas"]["shapes"].append(duplicate)

        with self.assertRaises(ValidationError):
            TutorRequest.model_validate(payload)

    def test_validates_each_canvas_action_shape(self) -> None:
        actions = [
            ACTION_ADAPTER.validate_python(action)
            for action in [
                {
                    "type": "text",
                    "position": {"x": 0.4, "y": 0.4},
                    "text": "Check the exponent.",
                },
                {
                    "type": "arrow",
                    "start": {"x": 0.5, "y": 0.4},
                    "end": {"x": 0.35, "y": 0.38},
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
            ]
        ]

        self.assertEqual([action.type for action in actions], ["text", "arrow", "circle"])

    def test_rejects_action_with_wrong_fields(self) -> None:
        with self.assertRaises(ValidationError):
            ACTION_ADAPTER.validate_python(
                {"type": "math", "position": {"x": 0.3, "y": 0.4}, "text": "2x"}
            )


class TutorSchemaConstructionTests(unittest.TestCase):
    def test_core_context_models_are_independently_reusable(self) -> None:
        canvas = CanvasContext(image_width=100, image_height=100)
        problem = ProblemContext(prompt_text="Solve x + 1 = 2")
        course = CourseMetadata(name="Algebra")

        self.assertEqual(canvas.shapes, [])
        self.assertEqual(problem.source, "manual")
        self.assertEqual(course.name, "Algebra")


if __name__ == "__main__":
    unittest.main()
