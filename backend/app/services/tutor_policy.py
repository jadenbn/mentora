"""The deterministic safety policy.

Model output passes through here before it reaches a canvas. Pure by design:
a plan in, a plan out, no request context and no I/O, so the rules are cheap
to state and impossible to route around.

Two rules, at the two ends of the confidence range. The tutor must not grade
work it cannot read, and it must not manufacture corrections for work that is
already finished.
"""

from __future__ import annotations

from app.schemas.tutor import TextAction, TutorPlan, Uncertainty, WorkStatus

#: A whiteboard buried in annotations is worse feedback than none.
MAX_ACTIONS = 12

#: Where feedback goes when nothing better is known.
_CANVAS_CENTRE = {"x": 0.5, "y": 0.5}

_CLARIFICATION = "I can't read this clearly — could you rewrite the step?"
_COMPLETE = "This looks complete."

#: Verdicts. Withheld when the canvas could not be read.
_GRADING_ACTIONS = {"check", "cross"}

#: Where a tag is meaningful. On a correct or unreadable answer it is model
#: noise -- there is nothing to have gotten wrong -- so the policy is the
#: one place that can't be routed around to keep it out of the record.
_TAGGABLE_STATUSES = {WorkStatus.incorrect, WorkStatus.partial}


def _clarification_action(uncertainties: list[Uncertainty]) -> TextAction:
    """Ask about the specific symbol when one is named, not the whole canvas."""
    if not uncertainties:
        return TextAction(type="text", position=_CANVAS_CENTRE, text=_CLARIFICATION)
    first = uncertainties[0]
    return TextAction(
        type="text",
        position={"x": first.target.x, "y": first.target.y},
        text=f"{first.description} Could you rewrite it?"[:240],
    )


def apply_safety_policy(plan: TutorPlan) -> TutorPlan:
    """Return a plan that is safe to render."""
    actions = list(plan.canvas_actions)
    status = plan.status
    summary = plan.summary

    # An unreadable symbol overrides whatever verdict the model claimed: it
    # cannot have graded a step it just said it could not read.
    if plan.uncertainties:
        status = WorkStatus.uncertain

    if status is WorkStatus.uncertain:
        actions = [a for a in actions if a.type not in _GRADING_ACTIONS]
        if not actions:
            actions = [_clarification_action(plan.uncertainties)]

    elif status is WorkStatus.correct:
        # Finished work must not be argued with. Keep one check, drop every
        # corrective mark, and confirm in words rather than inventing a step.
        checks = [a for a in actions if a.type == "check"][:1]
        spoken = next((a for a in actions if a.type == "text"), None)
        position = spoken.position.model_dump() if spoken else _CANVAS_CENTRE
        actions = checks + [
            TextAction(type="text", position=position, text=summary or _COMPLETE)
        ]

    error_tag = plan.error_tag if plan.status in _TAGGABLE_STATUSES else None

    return plan.model_copy(
        update={
            "status": status,
            "summary": summary,
            "canvas_actions": actions[:MAX_ACTIONS],
            "error_tag": error_tag,
        }
    )
