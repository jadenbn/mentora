"""A decayed, as-of-now view of one student's state on one skill.

Both selection (choosing what to serve next) and student_model_service
(reporting what a student knows) need the same thing: current mastery with
read-time decay applied, attempt count, and misconceptions ranked by
frequency. Computed here once so the two call sites can't drift.
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.models.skill_state import SkillState
from app.services.mastery import apply_decay


def days_since(last_seen: datetime, now: datetime) -> float:
    """Days elapsed, defensive against naive datetimes from older rows."""
    if last_seen.tzinfo is None:
        last_seen = last_seen.replace(tzinfo=timezone.utc)
    return (now - last_seen).total_seconds() / 86400


class SkillProgress:
    """Decayed mastery, attempts, and ranked misconceptions, as of `now`.

    `ranked_misconceptions` is the full (tag, count) list sorted by count
    descending, un-truncated: callers derive their own view of it (selection
    wants a single count-gated tag; a report wants the top few, ungated).
    """

    def __init__(self, state: SkillState | None, default_mastery: float, now: datetime):
        if state is None:
            self.mastery = default_mastery
            self.attempts = 0
            self.ranked_misconceptions: list[tuple[str, int]] = []
            self.last_seen: datetime | None = None
        else:
            self.mastery = apply_decay(state.mastery, days_since(state.last_seen, now))
            self.attempts = state.attempts
            self.ranked_misconceptions = sorted(
                state.misconception_counts.items(), key=lambda kv: -kv[1]
            )
            self.last_seen = state.last_seen
