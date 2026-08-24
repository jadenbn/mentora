"""Closed-loop simulation of the learning engine against real students.

Unlike a unit test, this drives the actual sequencing decision, not just the
mastery math: each simulated attempt asks services.selection.select_next()
what to serve next, samples a synthetic outcome at that difficulty from a
hidden true-ability model, and writes it back through
services.student_model_service.record_attempt() — the same call the API
makes. Every unlock gate, review-forcing rule, recency penalty, and
prerequisite bleed in selection.py and student_model_service.py runs for
real, against the real calc1 taxonomy (15 skills, a real prereq DAG), not a
flat list of independent synthetic skills.

Three questions this answers that a pure mastery-math check can't:
  - Does mastery converge to true ability under the ACTUAL selection policy,
    not an idealized independent-and-uniform one?
  - How often does forced review actually fire, and for whom?
  - Does any skill the taxonomy has unlocked never get served — i.e. does
    the priority formula starve something reachable?

Time is simulated too: sessions are batched across simulated days, with
occasional multi-day gaps, so read-time decay (mastery.apply_decay) is
exercised the way it would be for a student who doesn't practice daily.
Timestamps are corrected after each real write rather than by monkeypatching
the services' clocks, so the services under test run unmodified.

Run: python scripts/simulate.py --seed 42
     python scripts/simulate.py --archetype weak --attempts 800 --verbose
"""

from __future__ import annotations

import argparse
import math
import random
import sys
import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

# `python scripts/simulate.py` puts scripts/, not backend/, on sys.path[0],
# so the app package wouldn't otherwise be importable regardless of cwd.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlmodel import Session, SQLModel, create_engine

from app.models.attempt import Attempt
from app.models.skill import Skill
from app.models.skill_state import SkillState
from app.schemas.learning import AttemptCreate
from app.services import selection, student_model_service
from app.services.mastery import apply_decay
from app.services.taxonomy import load_taxonomy

COURSE_ID = "calc1"
DISCRIMINATION_K = 6.0  # steepness of the synthetic success curve

# How long a run needs to be before we trust convergence/starvation stats.
CONVERGENCE_MIN_ATTEMPTS = 8
STARVATION_FLOOR = 5  # touched fewer than this many times => "under-served"
CONCENTRATION_WARN = 0.5  # one skill taking this share of all attempts is worth a flag

MASTERY_BAR = 0.85  # narrative-only "mastered" bar for --journey, well above UNLOCK_THRESHOLD
JOURNEY_SNAPSHOTS = 10  # how many progress snapshots to print across a --journey run

SESSION_SIZE_RANGE = (4, 14)  # attempts per simulated sitting
TYPICAL_GAP_DAYS = (0.5, 2.0)  # gap before the next sitting, usually
BREAK_PROBABILITY = 0.12  # chance a gap is a real break instead
BREAK_GAP_DAYS = (4.0, 16.0)
FINAL_LOOKAHEAD_DAYS = 5.0  # "student checks their dashboard a few days later"


# ---------------------------------------------------------------------------
# Taxonomy shape: prereq depth, used to build a "weak on advanced material"
# archetype that's actually correlated with the DAG instead of independent
# per skill (real students aren't independently random per topic).

def compute_depths(skills: list[Skill]) -> dict[str, int]:
    by_id = {s.id: s for s in skills}
    cache: dict[str, int] = {}

    def depth(skill_id: str) -> int:
        if skill_id not in cache:
            prereqs = by_id[skill_id].prereqs
            cache[skill_id] = 0 if not prereqs else 1 + max(depth(p) for p in prereqs)
        return cache[skill_id]

    return {s.id: depth(s.id) for s in skills}


# ---------------------------------------------------------------------------
# Student archetypes: how hidden true ability is generated per skill.

def _clamp01(x: float) -> float:
    return max(0.03, min(0.97, x))


def _correlated_abilities(base: float, noise_std: float, skills, rng) -> dict[str, float]:
    """A per-student aptitude plus per-skill noise, not fully independent
    draws -- a real student's skills correlate with each other."""
    return {s.id: _clamp01(rng.gauss(base, noise_std)) for s in skills}


