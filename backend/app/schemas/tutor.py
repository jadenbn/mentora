"""Validated contracts for multimodal tutor analysis and canvas rendering."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Annotated, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    """Reject fields that are not part of the published API contract."""

    model_config = ConfigDict(extra="forbid")


class TutorMode(str, Enum):
    mark = "mark"
    hint = "hint"
    explain = "explain"
    stuck = "stuck"


class TutorTrigger(str, Enum):
    manual = "manual"
    live = "live"
    voice = "voice"


class ShapeOwner(str, Enum):
    system = "system"
    student = "student"
    ai = "ai"


class WorkStatus(str, Enum):
    correct = "correct"
    incorrect = "incorrect"
    partial = "partial"
    uncertain = "uncertain"


class NormalizedPoint(StrictModel):
    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)


class NormalizedBounds(NormalizedPoint):
    width: float = Field(gt=0, le=1)
    height: float = Field(gt=0, le=1)

    @model_validator(mode="after")
    def remain_inside_image(self) -> "NormalizedBounds":
        if self.x + self.width > 1 or self.y + self.height > 1:
            raise ValueError("normalized bounds must remain inside the canvas image")
        return self


class Viewport(StrictModel):
    x: float
    y: float
    width: float = Field(gt=0)
    height: float = Field(gt=0)
    zoom: float = Field(gt=0)


class CanvasShape(StrictModel):
    id: str = Field(min_length=1, max_length=200)
    owner: ShapeOwner
    shape_type: str = Field(min_length=1, max_length=80)
    bounds: NormalizedBounds | None = None
    text: str | None = Field(default=None, max_length=2_000)
    latex: str | None = Field(default=None, max_length=2_000)


class CanvasContext(StrictModel):
    image_width: int = Field(gt=0, le=16_384)
    image_height: int = Field(gt=0, le=16_384)
    viewport: Viewport | None = None
    shapes: list[CanvasShape] = Field(default_factory=list, max_length=2_000)

    @model_validator(mode="after")
    def shape_ids_are_unique(self) -> "CanvasContext":
        shape_ids = [shape.id for shape in self.shapes]
        if len(shape_ids) != len(set(shape_ids)):
            raise ValueError("canvas shape ids must be unique")
        return self


class AiSelection(StrictModel):
    shape_ids: list[str] = Field(default_factory=list, max_length=200)
    bounds: NormalizedBounds


class ProblemContext(StrictModel):
    prompt_text: str = Field(min_length=1, max_length=20_000)
    solution_reference: str | None = Field(default=None, max_length=10_000)
    latex_blocks: list[str] = Field(default_factory=list, max_length=100)
    topic: str | None = Field(default=None, max_length=200)
    difficulty: str | None = Field(default=None, max_length=80)
    expected_skills: list[str] = Field(default_factory=list, max_length=50)
    source: Literal["generated", "imported", "manual"] = "manual"


class CourseMetadata(StrictModel):
    name: str | None = Field(default=None, max_length=300)
    covered_topics: list[str] = Field(default_factory=list, max_length=500)
    not_yet_covered_topics: list[str] = Field(default_factory=list, max_length=500)
    notation_summary: str | None = Field(default=None, max_length=5_000)
    instructor_style_summary: str | None = Field(default=None, max_length=5_000)


class PriorTutorInteraction(StrictModel):
    interaction_id: str = Field(min_length=1, max_length=200)
    mode: TutorMode
    summary: str = Field(max_length=1_000)
    created_at: datetime | None = None


class StudentModelSnapshot(StrictModel):
    attempted_topics: list[str] = Field(default_factory=list, max_length=500)
    recurring_mistakes: list[str] = Field(default_factory=list, max_length=500)
    strengths: list[str] = Field(default_factory=list, max_length=500)
    total_hints_used: int | None = Field(default=None, ge=0)


class ClientCapabilities(StrictModel):
    supported_actions: list[
        Literal[
            "text",
            "math",
            "arrow",
            "circle",
            "underline",
            "highlight",
            "check",
            "cross",
        ]
    ] = Field(default_factory=list)
    supports_latex: bool = True
    supports_selection_crop: bool = False


class TutorRequest(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    request_id: UUID
    user_id: str = Field(min_length=1, max_length=200)
    course_id: str = Field(min_length=1, max_length=200)
    session_id: str = Field(min_length=1, max_length=200)
    problem_id: str = Field(min_length=1, max_length=200)
    mode: TutorMode
    trigger: TutorTrigger = TutorTrigger.manual
    problem: ProblemContext
    course: CourseMetadata = Field(default_factory=CourseMetadata)
    canvas: CanvasContext
    selection: AiSelection | None = None
    recent_interactions: list[PriorTutorInteraction] = Field(
        default_factory=list, max_length=20
    )
    student_model: StudentModelSnapshot | None = None
    transcript: str | None = Field(default=None, max_length=4_000)
    instruction: str | None = Field(default=None, max_length=4_000)
    locale: str = Field(default="en", min_length=2, max_length=35)
    timezone: str | None = Field(default=None, max_length=100)
    client_capabilities: ClientCapabilities = Field(
        default_factory=ClientCapabilities
    )

    @model_validator(mode="after")
    def selected_shapes_exist(self) -> "TutorRequest":
        if not self.selection:
            return self
        known_ids = {shape.id for shape in self.canvas.shapes}
        unknown_ids = set(self.selection.shape_ids) - known_ids
        if unknown_ids:
            raise ValueError("selection references unknown canvas shape ids")
        return self


class CanvasActionBase(StrictModel):
    action_id: str = Field(
        default_factory=lambda: uuid4().hex, min_length=1, max_length=64
    )
    purpose: str | None = Field(default=None, max_length=160)


class TextAction(CanvasActionBase):
    type: Literal["text"]
    position: NormalizedPoint
    text: str = Field(min_length=1, max_length=240)


class MathAction(CanvasActionBase):
    type: Literal["math"]
    position: NormalizedPoint
    latex: str = Field(min_length=1, max_length=500)


class ArrowAction(CanvasActionBase):
    type: Literal["arrow"]
    start: NormalizedPoint
    end: NormalizedPoint
    label: str | None = Field(default=None, max_length=80)


class TargetActionBase(CanvasActionBase):
    target: NormalizedBounds
    label: str | None = Field(default=None, max_length=80)


class CircleAction(TargetActionBase):
    type: Literal["circle"]


class UnderlineAction(TargetActionBase):
    type: Literal["underline"]


class HighlightAction(TargetActionBase):
    type: Literal["highlight"]


class CheckAction(TargetActionBase):
    type: Literal["check"]


class CrossAction(TargetActionBase):
    type: Literal["cross"]


CanvasAction = Annotated[
    TextAction
    | MathAction
    | ArrowAction
    | CircleAction
    | UnderlineAction
    | HighlightAction
    | CheckAction
    | CrossAction,
    Field(discriminator="type"),
]


class CourseBoundaryDecision(StrictModel):
    requires_confirmation: bool = False
    technique: str | None = Field(default=None, max_length=200)
    message: str | None = Field(default=None, max_length=500)
    alternatives_available: bool = False

    @model_validator(mode="after")
    def confirmation_has_explanation(self) -> "CourseBoundaryDecision":
        if self.requires_confirmation and (not self.technique or not self.message):
            raise ValueError(
                "course boundary confirmation requires a technique and message"
            )
        return self


class LearningObservationType(str, Enum):
    strength = "strength"
    mistake = "mistake"
    progress = "progress"
    help_usage = "help_usage"


class LearningObservation(StrictModel):
    type: LearningObservationType
    topic: str = Field(min_length=1, max_length=200)
    skill: str = Field(min_length=1, max_length=200)
    outcome: WorkStatus
    evidence: str = Field(min_length=1, max_length=500)
    mistake_tag: str | None = Field(default=None, max_length=120)
    confidence: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def mistakes_are_not_uncertain(self) -> "LearningObservation":
        if self.type == LearningObservationType.mistake and (
            self.outcome == WorkStatus.uncertain or self.confidence < 0.6
        ):
            raise ValueError("mistake observations require confidence of at least 0.6")
        return self


class GroundingReference(StrictModel):
    filename: str = Field(min_length=1, max_length=500)
    page: int = Field(ge=0)
    score: float


class LearningEvent(LearningObservation):
    schema_version: Literal["1.0"] = "1.0"
    event_id: str = Field(default_factory=lambda: uuid4().hex)
    interaction_id: str
    request_id: UUID
    user_id: str
    course_id: str
    session_id: str
    problem_id: str
    tutor_mode: TutorMode
    trigger: TutorTrigger
    difficulty: str | None = None
    occurred_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


class LearningDeliveryStatus(str, Enum):
    queued = "queued"
    disabled = "disabled"
    failed = "failed"


class LearningDelivery(StrictModel):
    status: LearningDeliveryStatus
    event_count: int = Field(ge=0)


class LearningWebhookEnvelope(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    interaction_id: str
    events: list[LearningEvent]


class TutorResponse(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    interaction_id: str
    request_id: UUID
    status: WorkStatus
    confidence: float = Field(ge=0, le=1)
    canvas_actions: list[CanvasAction] = Field(default_factory=list, max_length=12)
    summary: str | None = None
    grounding_references: list[GroundingReference] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    course_boundary: CourseBoundaryDecision = Field(
        default_factory=CourseBoundaryDecision
    )
    learning_events: list[LearningEvent] = Field(default_factory=list)
    learning_delivery: LearningDelivery
