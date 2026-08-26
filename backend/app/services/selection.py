"""Pick which topic a generated question should target, and how hard.

Read-only: nothing here writes state. Called from inside question generation
(app.api.questions) when the student did not name a topic themselves -- there
is no student-facing "next problem" surface. Topics are flat: no prerequisite
graph, no unlock gate. Gating on top of an ability estimate was what starved
the demo (an average student never clears a fixed threshold); a flat pool
scored by weakness and staleness does not have that failure mode.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlmodel import Session, select

from app.models.attempt import Attempt
from app.models.skill import Skill
from app.models.skill_state import SkillState
from app.services.accuracy import accuracy, days_since, has_signal

# A topic with no attempts yet: how much weight "we haven't seen this" gets
# against "we've seen this and it's weak". Deliberately smaller than a
# confirmed weakness, so breadth doesn't crowd out remediation.
W_COVERAGE = 0.20
W_WEAKNESS = 0.60
W_STALENESS = 0.25
W_RECENCY_PENALTY = 0.40
STALENESS_CAP_DAYS = 7.0

# Difficulty the model is asked to write at when the topic has enough
# attempts to trust its accuracy reading; otherwise a moderate default.
DIFFICULTY_FLOOR = 0.15
DIFFICULTY_CEIL = 0.85
DEFAULT_DIFFICULTY = 0.5

RECENT_PICKS_WINDOW = 2  # how many recently-served topics incur the recency penalty


@dataclass(frozen=True)
class TopicPick:
    skill_id: str
    skill_name: str
    skill_description: str
    target_difficulty: float
    question_forms: list[str]


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


def _target_difficulty(state: SkillState | None) -> float:
    if state is None or not has_signal(state.attempts):
        return DEFAULT_DIFFICULTY
    a = accuracy(state.recent_outcomes)
    return DEFAULT_DIFFICULTY if a is None else min(max(a, DIFFICULTY_FLOOR), DIFFICULTY_CEIL)


def pick_topic(session: Session, course_id: str, student_id: str) -> TopicPick | None:
    """The topic a question should target next, or None if the course has
    no topics yet (a fresh course with no generated question to piggyback on)."""
    skills = session.exec(select(Skill).where(Skill.course_id == course_id)).all()
    if not skills:
        return None

    now = datetime.now(timezone.utc)
    states = session.exec(
        select(SkillState).where(
            SkillState.student_id == student_id,
            SkillState.skill_id.in_([s.id for s in skills]),
        )
    ).all()
    state_by_id = {state.skill_id: state for state in states}
    recent = set(_recent_primary_skills(session, course_id, student_id, RECENT_PICKS_WINDOW))

    def priority(skill: Skill) -> float:
        state = state_by_id.get(skill.id)
        if state is None or not state.recent_outcomes:
            base = W_COVERAGE
        else:
            weakness = 1.0 - (accuracy(state.recent_outcomes) or 0.5)
            staleness = (
                0.0
                if state.last_seen is None
                else min(days_since(state.last_seen, now) / STALENESS_CAP_DAYS, 1.0)
            )
            base = W_WEAKNESS * weakness + W_STALENESS * staleness
        return base - (W_RECENCY_PENALTY if skill.id in recent else 0.0)

    def rank(skill: Skill) -> tuple[float, float]:
        # Ties break toward the easier topic -- on a student's first
        # question every topic scores exactly W_COVERAGE.
        return (priority(skill), -skill.difficulty_band)

    chosen = max(skills, key=rank)
    return TopicPick(
        skill_id=chosen.id,
        skill_name=chosen.name,
        skill_description=chosen.description,
        target_difficulty=_target_difficulty(state_by_id.get(chosen.id)),
        question_forms=list(chosen.question_forms),
    )
