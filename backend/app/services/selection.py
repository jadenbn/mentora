"""Pick what skill the next problem should target, and at what difficulty.

Read-only: nothing here writes state. It only reads what attempt ingestion
already recorded and derives a spec from it.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlmodel import Session, select

from app.models.attempt import Attempt
from app.models.skill import Skill
from app.models.skill_state import SkillState
from app.models.student_profile import StudentProfile
from app.schemas.learning import GenerationSpec
from app.services.mastery import apply_decay

W_URGENCY = 0.60
W_STALENESS = 0.25
W_RECENCY_PENALTY = 0.40
UNLOCK_THRESHOLD = 0.60
REVIEW_RATIO = 0.30
REVIEW_MASTERY_MIN = 0.70
DIFFICULTY_OFFSET = 0.15
MISCONCEPTION_MIN_COUNT = 3
STALENESS_CAP_DAYS = 7.0

RECENT_WINDOW = 2  # how many recently-seen skills incur the recency penalty
REVIEW_LOOKBACK = 3  # consecutive weak picks before the review floor forces a break


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _days_since(last_seen: datetime, now: datetime) -> float:
    if last_seen.tzinfo is None:
        last_seen = last_seen.replace(tzinfo=timezone.utc)
    return (now - last_seen).total_seconds() / 86400


class _SkillView:
    """Decayed mastery, attempt count, and top misconception for one skill."""

    def __init__(self, skill: Skill, state: SkillState | None, default_mastery: float, now: datetime):
        self.skill = skill
        if state is None:
            self.mastery = default_mastery
            self.attempts = 0
            self.top_misconception = None
            self.last_seen: datetime | None = None
        else:
            self.mastery = apply_decay(state.mastery, _days_since(state.last_seen, now))
            self.attempts = state.attempts
            top = sorted(state.misconception_counts.items(), key=lambda kv: -kv[1])
            self.top_misconception = top[0][0] if top and top[0][1] >= MISCONCEPTION_MIN_COUNT else None
            self.last_seen = state.last_seen


def _recent_primary_skills(session: Session, course_id: str, student_id: str, limit: int) -> list[str]:
    """The primary (first declared) skill of the most recent attempts."""
    rows = session.exec(
        select(Attempt)
        .where(Attempt.course_id == course_id, Attempt.student_id == student_id)
        .order_by(Attempt.created_at.desc())
        .limit(limit)
    ).all()
    return [row.expected_skills[0] for row in rows if row.expected_skills]


def select_next(session: Session, course_id: str, student_id: str) -> GenerationSpec | None:
    now = datetime.now(timezone.utc)
    skills = session.exec(select(Skill).where(Skill.course_id == course_id)).all()
    if not skills:
        return None

    profile = session.get(StudentProfile, (student_id, course_id))
    default_mastery = profile.global_ability if profile else 0.5

    views: dict[str, _SkillView] = {}
    for skill in skills:
        state = session.get(SkillState, (student_id, skill.id))
        views[skill.id] = _SkillView(skill, state, default_mastery, now)

    def is_unlocked(skill: Skill) -> bool:
        return all(views[p].mastery >= UNLOCK_THRESHOLD for p in skill.prereqs if p in views)

    unlocked = [s for s in skills if is_unlocked(s)]
    if not unlocked:
        return None

    recent = set(_recent_primary_skills(session, course_id, student_id, RECENT_WINDOW))

    def priority(skill: Skill) -> float:
        v = views[skill.id]
        urgency = 1.0 - v.mastery
        staleness = 1.0 if v.last_seen is None else min(
            _days_since(v.last_seen, now) / STALENESS_CAP_DAYS, 1.0
        )
        recency_penalty = W_RECENCY_PENALTY if skill.id in recent else 0.0
        return W_URGENCY * urgency + W_STALENESS * staleness - recency_penalty

    is_review = False
    last_picks = _recent_primary_skills(session, course_id, student_id, REVIEW_LOOKBACK)
    forced_review = len(last_picks) == REVIEW_LOOKBACK and all(
        views[skill_id].mastery < REVIEW_MASTERY_MIN for skill_id in last_picks if skill_id in views
    )

    review_candidates = [s for s in unlocked if views[s.id].mastery >= REVIEW_MASTERY_MIN]
    if forced_review and review_candidates:
        chosen = max(review_candidates, key=priority)
        is_review = True
    else:
        chosen = max(unlocked, key=priority)

    view = views[chosen.id]
    target_difficulty = _clamp(view.mastery + DIFFICULTY_OFFSET, 0.1, 0.9)
    prereq_mastery = {p: views[p].mastery for p in chosen.prereqs if p in views}

    return GenerationSpec(
        skill_id=chosen.id,
        skill_name=chosen.name,
        skill_description=chosen.description,
        target_difficulty=target_difficulty,
        target_misconception=view.top_misconception,
        avoid_forms=[],  # populated once generation persists prompt text
        prereq_mastery=prereq_mastery,
        is_review=is_review,
    )