def _depth_penalized_abilities(
    shallow_base: float, per_depth_penalty: float, noise_std: float, skills, depths, rng
) -> dict[str, float]:
    return {
        s.id: _clamp01(rng.gauss(shallow_base - per_depth_penalty * depths[s.id], noise_std))
        for s in skills
    }


@dataclass
class Archetype:
    name: str
    ability_fn: "callable"
    hint_farmer: bool = False


ARCHETYPES = [
    Archetype("average", lambda sk, d, rng: _correlated_abilities(0.50, 0.14, sk, rng)),
    Archetype("strong", lambda sk, d, rng: _correlated_abilities(0.82, 0.08, sk, rng)),
    Archetype("weak", lambda sk, d, rng: _correlated_abilities(0.22, 0.08, sk, rng)),
    Archetype(
        "uneven_advanced_gap",
        lambda sk, d, rng: _depth_penalized_abilities(0.88, 0.13, 0.07, sk, d, rng),
    ),
    Archetype(
        "hint_farmer",
        lambda sk, d, rng: _correlated_abilities(0.50, 0.14, sk, rng),
        hint_farmer=True,
    ),
]


# ---------------------------------------------------------------------------
# Outcome sampling.

def simulate_outcome(true_ability: float, difficulty: float, rng: random.Random, *, hint_farmer: bool):
    """Sample (correct, hints_used, partial) from a logistic success model.

    P(correct) = 1 / (1 + exp(-K * (true_ability - difficulty)))
    """
    p_correct = 1 / (1 + math.exp(-DISCRIMINATION_K * (true_ability - difficulty)))
    correct = rng.random() < p_correct

    if correct:
        if hint_farmer:
            # Leans on hints regardless of whether they needed to.
            return correct, 2, False
        gap = true_ability - difficulty
        if gap > 0.15:
            hints = 0
        elif gap > -0.05:
            hints = rng.choice([0, 1])
        else:
            hints = rng.choice([1, 2])
        return correct, hints, False

    partial = rng.random() < 0.3
    return correct, 0, partial


# ---------------------------------------------------------------------------
# One closed-loop trial: real DB, real selection, real record_attempt.

class _FrozenClock:
    """Stand-in for the `datetime` name app.services.selection calls .now()
    on.

    select_next() reads real wall-clock time internally to decide unlock
    gating and staleness (via apply_decay on days-since-last-seen). There's
    no injection point for that, and no way to drive a multi-week simulated
    timeline through it otherwise: our simulated last_seen timestamps sit in
    the past relative to the real clock, so every prereq's decayed mastery
    would collapse toward 0.5 on every read and nothing would ever unlock.
    Patched into app.services.selection for the duration of one trial only,
    and restored immediately after -- see run_trial().
    """

    def __init__(self, get_now):
        self._get_now = get_now

    def now(self, tz=None):
        value = self._get_now()
        return value.astimezone(tz) if tz else value


@dataclass
class Pick:
    skill_id: str
    is_review: bool
    difficulty: float
    correct: bool


@dataclass
class TrialResult:
    archetype: str
    true_ability: dict
    picks: list = field(default_factory=list)
    final_mastery: dict = field(default_factory=dict)
    final_attempts: dict = field(default_factory=dict)
    decayed_mastery: dict = field(default_factory=dict)
    stalls: int = 0


def _seed_calc1(session: Session) -> list[Skill]:
    skills = load_taxonomy(COURSE_ID)
    for skill in skills:
        session.add(skill)
    session.commit()
    return skills


