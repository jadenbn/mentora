"""The tutor wire contract.

Tutor prose belongs in ``summary``. Canvas actions only point at regions, so
the board stays clear while the navbar carries the chronological guidance.

Every coordinate is normalized to the submitted canvas image: x/y in [0, 1]
from the top-left. Conversion back to world space happens in exactly one place,
frontend/lib/annotations/renderCanvasActions.ts.
"""

from __future__ import annotations

from enum import Enum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    """Reject fields that are not part of the contract."""

    model_config = ConfigDict(extra="forbid")


class TutorMode(str, Enum):
    """The four buttons."""

    mark = "mark"
    hint = "hint"
    explain = "explain"
    stuck = "stuck"


class WorkStatus(str, Enum):
    correct = "correct"
    incorrect = "incorrect"
    partial = "partial"
    #: The canvas could not be read. Never graded — see services/tutor_policy.
    uncertain = "uncertain"


class NormalizedBounds(StrictModel):
    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)
    width: float = Field(gt=0, le=1)
    height: float = Field(gt=0, le=1)

    @model_validator(mode="after")
    def stays_inside_the_image(self) -> "NormalizedBounds":
        if self.x + self.width > 1 or self.y + self.height > 1:
            raise ValueError("bounds must stay inside the canvas image")
        return self


class TargetAction(StrictModel):
    """Point at or highlight a region.

    Visual actions never carry prose; guidance lives in the summary.
    """

    type: Literal["highlight", "circle", "check", "cross"]
    target: NormalizedBounds


CanvasAction = TargetAction


class Uncertainty(StrictModel):
    """One symbol the tutor could not read, and where it sits.

    Naming the symbol and its location is what lets the tutor ask about *that*
    step rather than shrugging at the whole canvas.
    """

    description: str = Field(min_length=1, max_length=240)
    target: NormalizedBounds


class _Feedback(StrictModel):
    """The verdict, what to draw, and what to say — shared by plan and response."""

    status: WorkStatus
    canvas_actions: list[CanvasAction] = Field(default_factory=list)
    summary: str = Field(min_length=1, max_length=240)


class TutorPlan(_Feedback):
    """What the model produced. Untrusted until the safety policy has run."""

    uncertainties: list[Uncertainty] = Field(default_factory=list, max_length=20)


class TutorResponse(_Feedback):
    """What the server returns: a policy-checked plan under a server-minted id.

    Uncertainties do not appear here. The policy has already turned them into
    concise navbar guidance and safe visual actions.
    """

    interaction_id: str
