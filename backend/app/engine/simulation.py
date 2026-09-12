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

Every student in one run is drawn from the same `profile` (STUDENT_PROFILES)
-- an ability range and a learning rate, not just "more of the same". `n`
students from one profile narrows noise on that profile's numbers; it says
nothing about a different kind of student. To ask whether the policy still
covers the course, still holds difficulty steady, still avoids repeats for a
struggling cohort rather than an average one, run this again with a
different profile and read the two reports side by side.

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
from sqlmodel import Session, SQLModel, create_engine, select

from app.models.skill import Skill
from app.engine.schemas import AttemptCreate
from app.engine.accuracy import PRIOR_ACCURACY, difficulty_bucket, estimated_accuracy, score_attempt
from app.engine.models.skill_state import SkillState
from app.engine.selection import mark_served, pick_topic
from app.engine.student_model_service import record_attempt

#: How much a difficulty above or below the middle moves the odds.
DIFFICULTY_EFFECT = 0.6
#: How much ability a student gains on a topic each time they practise it,
#: for a student on the "mixed" profile (see STUDENT_PROFILES). Other
#: profiles scale this rather than restate it.
LEARNING_RATE = 0.04
#: Odds of landing a partial rather than nothing when the answer is wrong.
PARTIAL_BAND = 0.15


@dataclass(frozen=True)
class StudentProfile:
    """One synthetic-student archetype: where a student's per-topic ability
    starts (drawn uniformly from `ability_range`), and how fast it moves.

    Every student in one `simulate` run is drawn from the same profile --
    the point is not "more students" (that only narrows noise on the same
    question) but "a different cohort" (that changes whether the policy
    still works for a struggling student, not just an average one). Run the
    same course through two profiles and compare the reports.
    """
    ability_range: tuple[float, float]
    learning_rate: float


#: Canned cohorts, not an open-ended dial. "mixed" reproduces the only
#: population this simulator ever measured before profiles existed.
STUDENT_PROFILES: dict[str, StudentProfile] = {
    "mixed": StudentProfile(ability_range=(0.1, 0.9), learning_rate=LEARNING_RATE),
    "strong": StudentProfile(ability_range=(0.55, 0.9), learning_rate=LEARNING_RATE),
    "struggling": StudentProfile(ability_range=(0.1, 0.4), learning_rate=LEARNING_RATE * 0.5),
    "fast_learner": StudentProfile(ability_range=(0.15, 0.45), learning_rate=LEARNING_RATE * 3),
}


