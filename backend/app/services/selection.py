"""Pick what skill the next problem should target, and at what difficulty.

Read-only: nothing here writes state. It reads what attempt ingestion
recorded and derives a spec from it.

This module also owns `decayed_progress`, the as-of-now read of one skill's
state. Selection and the student-model report are the only two callers and
they must not drift: both need decayed mastery and an attempt count computed
the same way.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlmodel import Session, select

from app.models.attempt import Attempt
from app.models.skill import Skill
from app.models.skill_state import SkillState
from app.schemas.learning import GenerationSpec
from app.services.mastery import apply_decay, clamp

W_URGENCY = 0.60
W_STALENESS = 0.25
W_RECENCY_PENALTY = 0.40
UNLOCK_THRESHOLD = 0.60
REVIEW_MASTERY_MIN = 0.70
DIFFICULTY_OFFSET = 0.15
STALENESS_CAP_DAYS = 7.0

# Mastery assumed for a skill with no attempt history. Cold start is blind:
# there is no per-student prior, and pretending otherwise (an unwritten
# StudentProfile.global_ability) only hid that it was always this constant.
DEFAULT_MASTERY = 0.5

RECENT_WINDOW = 2  # how many recently-seen skills incur the recency penalty
REVIEW_LOOKBACK = 3  # consecutive weak picks before the review floor forces a break


def days_since(last_seen: datetime, now: datetime) -> float:
    """Days elapsed, defensive against naive datetimes from older rows."""
    if last_seen.tzinfo is None:
        last_seen = last_seen.replace(tzinfo=timezone.utc)
    return (now - last_seen).total_seconds() / 86400


@dataclass(frozen=True)
class SkillProgress:
    """One skill's state as of `now`, with read-time decay applied."""

    mastery: float
    attempts: int
    last_seen: datetime | None


def decayed_progress(state: SkillState | None, now: datetime) -> SkillProgress:
    if state is None:
        return SkillProgress(mastery=DEFAULT_MASTERY, attempts=0, last_seen=None)
    if state.last_seen is None:
        # Created by prerequisite bleed, never actually practised: it holds a
        # mastery estimate but has no last-seen moment to decay from.
        return SkillProgress(mastery=state.mastery, attempts=state.attempts, last_seen=None)
    return SkillProgress(
        mastery=apply_decay(state.mastery, days_since(state.last_seen, now)),
        attempts=state.attempts,
        last_seen=state.last_seen,
    )


def retrieval_query(skill: Skill) -> str:
    """Assemble a course-retrieval query from a skill.

    Name first -- highest-signal term; description supplies context; keywords
    supply the textbook's own vocabulary that the name may not use.
    """
    return " ".join([skill.name, skill.description, *skill.keywords])


def progress_by_skill(
    session: Session, skills: list[Skill], student_id: str, now: datetime
) -> dict[str, SkillProgress]:
    """Every skill's decayed progress, in one query rather than one per skill."""
    states = session.exec(
        select(SkillState).where(
            SkillState.student_id == student_id,
            SkillState.skill_id.in_([s.id for s in skills]),
        )
    ).all()
    by_id = {state.skill_id: state for state in states}
    return {skill.id: decayed_progress(by_id.get(skill.id), now) for skill in skills}


def _recent_primary_skills(
    session: Session, course_id: str, student_id: str, limit: int
) -> list[str]:
    """The primary (first declared) skill of the most recent attempts."""
    rows = session.exec(
        select(Attempt)
        .where(Attempt.course_id == course_id, Attempt.student_id == student_id)
        .order_by(Attempt.created_at.desc())
        .limit(limit)
    ).all()
    return [row.expected_skills[0] for row in rows if row.expected_skills]


def is_unlocked(skill: Skill, progress: dict[str, SkillProgress]) -> bool:
    """Every prerequisite present in the course is at or above the threshold."""
    return all(
        progress[p].mastery >= UNLOCK_THRESHOLD for p in skill.prereqs if p in progress
    )


def select_next(session: Session, course_id: str, student_id: str) -> GenerationSpec | None:
    now = datetime.now(timezone.utc)
    skills = session.exec(select(Skill).where(Skill.course_id == course_id)).all()
    if not skills:
        return None

    progress = progress_by_skill(session, list(skills), student_id, now)

    unlocked = [s for s in skills if is_unlocked(s, progress)]
    if not unlocked:
        return None

    recent = set(_recent_primary_skills(session, course_id, student_id, RECENT_WINDOW))

    def priority(skill: Skill) -> float:
        p = progress[skill.id]
        urgency = 1.0 - p.mastery
        staleness = (
            1.0
            if p.last_seen is None
            else min(days_since(p.last_seen, now) / STALENESS_CAP_DAYS, 1.0)
        )
        recency_penalty = W_RECENCY_PENALTY if skill.id in recent else 0.0
        return W_URGENCY * urgency + W_STALENESS * staleness - recency_penalty

    last_picks = _recent_primary_skills(session, course_id, student_id, REVIEW_LOOKBACK)
    forced_review = len(last_picks) == REVIEW_LOOKBACK and all(
        progress[skill_id].mastery < REVIEW_MASTERY_MIN
        for skill_id in last_picks
        if skill_id in progress
    )
    review_candidates = [s for s in unlocked if progress[s.id].mastery >= REVIEW_MASTERY_MIN]

    is_review = bool(forced_review and review_candidates)
    chosen = max(review_candidates if is_review else unlocked, key=priority)

    return GenerationSpec(
        skill_id=chosen.id,
        skill_name=chosen.name,
        skill_description=chosen.description,
        target_difficulty=clamp(progress[chosen.id].mastery + DIFFICULTY_OFFSET, 0.1, 0.9),
        avoid_forms=list(chosen.question_forms),
        retrieval_query=retrieval_query(chosen),
        is_review=is_review,
    )
