"""Replay the selection policy against synthetic students.

The engine's constants -- the priority weights, the window of 8, the prior
weight -- were all set by hand, and until this existed nothing could tell you
one of them was wrong. Tests prove the mechanism is correct; this measures
whether the policy is any good.

It runs the *real* `pick_topic` / `mark_served` / `record_attempt` against a
throwaway in-memory database, so there is no second copy of the policy to
drift from the first, and no synthetic student ever lands in mentora.db.

A synthetic student has a latent per-topic ability, gains a little on a topic
each time they practise it, and succeeds with a probability set by that
ability against the difficulty the engine asked for. That is a crude learner
model and the absolute numbers mean little; the useful signal is how the
numbers *move* when a constant changes.

An optional virtual clock can advance between attempts (`attempt_interval_days`),
so `last_seen` staleness accumulates the way it would over a real term rather
than never firing at all. It defaults to 0 -- every attempt at the same
instant, as before -- because turning it on changes what the simulator
measures: once enough of a course's topics go stale, a stale-but-known topic
can outscore a topic never touched at all (staleness saturates at
W_STALENESS=0.25 above the W_COVERAGE=0.30 baseline once weakness is low
enough), and coverage over a fixed question budget falls as a result. That is
a real interaction the constants have, not a bug in the clock -- see
test_a_realistic_pace_lets_staleness_compete_with_coverage in
tests/test_simulation.py -- and retuning the weights for it is future work,
not part of adding the clock.
"""

from __future__ import annotations

import random
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.models.skill import Skill
from app.schemas.learning import AttemptCreate
from app.services.accuracy import difficulty_bucket, score_attempt
from app.services.selection import mark_served, pick_topic
from app.services.student_model_service import record_attempt

#: How much a difficulty above or below the middle moves the odds.
DIFFICULTY_EFFECT = 0.6
#: How much ability a student gains on a topic each time they practise it.
LEARNING_RATE = 0.04
#: Odds of landing a partial rather than nothing when the answer is wrong.
PARTIAL_BAND = 0.15


@dataclass(frozen=True)
class SimulationReport:
    students: int
    questions_each: int
    topics: int
    #: Mean share of the course's topics a student actually attempted.
    coverage: float
    #: Mean outcome score over the first and last third of each student's
    #: run. These should stay roughly level, not climb: difficulty tracks
    #: the estimate, so a student who improves is served harder questions
    #: rather than scoring higher on the same ones. A collapse here means
    #: the engine is pushing students past what they can do.
    score_early: float
    score_late: float
    #: Mean difficulty served over the same two thirds. This is where growth
    #: shows up -- late should exceed early.
    difficulty_early: float
    difficulty_late: float
    #: Share of picks that repeat the immediately preceding topic. The
    #: recency penalty exists to keep this low.
    repeat_rate: float
    #: Mean outcome score by the difficulty the engine asked for. Should
    #: fall as difficulty rises; if it is flat, the generator's compliance
    #: with the requested level is not reaching the student.
    calibration: dict[str, float]

    def as_dict(self) -> dict:
        return asdict(self)


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def simulate(
    skills: list[Skill],
    *,
    students: int = 12,
    questions_each: int = 24,
    seed: int = 1,
    attempt_interval_days: float = 0.0,
) -> SimulationReport:
    """Run the policy end to end and report on it. Never touches mentora.db.

    `attempt_interval_days` is the mean spacing (jittered 0.5x-1.5x) between
    one simulated attempt and the next; 0 -- the default -- keeps every
    attempt at the same virtual instant, matching every measurement this
    module has ever reported. Pass a realistic spacing (course review is
    keyed off STALENESS_BASE_DAYS, so a handful of days is enough) to
    exercise staleness instead.
    """
    if not skills:
        raise ValueError("a course with no topics has nothing to simulate")

    course_id = skills[0].course_id
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    SQLModel.metadata.create_all(engine)
    rng = random.Random(seed)
    # An arbitrary anchor; only the deltas from it matter to staleness.
    virtual_now = datetime(2020, 1, 1, tzinfo=timezone.utc)

    coverage: list[float] = []
    early: list[float] = []
    late: list[float] = []
    difficulty_early: list[float] = []
    difficulty_late: list[float] = []
    repeats = 0
    picks = 0
    by_bucket: dict[str, list[float]] = {}

    with Session(engine) as session:
        for skill in skills:
            session.add(Skill(**skill.model_dump()))
        session.commit()

        for index in range(students):
            student_id = f"sim-{index}"
            ability = {s.id: rng.uniform(0.1, 0.9) for s in skills}
            scores: list[float] = []
            difficulties: list[float] = []
            touched: set[str] = set()
            previous: str | None = None

            for question in range(questions_each):
                pick = pick_topic(session, course_id, student_id, now=virtual_now)
                mark_served(session, course_id, student_id, pick.skill_id, now=virtual_now)
                picks += 1
                if pick.skill_id == previous:
                    repeats += 1
                previous = pick.skill_id

                odds = ability[pick.skill_id] + (0.5 - pick.target_difficulty) * DIFFICULTY_EFFECT
                roll = rng.random()
                correct = roll < odds
                partial = not correct and roll < odds + PARTIAL_BAND

                record_attempt(
                    session,
                    course_id,
                    AttemptCreate(
                        student_id=student_id,
                        session_id="sim",
                        problem_id=f"{student_id}-{question}",
                        expected_skills=[pick.skill_id],
                        difficulty=pick.target_difficulty,
                        correct=correct,
                        partial=partial,
                    ),
                    now=virtual_now,
                )
                # Always advance by a token amount, even with staleness
                # switched off: mark_served stamps last_served with this
                # clock, and the recency penalty (_recently_served) ranks by
                # that timestamp, so ties from a frozen clock would make it
                # unable to tell this round's pick from ten rounds ago.
                virtual_now += timedelta(seconds=1)
                if attempt_interval_days > 0:
                    virtual_now += timedelta(days=attempt_interval_days * rng.uniform(0.5, 1.5))

                score = score_attempt(correct=correct, hints_used=0, partial=partial)
                scores.append(score)
                difficulties.append(pick.target_difficulty)
                touched.add(pick.skill_id)
                by_bucket.setdefault(difficulty_bucket(pick.target_difficulty), []).append(score)
                ability[pick.skill_id] = min(0.95, ability[pick.skill_id] + LEARNING_RATE)

            third = max(1, len(scores) // 3)
            coverage.append(len(touched) / len(skills))
            early.append(_mean(scores[:third]))
            late.append(_mean(scores[-third:]))
            difficulty_early.append(_mean(difficulties[:third]))
            difficulty_late.append(_mean(difficulties[-third:]))

    return SimulationReport(
        students=students,
        questions_each=questions_each,
        topics=len(skills),
        coverage=_mean(coverage),
        score_early=_mean(early),
        score_late=_mean(late),
        difficulty_early=_mean(difficulty_early),
        difficulty_late=_mean(difficulty_late),
        repeat_rate=repeats / picks if picks else 0.0,
        calibration={name: _mean(v) for name, v in sorted(by_bucket.items())},
    )
