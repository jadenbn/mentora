"""Closed-loop simulation of the learning engine against synthetic students.

Unlike a unit test this drives the actual sequencing decision: each attempt
asks services.selection.select_next() what to serve, samples an outcome at
that difficulty from a hidden ability model, and writes it back through
services.student_model_service.record_attempt(). Unlock gating, the coverage
and urgency terms, the recency penalty, the review floor and prerequisite
bleed all run for real against the real calc1 taxonomy.

    python scripts/simulate.py                # default: well-specified
    python scripts/simulate.py --misspecified # 3PL: guessing and slips
    python scripts/simulate.py --seed 7 --trials 5 --verbose

## What "well-specified" does and does not prove

The default outcome model is logistic in (ability - difficulty), which is the
same family the estimator's expected_score assumes. An estimator whose link
function matches the data-generating process converges by construction, so
that run tests the arithmetic and the plumbing -- useful, and it is what
justified the ALPHA_FLOOR change in mastery.py -- but it cannot fail for a
reason that would matter to a real student.

--misspecified is the run that can. It samples from a 3PL model instead:
students guess right on problems they cannot do (GUESS_FLOOR) and slip on
problems they can (SLIP_CEILING), which no amount of tuning inside mastery.py
anticipates. If MAE holds there, the estimator is earning something.

Exit status: 0 if every check passed, 1 on any failure.
"""

from __future__ import annotations

import argparse
import math
import random
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlmodel import Session, SQLModel, create_engine  # noqa: E402

from app.models.attempt import Attempt  # noqa: E402
from app.models.skill import Skill  # noqa: E402
from app.models.skill_state import SkillState  # noqa: E402
from app.schemas.learning import AttemptCreate  # noqa: E402
from app.services import selection, student_model_service  # noqa: E402
from app.services.mastery import apply_decay  # noqa: E402
from app.services.taxonomy import load_taxonomy  # noqa: E402

COURSE_ID = "calc1"

DISCRIMINATION_K = 6.0  # steepness of the synthetic success curve
GUESS_FLOOR = 0.15  # --misspecified: right answer without the skill
SLIP_CEILING = 0.05  # --misspecified: wrong answer despite the skill

SESSION_SIZE_RANGE = (4, 12)
TYPICAL_GAP_DAYS = (0.5, 2.0)
BREAK_GAP_DAYS = (4.0, 10.0)
BREAK_PROBABILITY = 0.15
FINAL_LOOKAHEAD_DAYS = 1.0

# A skill needs this much evidence before its estimate is fair to score.
CONVERGENCE_MIN_ATTEMPTS = 6
MAE_LIMIT = 0.15


def clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


# ---------------------------------------------------------------------------
# Students


@dataclass(frozen=True)
class Archetype:
    name: str
    base: float
    spread: float
    depth_penalty: float = 0.0  # ability falls off with prerequisite depth
    hint_farmer: bool = False


ARCHETYPES = [
    Archetype("average", base=0.50, spread=0.14),
    Archetype("strong", base=0.82, spread=0.08),
    Archetype("weak", base=0.22, spread=0.08),
    # Fluent at the basics, genuinely lost deeper in: the only archetype with
    # real between-skill spread, so it is the one where rank correlation and
    # the review floor are meaningful to check.
    Archetype("uneven_advanced_gap", base=0.88, spread=0.13, depth_penalty=0.07),
    Archetype("hint_farmer", base=0.50, spread=0.14, hint_farmer=True),
]


def compute_depths(skills: list[Skill]) -> dict[str, int]:
    by_id = {s.id: s for s in skills}
    memo: dict[str, int] = {}

    def depth(skill_id: str, seen: frozenset = frozenset()) -> int:
        if skill_id in memo:
            return memo[skill_id]
        skill = by_id.get(skill_id)
        if skill is None or not skill.prereqs or skill_id in seen:
            return 0
        memo[skill_id] = 1 + max(
            depth(p, seen | {skill_id}) for p in skill.prereqs
        )
        return memo[skill_id]

    return {s.id: depth(s.id) for s in skills}


