"""The deterministic safety policy.

Model output passes through here before it reaches a canvas. Pure by design:
a plan in, a plan out, no request context and no I/O, so the rules are cheap
to state and impossible to route around.

Two rules, at the two ends of the confidence range. The tutor must not grade
work it cannot read, and it must not manufacture corrections for work that is
already finished.
"""

from __future__ import annotations

from app.schemas.tutor import TutorPlan, Uncertainty, WorkStatus

#: A whiteboard buried in annotations is worse feedback than none.
MAX_ACTIONS = 12

_CLARIFICATION = "I can't read this clearly — could you rewrite the step?"
_COMPLETE = "This looks complete."

#: Verdicts. Withheld when the canvas could not be read.
_GRADING_ACTIONS = {"check", "cross"}


def _clarification_summary(uncertainties: list[Uncertainty]) -> str:
    """Ask about the specific symbol when one is named, not the whole canvas."""
    if not uncertainties:
        return _CLARIFICATION
    return f"{uncertainties[0].description} Could you rewrite it?"[:240]


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
        summary = _clarification_summary(plan.uncertainties)

    elif status is WorkStatus.correct:
        # Finished work must not be argued with. Keep one check, drop every
        # corrective mark, and confirm in the navbar rather than inventing a
        # step on the canvas.
        checks = [a for a in actions if a.type == "check"][:1]
        actions = checks
        summary = summary or _COMPLETE

    return plan.model_copy(
        update={
            "status": status,
            "summary": summary,
            "canvas_actions": actions[:MAX_ACTIONS],
        }
    )
