"""The tutor wire contract.

Two kinds of action exist, because there are two things the tutor can do to a
canvas: say something at a point, or point at a region. Everything the model is
allowed to express is in this file, and nothing here can describe a tldraw
operation.

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


class NormalizedPoint(StrictModel):
    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)


class NormalizedBounds(NormalizedPoint):
    width: float = Field(gt=0, le=1)
    height: float = Field(gt=0, le=1)

    @model_validator(mode="after")
    def stays_inside_the_image(self) -> "NormalizedBounds":
        if self.x + self.width > 1 or self.y + self.height > 1:
            raise ValueError("bounds must stay inside the canvas image")
        return self


class TextAction(StrictModel):
    """Say something at a point."""

    type: Literal["text"]
    position: NormalizedPoint
    text: str = Field(min_length=1, max_length=240)


class TargetAction(StrictModel):
    """Point at a region.

    One class rather than three: circling, checking, and crossing differ only
    in what they draw, never in what they carry. A mark that also wanted to
    speak would be a text action next to it.
    """

    type: Literal["circle", "check", "cross"]
    target: NormalizedBounds


CanvasAction = Annotated[TextAction | TargetAction, Field(discriminator="type")]


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
    summary: str | None = Field(default=None, max_length=1_000)


class TutorPlan(_Feedback):
    """What the model produced. Untrusted until the safety policy has run."""

    uncertainties: list[Uncertainty] = Field(default_factory=list, max_length=20)


class TutorResponse(_Feedback):
    """What the server returns: a policy-checked plan under a server-minted id.

    Uncertainties do not appear here. The policy has already turned them into
    a question placed on the canvas, which is the only form the student needs.
    """

    interaction_id: str