def draw_abilities(
    archetype: Archetype, skills: list[Skill], depths: dict[str, int], rng: random.Random
) -> dict[str, float]:
    return {
        s.id: clamp01(
            rng.gauss(archetype.base, archetype.spread)
            - archetype.depth_penalty * depths[s.id]
        )
        for s in skills
    }


def simulate_outcome(
    true_ability: float,
    difficulty: float,
    rng: random.Random,
    *,
    hint_farmer: bool,
    misspecified: bool,
):
    """Sample (correct, hints_used, partial) at this ability and difficulty."""
    p = 1 / (1 + math.exp(-DISCRIMINATION_K * (true_ability - difficulty)))
    if misspecified:
        # 3PL: a floor from guessing and a ceiling from slips. The estimator
        # models neither, which is the whole point of running this way.
        p = GUESS_FLOOR + (1 - GUESS_FLOOR - SLIP_CEILING) * p

    correct = rng.random() < p
    if not correct:
        return False, 0, rng.random() < 0.3

    if hint_farmer:
        return True, 2, False  # leans on hints whether or not they were needed
    gap = true_ability - difficulty
    if gap > 0.15:
        return True, 0, False
    if gap > -0.05:
        return True, rng.choice([0, 1]), False
    return True, rng.choice([1, 2]), False


# ---------------------------------------------------------------------------
# One closed-loop trial: real DB, real selection, real record_attempt


