"""Pick which topic a generated question should target, and how hard.

Called from inside question generation (app.api.questions) when the student
did not name a topic themselves -- there is no student-facing "next problem"
surface. Topics are flat: no prerequisite graph, no unlock gate. Gating on
top of an ability estimate was what starved the demo (an average student
never clears a fixed threshold); a flat pool scored by weakness and staleness
does not have that failure mode.

Reading is free of side effects; `mark_served` is the one writer, and the
generation route calls it after a question actually exists.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlmodel import Session, select

from app.models.skill import Skill
from app.engine.models.skill_state import SkillState
from app.engine.accuracy import days_since, estimated_accuracy

# A topic with no outcomes yet. Placed deliberately between two weakness
# scores: above a topic the student is doing fine on (estimate 0.58 scores
# 0.25), below one they are struggling with (estimate 0.38 scores 0.37). So
# new material is served unless something already seen needs remediation.
#
# This is the one constant here that was not set by hand. At 0.20 it lost
# even to topics the student was doing well on, and the simulator measured
# the consequence: an average student reached 6 of 15 topics in 30
# questions. Re-measure with POST /dev/courses/{id}/simulate before moving
# it.
W_COVERAGE = 0.30
W_WEAKNESS = 0.60
W_STALENESS = 0.25
W_RECENCY_PENALTY = 0.40

# How long a topic takes to go fully stale, before scaling. The cap is
# stretched by how well the topic is known -- a topic at 0.9 gets roughly
# three times the grace of one at 0.1 -- because "decayed since practice"
# arrives later for material that was solid to begin with.
STALENESS_BASE_DAYS = 7.0
STALENESS_STRENGTH_STRETCH = 2.0

# Difficulty is clamped into the range a question is worth writing at.
DIFFICULTY_FLOOR = 0.15
DIFFICULTY_CEIL = 0.85

RECENT_PICKS_WINDOW = 2  # how many recently-served topics incur the penalty


@dataclass(frozen=True)
class TopicPick:
    skill_id: str
    skill_name: str
    skill_description: str
    target_difficulty: float
    question_forms: list[str]


def _staleness(state: SkillState, now: datetime, strength: float) -> float:
    if state.last_seen is None:
        return 0.0
    cap = STALENESS_BASE_DAYS * (1 + STALENESS_STRENGTH_STRETCH * strength)
    return min(days_since(state.last_seen, now) / cap, 1.0)


def _target_difficulty(skill: Skill, state: SkillState | None) -> float:
    """How hard to write. An untouched topic is written at the difficulty its
    taxonomy entry claims; after that, at the student's own estimate.

    There is no `mastery + offset` productive-struggle term: the estimate
    already sits where a residual estimator's fixed point would.
    """
    if state is None or not state.recent_outcomes:
        return skill.difficulty_band
    return min(max(estimated_accuracy(state.recent_outcomes), DIFFICULTY_FLOOR), DIFFICULTY_CEIL)


def _recently_served(states: list[SkillState], limit: int) -> set[str]:
    """The last `limit` topics *served*, graded or not.

    Served, not attempted: a question the student read and abandoned records
    no attempt, and keying this off the ledger meant the engine re-served
    that topic forever to exactly the student who was bouncing off it.
    """
    served = [s for s in states if s.last_served is not None]
    served.sort(key=lambda s: s.last_served, reverse=True)
    return {s.skill_id for s in served[:limit]}


def pick_topic(
    session: Session, course_id: str, student_id: str, now: datetime | None = None
) -> TopicPick | None:
    """The topic a question should target next, or None if the course has
    no topics yet (a fresh course with no generated question to piggyback on).

    `now` defaults to the wall clock; every production caller leaves it
    unset. The simulator is the one caller that passes a virtual timestamp,
    so staleness can be exercised without a real multi-day run.
    """
    skills = session.exec(select(Skill).where(Skill.course_id == course_id)).all()
    if not skills:
        return None

    now = now or datetime.now(timezone.utc)
    states = session.exec(
        select(SkillState).where(
            SkillState.student_id == student_id,
            SkillState.skill_id.in_([s.id for s in skills]),
        )
    ).all()
    state_by_id = {state.skill_id: state for state in states}
    recent = _recently_served(list(states), RECENT_PICKS_WINDOW)

    def priority(skill: Skill) -> float:
        state = state_by_id.get(skill.id)
        if state is None or not state.recent_outcomes:
            base = W_COVERAGE
        else:
            # Smoothed, so one unlucky attempt cannot outrank a topic with
            # eight attempts of real evidence behind it.
            strength = estimated_accuracy(state.recent_outcomes)
            base = W_WEAKNESS * (1.0 - strength) + W_STALENESS * _staleness(
                state, now, strength
            )
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
        target_difficulty=_target_difficulty(chosen, state_by_id.get(chosen.id)),
        question_forms=list(chosen.question_forms),
    )


def mark_served(
    session: Session,
    course_id: str,
    student_id: str,
    skill_id: str,
    now: datetime | None = None,
) -> None:
    """Record that this topic was just put in front of this student.

    Moves `last_served` and nothing else -- no attempt, no outcome, no
    accuracy. Creates the state row if the topic has never been touched,
    which is the common case for a first serve. `now` exists for the same
    reason it does on pick_topic: only the simulator ever passes it.
    """
    state = session.get(SkillState, (student_id, skill_id))
    if state is None:
        state = SkillState(student_id=student_id, course_id=course_id, skill_id=skill_id)
    state.last_served = now or datetime.now(timezone.utc)
    session.add(state)
    session.commit()
