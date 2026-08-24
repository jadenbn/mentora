"""Turn a graded tutor response into the fields record_attempt needs.

The tutor grades a canvas; the learning engine records a per-skill attempt.
Nothing else in this codebase bridges the two, so this module is that
bridge — a pure function, no DB, no provider call.

This branch forked before app.schemas.tutor existed, so _TutorStatus below
mirrors WorkStatus's four values under the tutor module's own names instead
of importing it. Delete _TutorStatus and import app.schemas.tutor.WorkStatus
once the branches share a history.

Known gap: TutorResponse carries no signal finer than correct / incorrect /
partial / uncertain — no conceptual/procedural/careless distinction. Every
incorrect attempt is conservatively tagged CONCEPTUAL_ERROR below. Real
misconception granularity needs the tutor's single model call to emit it
directly (extending TutorPlan, not a second round trip) — that is a change
to app/schemas/tutor.py and app/prompts/tutor.py, owned by whoever maintains
the tutor path, not something to add from here.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from app.models.enums import MisconceptionTag
from app.schemas.learning import ErrorReport


class _TutorStatus(str, Enum):
    """Mirrors app.schemas.tutor.WorkStatus. See module docstring."""

    correct = "correct"
    incorrect = "incorrect"
    partial = "partial"
    uncertain = "uncertain"


@dataclass(frozen=True)
class AttemptGrading:
    """The subset of AttemptCreate that a graded tutor response determines.

    A caller merges this with the request-level fields the tutor response
    can't know (student_id, session_id, problem_id, difficulty, hints_used,
    total_time_ms) to build an AttemptCreate for POST /attempts.
    """

    correct: bool
    partial: bool
    errors: list[ErrorReport]


def to_attempt_grading(
    status: _TutorStatus, expected_skills: list[str]
) -> AttemptGrading | None:
    """None means: do not record this as an attempt.

    Only "uncertain" returns None — the tutor never actually graded the
    canvas there (see app/services/tutor_policy.py on main), so there is
    nothing to feed the student model.
    """
    if status == _TutorStatus.uncertain:
        return None

    if status == _TutorStatus.correct:
        return AttemptGrading(correct=True, partial=False, errors=[])

    if status == _TutorStatus.partial:
        return AttemptGrading(
            correct=False,
            partial=True,
            errors=[
                ErrorReport(skill_id=skill_id, misconception=MisconceptionTag.INCOMPLETE)
                for skill_id in expected_skills
            ],
        )

    return AttemptGrading(
        correct=False,
        partial=False,
        errors=[
            ErrorReport(skill_id=skill_id, misconception=MisconceptionTag.CONCEPTUAL_ERROR)
            for skill_id in expected_skills
        ],
    )