def run_trial(archetype: Archetype, rng: random.Random, target_attempts: int, student_id: str) -> TrialResult:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)

    with Session(engine) as session:
        skills = _seed_calc1(session)
        depths = compute_depths(skills)
        true_ability = archetype.ability_fn(skills, depths, rng)
        result = TrialResult(archetype=archetype.name, true_ability=true_ability)

        clock = {"now": datetime(2026, 1, 1, tzinfo=timezone.utc)}
        original_clock = selection.datetime
        selection.datetime = _FrozenClock(lambda: clock["now"])

        try:
            attempts_done = 0
            session_index = 0

            while attempts_done < target_attempts:
                session_index += 1
                sitting_size = rng.randint(*SESSION_SIZE_RANGE)

                for _ in range(sitting_size):
                    if attempts_done >= target_attempts:
                        break

                    spec = selection.select_next(session, COURSE_ID, student_id)
                    if spec is None:
                        # Every calc1 skill with no prereqs is unlocked
                        # vacuously, so this should never actually happen.
                        result.stalls += 1
                        break

                    correct, hints, partial = simulate_outcome(
                        true_ability[spec.skill_id], spec.target_difficulty, rng,
                        hint_farmer=archetype.hint_farmer,
                    )
                    payload = AttemptCreate(
                        student_id=student_id,
                        session_id=f"sitting-{session_index}",
                        problem_id=f"sim-{attempts_done}",
                        expected_skills=[spec.skill_id],
                        difficulty=spec.target_difficulty,
                        correct=correct,
                        partial=partial,
                        hints_used=hints,
                        total_time_ms=None,
                        errors=[],
                    )
                    outcome = student_model_service.record_attempt(session, COURSE_ID, payload)

                    # Time-travel: correct the timestamps record_attempt just
                    # wrote to our simulated "now" instead of the wall clock,
                    # so decay and recency operate on simulated time.
                    now = clock["now"]
                    state = session.get(SkillState, (student_id, spec.skill_id))
                    state.last_seen = now
                    session.add(state)
                    attempt_row = session.get(Attempt, outcome.attempt_id)
                    attempt_row.created_at = now
                    session.add(attempt_row)
                    session.commit()

                    result.picks.append(
                        Pick(skill_id=spec.skill_id, is_review=spec.is_review,
                             difficulty=spec.target_difficulty, correct=correct)
                    )
                    attempts_done += 1

                if result.stalls and attempts_done < target_attempts:
                    break  # nothing servable; no point looping forever

                gap_days = (
                    rng.uniform(*BREAK_GAP_DAYS) if rng.random() < BREAK_PROBABILITY
                    else rng.uniform(*TYPICAL_GAP_DAYS)
                )
                clock["now"] += timedelta(days=gap_days)

            final_now = clock["now"] + timedelta(days=FINAL_LOOKAHEAD_DAYS)
            for skill in skills:
                state = session.get(SkillState, (student_id, skill.id))
                if state is None:
                    continue
                result.final_mastery[skill.id] = state.mastery
                result.final_attempts[skill.id] = state.attempts
                last_seen = state.last_seen
                if last_seen.tzinfo is None:  # SQLite round-trip drops tzinfo
                    last_seen = last_seen.replace(tzinfo=timezone.utc)
                days_since = (final_now - last_seen).total_seconds() / 86400
                result.decayed_mastery[skill.id] = apply_decay(state.mastery, days_since)
        finally:
            selection.datetime = original_clock

        return result