@dataclass(frozen=True)
class SkillOutcome:
    """One topic's read-out from a simulation run."""
    skill_id: str
    skill_name: str
    #: How many times any student in the cohort was served this topic.
    times_served: int
    #: Mean outcome score on this topic, over every attempt by every
    #: student. None if no student was ever served it -- there is nothing
    #: to average, and 0.0 would misreport that as "served and failed".
    mean_score: float | None
    #: Mean, across the whole cohort, of `estimated_accuracy` on this
    #: topic's final SkillState -- the same number the dashboard's own
    #: "Estimate" column reads for a real student. A student never served
    #: the topic counts at PRIOR_ACCURACY, same as a real student who has
    #: never attempted it. This is "what the topic would be at" after the
    #: run, not the synthetic learner's hidden true ability.
    final_estimate: float

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class SimulationReport:
    students: int
    questions_each: int
    #: Which STUDENT_PROFILES entry this cohort was drawn from.
    profile: str
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
    #: Every topic in the course, individually -- see SkillOutcome. The
    #: aggregates above answer "is the policy sane overall"; this answers
    #: "which topics, specifically, does it undercover or under-serve".
    per_skill: list[SkillOutcome]

    def as_dict(self) -> dict:
        return asdict(self)


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def simulate(
    skills: list[Skill],
    *,
    profile: str = "mixed",
    students: int = 12,
    questions_each: int = 24,
    seed: int = 1,
    attempt_interval_days: float = 0.0,
) -> SimulationReport:
    """Run the policy end to end and report on it. Never touches mentora.db.

    `profile` selects the cohort's ability range and learning rate from
    STUDENT_PROFILES; raises ValueError for anything else. `students` only
    controls how many are drawn from that one profile and averaged -- it
    narrows noise on the numbers below, it does not change what is measured.
    To see whether the policy holds up for a different kind of student, run
    this again with a different profile and compare the two reports.

    `attempt_interval_days` is the mean spacing (jittered 0.5x-1.5x) between
    one simulated attempt and the next; 0 -- the default -- keeps every
    attempt at the same virtual instant, matching every measurement this
    module has ever reported. Pass a realistic spacing (course review is
    keyed off STALENESS_BASE_DAYS, so a handful of days is enough) to
    exercise staleness instead.
    """
    if not skills:
        raise ValueError("a course with no topics has nothing to simulate")
    try:
        cohort = STUDENT_PROFILES[profile]
    except KeyError:
        raise ValueError(
            f"unknown profile {profile!r}; choose one of {sorted(STUDENT_PROFILES)}"
        ) from None

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
    served_by_skill: dict[str, int] = {s.id: 0 for s in skills}
    scores_by_skill: dict[str, list[float]] = {s.id: [] for s in skills}

    with Session(engine) as session:
        for skill in skills:
            session.add(Skill(**skill.model_dump()))
        session.commit()

        for index in range(students):
            student_id = f"sim-{index}"
            lo, hi = cohort.ability_range
            ability = {s.id: rng.uniform(lo, hi) for s in skills}
            scores: list[float] = []
            difficulties: list[float] = []
            touched: set[str] = set()
            previous: str | None = None

            for question in range(questions_each):
                pick = pick_topic(session, course_id, student_id, now=virtual_now)
                mark_served(session, course_id, student_id, pick.skill_id, now=virtual_now)
                picks += 1
                served_by_skill[pick.skill_id] += 1
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
                scores_by_skill[pick.skill_id].append(score)
                by_bucket.setdefault(difficulty_bucket(pick.target_difficulty), []).append(score)
                ability[pick.skill_id] = min(0.95, ability[pick.skill_id] + cohort.learning_rate)

            third = max(1, len(scores) // 3)
            coverage.append(len(touched) / len(skills))
            early.append(_mean(scores[:third]))
            late.append(_mean(scores[-third:]))
            difficulty_early.append(_mean(difficulties[:third]))
            difficulty_late.append(_mean(difficulties[-third:]))

        # One SkillState row per (student, topic) ever served -- read back
        # after the whole cohort has run, so this is the same number the
        # real dashboard would show for each of those students, not the
        # synthetic learner's hidden true ability.
        final_estimates: dict[str, list[float]] = {s.id: [] for s in skills}
        for state in session.exec(select(SkillState)).all():
            final_estimates[state.skill_id].append(estimated_accuracy(state.recent_outcomes))

    per_skill = [
        SkillOutcome(
            skill_id=skill.id,
            skill_name=skill.name,
            times_served=served_by_skill[skill.id],
            mean_score=_mean(scores_by_skill[skill.id]) if scores_by_skill[skill.id] else None,
            # Students never served this topic count at the same prior a
            # real, never-attempted SkillState reads as.
            final_estimate=_mean(
                final_estimates[skill.id]
                + [PRIOR_ACCURACY] * (students - len(final_estimates[skill.id]))
            ),
        )
        for skill in skills
    ]

    return SimulationReport(
        students=students,
        questions_each=questions_each,
        profile=profile,
        topics=len(skills),
        coverage=_mean(coverage),
        score_early=_mean(early),
        score_late=_mean(late),
        difficulty_early=_mean(difficulty_early),
        difficulty_late=_mean(difficulty_late),
        repeat_rate=repeats / picks if picks else 0.0,
        calibration={name: _mean(v) for name, v in sorted(by_bucket.items())},
        per_skill=per_skill,
    )
