"""Deterministic builders for tutor tests.

Every builder returns the *smallest valid* value for its type and takes
keyword overrides for the one field a test cares about. Tests should read as
"a plan whose status is uncertain", never as a wall of boilerplate.
"""

from __future__ import annotations

from app.schemas.tutor import CanvasAction, NormalizedBounds, TutorPlan, WorkStatus

# --- image bytes -----------------------------------------------------------
# Real magic numbers: the API sniffs content rather than trusting the client's
# declared Content-Type, so these must be genuine signatures.

PNG = (
    b"\x89PNG\r\n\x1a\n"
    b"\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
    b"\x00\x00\x00\rIDAT\x08\xd7c\xf8\xcf\xc0\xf0\x1f\x00\x05\x00\x01\xff"
    b"\x89\x99=\x1d\x00\x00\x00\x00IEND\xaeB`\x82"
)
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 32
WEBP = b"RIFF" + b"\x00\x00\x00\x00" + b"WEBP" + b"\x00" * 32
NOT_AN_IMAGE = b"%PDF-1.7\n" + b"\x00" * 32


def bounds(x: float = 0.2, y: float = 0.3, width: float = 0.2, height: float = 0.1) -> dict:
    return {"x": x, "y": y, "width": width, "height": height}


def text_action(text: str = "What happens to the exponent?", **over) -> dict:
    return {"type": "text", "position": {"x": 0.4, "y": 0.3}, "text": text, **over}


def circle_action(**over) -> dict:
    return {"type": "circle", "target": bounds(), **over}


def check_action(**over) -> dict:
    return {"type": "check", "target": bounds(), **over}


def cross_action(**over) -> dict:
    return {"type": "cross", "target": bounds(), **over}


def plan(
    *,
    status: WorkStatus | str = WorkStatus.partial,
    actions: list[dict] | None = None,
    summary: str | None = "A restrained power-rule hint.",
) -> TutorPlan:
    """A model-produced plan, already validated."""
    return TutorPlan.model_validate(
        {
            "status": status,
            "canvas_actions": [circle_action()] if actions is None else actions,
            "summary": summary,
        }
    )


def normalized_bounds(**over) -> NormalizedBounds:
    return NormalizedBounds.model_validate(bounds(**over))


def action_types(actions: list[CanvasAction]) -> list[str]:
    """Readable assertion helper: ['text', 'circle'] instead of object reprs."""
    return [action.type for action in actions]


class StubWorkflow:
    """Implements the TutorWorkflow port without touching a provider.

    Records the call so tests can assert on what the service asked for, which
    is the only thing the service is actually responsible for.
    """

    def __init__(self, result: TutorPlan | None = None, error: Exception | None = None):
        self._result = result if result is not None else plan()
        self._error = error
        self.calls: list[dict] = []

    async def run(self, **kwargs) -> TutorPlan:
        self.calls.append(kwargs)
        if self._error is not None:
            raise self._error
        return self._result

    @property
    def last_call(self) -> dict:
        assert self.calls, "workflow was never invoked"
        return self.calls[-1]