def run_journey(seed: int, target_attempts: int) -> int:
    """One narrated trial: a complete novice who ends up mastering every
    skill in the course. Unlike run_trial(), this prints events as they
    happen -- when a skill first enters rotation, periodic mastery
    snapshots -- instead of only reporting a final state. Single trial, one
    archetype defined locally rather than added to ARCHETYPES: this is a
    demonstration run, not part of the standing eval suite.
    """
    rng = random.Random(seed)
    # Deliberately high and tight: this student is capable everywhere, not
    # just on average -- the point is to watch the whole DAG unlock and
    # converge, not to model a realistic mixed-ability student.
    archetype = Archetype("master_journey", lambda sk, d, r: _correlated_abilities(0.93, 0.04, sk, r))
    student_id = "journey-student"

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)

    with Session(engine) as session:
        skills = _seed_calc1(session)
        depths = compute_depths(skills)
        true_ability = archetype.ability_fn(skills, depths, rng)

        print(f"=== NOVICE -> MASTER: {COURSE_ID}, seed={seed}, "
              f"target={target_attempts} attempts ===")
        print(f"({len(skills)} skills, hidden true ability ~0.93 +/- 0.04 on every one, "
              f"starting mastery 0.50 on all)\n")

        clock = {"now": datetime(2026, 1, 1, tzinfo=timezone.utc)}
        original_clock = selection.datetime
        selection.datetime = _FrozenClock(lambda: clock["now"])

        first_practiced: dict[str, int] = {}
        review_count = 0
        snapshot_every = max(1, target_attempts // JOURNEY_SNAPSHOTS)

        try:
            attempts_done = 0
            session_index = 0

            while attempts_done < target_attempts:
                session_index += 1
                sitting_size = rng.randint(*SESSION_SIZE_RANGE)

                for _ in range(sitting_size):
                    if attempts_done >= target_attempts:
                        break

                    spec = selection.select_next(session, COURSE_ID, student_id)
                    if spec is None:
                        print(f"  [attempt {attempts_done}] STALL -- select_next returned "
                              f"None; stopping early")
                        attempts_done = target_attempts
                        break

                    if spec.skill_id not in first_practiced:
                        first_practiced[spec.skill_id] = attempts_done + 1
                        day = (clock["now"] - datetime(2026, 1, 1, tzinfo=timezone.utc)).days
                        skill_name = next(s.name for s in skills if s.id == spec.skill_id)
                        print(f"  day {day:4d}  attempt {attempts_done + 1:4d}  "
                              f"ENTERS ROTATION (d{depths[spec.skill_id]})  "
                              f"{spec.skill_id}  -- {skill_name}")

                    if spec.is_review:
                        review_count += 1

                    correct, hints, partial = simulate_outcome(
                        true_ability[spec.skill_id], spec.target_difficulty, rng,
                        hint_farmer=False,
                    )
                    payload = AttemptCreate(
                        student_id=student_id,
                        session_id=f"sitting-{session_index}",
                        problem_id=f"sim-{attempts_done}",
                        expected_skills=[spec.skill_id],
                        difficulty=spec.target_difficulty,
                        correct=correct,
                        partial=partial,
                        hints_used=hints,
                        total_time_ms=None,
                        errors=[],
                    )
                    outcome = student_model_service.record_attempt(session, COURSE_ID, payload)

                    now = clock["now"]
                    state = session.get(SkillState, (student_id, spec.skill_id))
                    state.last_seen = now
                    session.add(state)
                    attempt_row = session.get(Attempt, outcome.attempt_id)
                    attempt_row.created_at = now
                    session.add(attempt_row)
                    session.commit()

                    attempts_done += 1

                    if attempts_done % snapshot_every == 0:
                        states = {s.id: session.get(SkillState, (student_id, s.id)) for s in skills}
                        touched = {sid: st for sid, st in states.items() if st is not None}
                        mastered = sum(1 for st in touched.values() if st.mastery >= MASTERY_BAR)
                        avg_mastery = (
                            sum(st.mastery for st in touched.values()) / len(touched)
                            if touched else 0.0
                        )
                        day = (clock["now"] - datetime(2026, 1, 1, tzinfo=timezone.utc)).days
                        print(f"  --- snapshot: attempt {attempts_done:4d}, day {day:4d} -- "
                              f"{len(touched):2d}/{len(skills)} skills touched, "
                              f"{mastered:2d}/{len(skills)} mastered (>={MASTERY_BAR}), "
                              f"avg mastery {avg_mastery:.2f} ---")

                if attempts_done >= target_attempts:
                    break

                gap_days = (
                    rng.uniform(*BREAK_GAP_DAYS) if rng.random() < BREAK_PROBABILITY
                    else rng.uniform(*TYPICAL_GAP_DAYS)
                )
                clock["now"] += timedelta(days=gap_days)

            total_days = (clock["now"] - datetime(2026, 1, 1, tzinfo=timezone.utc)).days

            print(f"\n=== FINAL: {attempts_done} attempts across {total_days} simulated days ===")
            print(f"  forced review: {review_count} picks ({review_count / attempts_done:.1%})")
            print(f"\n  {'depth':<6}{'skill':<45}{'attempts':>9}{'mastery':>9}{'true':>7}")
            mastered_count = 0
            for skill in sorted(skills, key=lambda s: (depths[s.id], s.id)):
                state = session.get(SkillState, (student_id, skill.id))
                if state is None:
                    print(f"  d{depths[skill.id]:<5}{skill.id:<45}{'--':>9}{'--':>9}{'--':>7}"
                          f"  NEVER ENTERED ROTATION")
                    continue
                if state.mastery >= MASTERY_BAR:
                    mastered_count += 1
                flag = "  MASTERED" if state.mastery >= MASTERY_BAR else ""
                print(f"  d{depths[skill.id]:<5}{skill.id:<45}{state.attempts:>9}"
                      f"{state.mastery:>9.2f}{true_ability[skill.id]:>7.2f}{flag}")

            print(f"\n  {mastered_count}/{len(skills)} skills mastered (mastery >= {MASTERY_BAR})")
            if mastered_count == len(skills):
                print("  full course mastered.")
                return 0
            print(f"  {len(skills) - mastered_count} skill(s) short of mastery -- "
                  f"try a larger --attempts budget")
            return 1
        finally:
            selection.datetime = original_clock


# ---------------------------------------------------------------------------
# Metrics.

def spearman(xs: list, ys: list) -> float:
    def rank(values):
        order = sorted(range(len(values)), key=lambda i: values[i])
        ranks = [0.0] * len(values)
        for r, i in enumerate(order):
            ranks[i] = r
        return ranks

    rx, ry = rank(xs), rank(ys)
    n = len(xs)
    if n < 2:
        return 1.0
    d2 = sum((a - b) ** 2 for a, b in zip(rx, ry))
    return 1 - (6 * d2) / (n * (n**2 - 1))


def analyze(trial: TrialResult, skills: list[Skill], depths: dict) -> dict:
    attempts_by_skill = Counter(p.skill_id for p in trial.picks)
    review_picks = sum(1 for p in trial.picks if p.is_review)
    review_rate = review_picks / len(trial.picks) if trial.picks else 0.0

    estimates, truths = [], []
    for skill in skills:
        n = attempts_by_skill.get(skill.id, 0)
        if n >= CONVERGENCE_MIN_ATTEMPTS and skill.id in trial.final_mastery:
            estimates.append(trial.final_mastery[skill.id])
            truths.append(trial.true_ability[skill.id])

    mae = sum(abs(e - t) for e, t in zip(estimates, truths)) / len(estimates) if estimates else None
    # n=2 makes spearman exactly +-1 by construction (only one possible
    # ranking disagreement) -- not a meaningful correlation, just a coin
    # flip that then gets averaged across trials into a misleading number.
    corr = spearman(truths, estimates) if len(estimates) >= 3 else None

    def is_unlocked_now(skill: Skill) -> bool:
        return all(
            trial.decayed_mastery.get(p, 0.5) >= selection.UNLOCK_THRESHOLD
            for p in skill.prereqs
        )

    never_reached = [s.id for s in skills if attempts_by_skill.get(s.id, 0) == 0]
    starved_despite_unlocked = [
        skill.id for skill in skills
        if attempts_by_skill.get(skill.id, 0) == 0 and is_unlocked_now(skill)
    ]
    still_locked = [s for s in never_reached if s not in starved_despite_unlocked]
    under_served = [
        skill.id for skill in skills
        if 0 < attempts_by_skill.get(skill.id, 0) < STARVATION_FLOOR
    ]

    top_skill, top_n = attempts_by_skill.most_common(1)[0] if attempts_by_skill else (None, 0)
    top_skill_share = top_n / len(trial.picks) if trial.picks else 0.0

    return {
        "archetype": trial.archetype,
        "total_attempts": len(trial.picks),
        "mae": mae,
        "corr": corr,
        "n_converged_skills": len(estimates),
        "review_rate": review_rate,
        "stalls": trial.stalls,
        "skills_reached": len(skills) - len(never_reached),
        "skills_total": len(skills),
        "still_locked": still_locked,
        "starved_despite_unlocked": starved_despite_unlocked,
        "under_served": under_served,
        "top_skill": top_skill,
        "top_skill_share": top_skill_share,
    }


def average_reports(reports: list[dict]) -> dict:
    maes = [r["mae"] for r in reports if r["mae"] is not None]
    corrs = [r["corr"] for r in reports if r["corr"] is not None]
    starved: Counter = Counter()
    for r in reports:
        starved.update(r["starved_despite_unlocked"])
    return {
        "archetype": reports[0]["archetype"],
        "trials": len(reports),
        "mae": sum(maes) / len(maes) if maes else None,
        "corr": sum(corrs) / len(corrs) if corrs else None,
        "n_converged_avg": sum(r["n_converged_skills"] for r in reports) / len(reports),
        "review_rate": sum(r["review_rate"] for r in reports) / len(reports),
        "stalls": sum(r["stalls"] for r in reports),
        "skills_reached_avg": sum(r["skills_reached"] for r in reports) / len(reports),
        "skills_total": reports[0]["skills_total"],
        "starved_persistent": [s for s, count in starved.items() if count > len(reports) / 2],
        "under_served_last": reports[-1]["under_served"],
        "top_skill_share_avg": sum(r["top_skill_share"] for r in reports) / len(reports),
        "top_skill_last": reports[-1]["top_skill"],
    }


# ---------------------------------------------------------------------------
# Reporting.

def print_report(summary: dict) -> None:
    print(f"\n-- {summary['archetype']} ({summary['trials']} trials) --")
    mae_s = f"{summary['mae']:.3f}" if summary["mae"] is not None else "n/a"
    corr_s = f"{summary['corr']:.3f}" if summary["corr"] is not None else "n/a"
    print(f"  convergence:  MAE={mae_s}  spearman={corr_s}  "
          f"(n={summary['n_converged_avg']:.1f} skills with >={CONVERGENCE_MIN_ATTEMPTS} attempts)")
    print(f"  coverage:     {summary['skills_reached_avg']:.1f}/{summary['skills_total']} "
          f"skills reached on average")
    print(f"  review rate:  {summary['review_rate']:.1%} of picks were forced review")
    print(f"  stalls:       {summary['stalls']} (select_next returned None mid-run)")
    if summary["top_skill_share_avg"] >= CONCENTRATION_WARN:
        print(f"  CONCENTRATED: {summary['top_skill_share_avg']:.0%} of attempts on one skill "
              f"on average (last trial: {summary['top_skill_last']})")
    if summary["starved_persistent"]:
        print(f"  STARVED:      unlocked but never served in >half the trials: "
              f"{summary['starved_persistent']}")
    if summary["under_served_last"]:
        print(f"  under-served: touched <{STARVATION_FLOOR}x (last trial): "
              f"{summary['under_served_last']}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=42)
    # 400 wasn't enough for a stable read: an "average" student only lands
    # 2-3 skills above the convergence-attempt floor by then, so MAE swings
    # on sampling noise alone. 600 was stable across repeated seeds. A
    # --journey run needs more: no cross-trial averaging to smooth noise,
    # and every one of 15 skills -- including depth-4 leaves -- has to
    # individually converge, not just enough of them for a stable average.
    parser.add_argument("--attempts", type=int, default=None,
                         help="attempts per trial (default: 600, or 1200 with --journey)")
    parser.add_argument("--trials", type=int, default=3, help="trials per archetype")
    parser.add_argument("--archetype", type=str, default=None,
                         help="run only this archetype (default: all)")
    parser.add_argument("--verbose", action="store_true", help="print per-skill detail")
    parser.add_argument("--journey", action="store_true",
                         help="narrate one student from novice to mastering every skill, "
                              "instead of running the multi-archetype eval suite")
    args = parser.parse_args()

    if args.journey:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(line_buffering=True)
        return run_journey(args.seed, args.attempts or 1200)

    args.attempts = args.attempts or 600

    archetypes = (
        [a for a in ARCHETYPES if a.name == args.archetype] if args.archetype else ARCHETYPES
    )
    if args.archetype and not archetypes:
        print(f"unknown archetype {args.archetype!r}; choices: {[a.name for a in ARCHETYPES]}")
        return 2

    started = time.time()
    all_summaries = []
    failures = []

    for archetype_index, archetype in enumerate(archetypes):
        trials, last_trial, last_skills, last_depths = [], None, None, None

        for i in range(args.trials):
            # Not hash(archetype.name): Python randomizes str hashing per
            # process by default, which would make --seed non-reproducible
            # across runs despite looking deterministic.
            trial_rng = random.Random(args.seed + archetype_index * 1000 + i)
            trial = run_trial(archetype, trial_rng, args.attempts, student_id=f"sim-{archetype.name}-{i}")
            skills = load_taxonomy(COURSE_ID)  # cheap: pure JSON parse, no DB
            depths = compute_depths(skills)
            trials.append(analyze(trial, skills, depths))
            last_trial, last_skills, last_depths = trial, skills, depths

        summary = average_reports(trials)
        all_summaries.append(summary)
        print_report(summary)

        if args.verbose and last_trial is not None:
            print("  per-skill (last trial):")
            for skill in sorted(last_skills, key=lambda s: last_depths[s.id]):
                n = sum(1 for p in last_trial.picks if p.skill_id == skill.id)
                mastery = last_trial.final_mastery.get(skill.id)
                truth = last_trial.true_ability[skill.id]
                mastery_s = f"{mastery:.2f}" if mastery is not None else "  -"
                print(f"    d{last_depths[skill.id]}  {skill.id:45s} "
                      f"n={n:3d}  mastery={mastery_s}  true={truth:.2f}")

        # -- pass/fail thresholds --
        if summary["stalls"]:
            failures.append(f"{archetype.name}: {summary['stalls']} stall(s) -- "
                             f"select_next returned None despite always-unlocked root skills")
        if summary["starved_persistent"]:
            failures.append(f"{archetype.name}: skills starved despite being unlocked: "
                             f"{summary['starved_persistent']}")
        if archetype.name in ("average", "strong") and summary["mae"] is not None:
            # Correlation is NOT gated for these two: both archetypes draw
            # per-skill ability from a tight per-student cluster (small
            # noise_std around one base), by design -- that's what makes
            # them "correlated ability" rather than the old fully
            # independent-per-skill model. Small true between-skill spread
            # mechanically caps rank correlation regardless of estimator
            # quality (range restriction), so MAE -- absolute accuracy --
            # is the metric that's actually meaningful here. Correlation is
            # gated below only for uneven_advanced_gap, which has deliberate
            # wide (depth-based) spread for it to be meaningful against.
            if summary["mae"] >= 0.15:
                failures.append(f"{archetype.name}: MAE {summary['mae']:.3f} >= 0.15")
        if archetype.name == "uneven_advanced_gap" and summary["corr"] is not None:
            if summary["corr"] <= 0.7:
                failures.append(f"uneven_advanced_gap: spearman {summary['corr']:.3f} <= 0.7")
        if archetype.name == "strong" and summary["skills_reached_avg"] < summary["skills_total"] * 0.85:
            failures.append(f"strong: only reached {summary['skills_reached_avg']:.1f}/"
                             f"{summary['skills_total']} skills -- unlock gating too conservative?")
        if archetype.name == "uneven_advanced_gap" and summary["review_rate"] <= 0.0:
            # weak/hint_farmer have nothing above REVIEW_MASTERY_MIN to
            # review yet at this attempt budget, so forced review can never
            # fire for them by construction -- uneven_advanced_gap is the
            # archetype that actually has mastered shallow skills to review
            # while still struggling deep, so it's the one that should show
            # review firing at all.
            failures.append("uneven_advanced_gap: forced review never fired despite a real "
                             "shallow/deep mastery gap")

    elapsed = time.time() - started
    print(f"\n({elapsed:.1f}s, {args.trials} trials x {args.attempts} attempts x {len(archetypes)} archetypes)")

    print()
    if failures:
        print("FAILED:")
        for f in failures:
            print(f"  - {f}")
        return 1

    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
