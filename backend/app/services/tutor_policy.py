"""The deterministic safety policy.

Model output passes through here before it reaches a canvas. Pure by design:
a plan in, a plan out, no request context and no I/O, so the rules are cheap
to state and impossible to route around.
"""

from __future__ import annotations

from app.schemas.tutor import TextAction, TutorPlan, WorkStatus

#: A whiteboard buried in annotations is worse feedback than none.
MAX_ACTIONS = 12

#: Where a clarification request goes when there is nowhere better.
_CANVAS_CENTRE = {"x": 0.5, "y": 0.5}

_CLARIFICATION = "I can't read this clearly — could you rewrite the step?"

#: Verdicts. Withheld when the canvas could not be read.
_GRADING_ACTIONS = {"check", "cross"}


def apply_safety_policy(plan: TutorPlan) -> TutorPlan:
    """Return a plan that is safe to render."""
    actions = list(plan.canvas_actions)

    if plan.status is WorkStatus.uncertain:
        actions = [a for a in actions if a.type not in _GRADING_ACTIONS]
        if not actions:
            actions = [
                TextAction(type="text", position=_CANVAS_CENTRE, text=_CLARIFICATION)
            ]

    return plan.model_copy(update={"canvas_actions": actions[:MAX_ACTIONS]})