class _FrozenClock:
    """Stand-in for the `datetime` name selection calls .now() on.

    select_next reads wall-clock time for staleness and decay, with no
    injection point. Simulated last_seen timestamps sit in the past relative
    to the real clock, so without this every prereq's decayed mastery would
    collapse toward 0.5 on every read and nothing would unlock. Patched for
    one trial and restored immediately after.
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


@dataclass
class TrialResult:
    archetype: str
    true_ability: dict
    picks: list = field(default_factory=list)
    final_mastery: dict = field(default_factory=dict)
    final_attempts: dict = field(default_factory=dict)
    decayed_mastery: dict = field(default_factory=dict)
    stalls: int = 0


def run_trial(
    archetype: Archetype,
    rng: random.Random,
    target_attempts: int,
    student_id: str,
    *,
    misspecified: bool,
) -> TrialResult:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)

    with Session(engine) as session:
        skills = load_taxonomy(COURSE_ID)
        for skill in skills:
            session.add(skill)
        session.commit()

        depths = compute_depths(skills)
        true_ability = draw_abilities(archetype, skills, depths, rng)
        result = TrialResult(archetype=archetype.name, true_ability=true_ability)

        clock = {"now": datetime(2026, 1, 1, tzinfo=timezone.utc)}
        original_clock = selection.datetime
        selection.datetime = _FrozenClock(lambda: clock["now"])

        try:
            done = 0
            sitting = 0
            while done < target_attempts:
                sitting += 1
                for _ in range(rng.randint(*SESSION_SIZE_RANGE)):
                    if done >= target_attempts:
                        break

                    spec = selection.select_next(session, COURSE_ID, student_id)
                    if spec is None:
                        # calc1's root skills are unlocked vacuously, so this
                        # should never happen.
                        result.stalls += 1
                        break

                    correct, hints, partial = simulate_outcome(
                        true_ability[spec.skill_id],
                        spec.target_difficulty,
                        rng,
                        hint_farmer=archetype.hint_farmer,
                        misspecified=misspecified,
                    )
                    outcome = student_model_service.record_attempt(
                        session,
                        COURSE_ID,
                        AttemptCreate(
                            student_id=student_id,
                            session_id=f"sitting-{sitting}",
                            problem_id=f"sim-{done}",  # unique: one attempt per problem
                            expected_skills=[spec.skill_id],
                            difficulty=spec.target_difficulty,
                            correct=correct,
                            partial=partial,
                            hints_used=hints,
                        ),
                    )

                    # Time-travel: rewrite the timestamps record_attempt just
                    # set to simulated "now", so decay and recency operate on
                    # simulated time without monkeypatching the service.
                    now = clock["now"]
                    state = session.get(SkillState, (student_id, spec.skill_id))
                    state.last_seen = now
                    session.add(state)
                    attempt_row = session.get(Attempt, outcome.attempt_id)
                    attempt_row.created_at = now
                    session.add(attempt_row)
                    session.commit()

                    result.picks.append(Pick(spec.skill_id, spec.is_review))
                    done += 1

                if result.stalls and done < target_attempts:
                    break

                clock["now"] += timedelta(
                    days=rng.uniform(*BREAK_GAP_DAYS)
                    if rng.random() < BREAK_PROBABILITY
                    else rng.uniform(*TYPICAL_GAP_DAYS)
                )

            final_now = clock["now"] + timedelta(days=FINAL_LOOKAHEAD_DAYS)
            for skill in skills:
                state = session.get(SkillState, (student_id, skill.id))
                if state is None:
                    continue
                result.final_mastery[skill.id] = state.mastery
                result.final_attempts[skill.id] = state.attempts
                last_seen = state.last_seen
                if last_seen is None:
                    result.decayed_mastery[skill.id] = state.mastery
                    continue
                if last_seen.tzinfo is None:  # SQLite round-trip drops tzinfo
                    last_seen = last_seen.replace(tzinfo=timezone.utc)
                result.decayed_mastery[skill.id] = apply_decay(
                    state.mastery, (final_now - last_seen).total_seconds() / 86400
                )
        finally:
            selection.datetime = original_clock

        return result


# ---------------------------------------------------------------------------
# Analysis


def spearman(xs: list[float], ys: list[float]) -> float | None:
    n = len(xs)
    if n < 3:
        return None

    def ranks(values):
        order = sorted(range(n), key=lambda i: values[i])
        out = [0.0] * n
        i = 0
        while i < n:
            j = i
            while j + 1 < n and values[order[j + 1]] == values[order[i]]:
                j += 1
            average = (i + j) / 2 + 1
            for k in range(i, j + 1):
                out[order[k]] = average
            i = j + 1
        return out

    rx, ry = ranks(xs), ranks(ys)
    mx, my = sum(rx) / n, sum(ry) / n
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    den = math.sqrt(sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry))
    return num / den if den else None


def analyze(trial: TrialResult, skills: list[Skill]) -> dict:
    converged = [
        sid
        for sid, n in trial.final_attempts.items()
        if n >= CONVERGENCE_MIN_ATTEMPTS
    ]
    estimates = [trial.final_mastery[s] for s in converged]
    truths = [trial.true_ability[s] for s in converged]

    served = {p.skill_id for p in trial.picks}
    starved = [
        s.id
        for s in skills
        if s.id not in served
        and all(
            trial.decayed_mastery.get(p, 0.5) >= selection.UNLOCK_THRESHOLD
            for p in s.prereqs
        )
    ]

    return {
        "archetype": trial.archetype,
        "mae": (
            sum(abs(e - t) for e, t in zip(estimates, truths)) / len(estimates)
            if estimates
            else None
        ),
        "corr": spearman(estimates, truths),
        "converged": len(converged),
        "skills_total": len(skills),
        "skills_reached": len(served),
        "review_rate": (
            sum(1 for p in trial.picks if p.is_review) / len(trial.picks)
            if trial.picks
            else 0.0
        ),
        "starved": starved,
        "stalls": trial.stalls,
    }


def average(reports: list[dict]) -> dict:
    def mean(key):
        values = [r[key] for r in reports if r[key] is not None]
        return sum(values) / len(values) if values else None

    starved = set(reports[0]["starved"])
    for r in reports[1:]:
        starved &= set(r["starved"])

    return {
        "archetype": reports[0]["archetype"],
        "mae": mean("mae"),
        "corr": mean("corr"),
        "converged": mean("converged"),
        "skills_total": reports[0]["skills_total"],
        "skills_reached": mean("skills_reached"),
        "review_rate": mean("review_rate"),
        "starved_persistent": sorted(starved),  # starved in EVERY trial
        "stalls": sum(r["stalls"] for r in reports),
    }


def print_report(summary: dict) -> None:
    mae = f"{summary['mae']:.3f}" if summary["mae"] is not None else "n/a"
    corr = f"{summary['corr']:.3f}" if summary["corr"] is not None else "n/a"
    print(f"\n{summary['archetype']}")
    print(
        f"  convergence:  MAE={mae}  spearman={corr}  "
        f"({summary['converged']:.1f} skills with >={CONVERGENCE_MIN_ATTEMPTS} attempts)"
    )
    print(
        f"  coverage:     {summary['skills_reached']:.1f}/{summary['skills_total']} "
        f"skills served   review={summary['review_rate'] * 100:.1f}%"
    )
    if summary["starved_persistent"]:
        print(f"  STARVED:      {summary['starved_persistent']}")
    if summary["stalls"]:
        print(f"  STALLS:       {summary['stalls']}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--attempts", type=int, default=600)
    parser.add_argument("--trials", type=int, default=3)
    parser.add_argument("--archetype", type=str, default=None)
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument(
        "--misspecified",
        action="store_true",
        help="sample outcomes from a 3PL model with guessing and slips, which "
             "the estimator does not model -- the run that can actually fail",
    )
    args = parser.parse_args()

    archetypes = (
        [a for a in ARCHETYPES if a.name == args.archetype]
        if args.archetype
        else ARCHETYPES
    )
    if args.archetype and not archetypes:
        print(f"unknown archetype {args.archetype!r}; choices: {[a.name for a in ARCHETYPES]}")
        return 2

    mode = "3PL (guessing + slips)" if args.misspecified else "logistic (well-specified)"
    print(f"outcome model: {mode}")

    started = time.time()
    failures = []

    for index, archetype in enumerate(archetypes):
        reports, last = [], None
        for i in range(args.trials):
            # Not hash(name): Python randomizes str hashing per process, which
            # would make --seed non-reproducible despite looking deterministic.
            rng = random.Random(args.seed + index * 1000 + i)
            trial = run_trial(
                archetype, rng, args.attempts,
                student_id=f"sim-{archetype.name}-{i}",
                misspecified=args.misspecified,
            )
            skills = load_taxonomy(COURSE_ID)
            reports.append(analyze(trial, skills))
            last = (trial, skills)

        summary = average(reports)
        print_report(summary)

        if args.verbose and last is not None:
            trial, skills = last
            depths = compute_depths(skills)
            print("  per-skill (last trial):")
            for skill in sorted(skills, key=lambda s: depths[s.id]):
                n = sum(1 for p in trial.picks if p.skill_id == skill.id)
                mastery = trial.final_mastery.get(skill.id)
                shown = f"{mastery:.2f}" if mastery is not None else "  -"
                print(
                    f"    d{depths[skill.id]}  {skill.id:45s} n={n:3d}  "
                    f"mastery={shown}  true={trial.true_ability[skill.id]:.2f}"
                )

        if summary["stalls"]:
            failures.append(f"{archetype.name}: {summary['stalls']} stall(s)")
        if summary["starved_persistent"]:
            failures.append(
                f"{archetype.name}: unlocked but never served: "
                f"{summary['starved_persistent']}"
            )
        if archetype.name in ("average", "strong") and summary["mae"] is not None:
            # Correlation is not gated for these two: both draw ability from a
            # tight cluster around one base, so small true between-skill spread
            # caps rank correlation regardless of estimator quality (range
            # restriction). MAE is the meaningful metric here.
            if summary["mae"] >= MAE_LIMIT:
                failures.append(
                    f"{archetype.name}: MAE {summary['mae']:.3f} >= {MAE_LIMIT}"
                )
        if archetype.name == "uneven_advanced_gap":
            if summary["corr"] is not None and summary["corr"] <= 0.7:
                failures.append(
                    f"uneven_advanced_gap: spearman {summary['corr']:.3f} <= 0.7"
                )
            if summary["review_rate"] <= 0.0:
                failures.append(
                    "uneven_advanced_gap: forced review never fired despite a real "
                    "shallow/deep mastery gap"
                )
        if archetype.name == "strong" and summary["skills_reached"] < summary["skills_total"] * 0.85:
            failures.append(
                f"strong: only reached {summary['skills_reached']:.1f}/"
                f"{summary['skills_total']} skills -- unlock gating too conservative?"
            )

    print(
        f"\n({time.time() - started:.1f}s, {args.trials} trials x {args.attempts} "
        f"attempts x {len(archetypes)} archetypes)\n"
    )
    if failures:
        print("FAILED:")
        for f in failures:
            print(f"  - {f}")
        return 1

    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
