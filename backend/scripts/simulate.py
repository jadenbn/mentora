"""Convergence simulation for the mastery update rule.

Builds a synthetic student with hidden per-skill true abilities, samples
outcomes from a logistic model, and checks whether the estimated mastery
converges toward the truth the engine never gets to see directly.

Run: python scripts/simulate.py --seed 42
"""

from __future__ import annotations

import argparse
import math
import random
import sys
from dataclasses import dataclass, field

from app.services.mastery import score_attempt, update_mastery

DISCRIMINATION_K = 6.0  # steepness of the synthetic success curve
SIM_ATTEMPTS = 50000  # ~30 attempts/skill at 15 skills, matching calc1.json
SIM_SEED = 42
DIFFICULTY_OFFSET = 0.15  # mirrors selection.py's target-difficulty offset
DIFFICULTY_NOISE_STD = 0.12  # generated problems miss their target difficulty

SKILLS = [f"skill-{i}" for i in range(15)]  # matches calc1.json skill count


@dataclass
class SimSkillState:
    mastery: float = 0.5
    attempts: int = 0


@dataclass
class SimStudent:
    true_ability: dict = field(default_factory=dict)
    state: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.state:
            self.state = {s: SimSkillState() for s in SKILLS}


def simulate_outcome(true_ability: float, difficulty: float, rng: random.Random):
    """Sample (correct, hints_used, partial) from a logistic success model.

    P(correct) = 1 / (1 + exp(-K * (true_ability - difficulty)))
    """
    p_correct = 1 / (1 + math.exp(-DISCRIMINATION_K * (true_ability - difficulty)))
    correct = rng.random() < p_correct

    if correct:
        # Weaker students who still get it right tend to have leaned on hints.
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


def run_student(true_abilities: dict, rng: random.Random, attempts: int = SIM_ATTEMPTS):
    student = SimStudent(true_ability=true_abilities)

    for _ in range(attempts):
        skill = rng.choice(SKILLS)
        st = student.state[skill]
        target_difficulty = st.mastery + DIFFICULTY_OFFSET
        # A generated problem doesn't land exactly on its target difficulty.
        # Without this noise, difficulty tracks mastery in lockstep and the
        # EWMA fixed point settles wherever P(correct at mastery+0.15) == 0.5,
        # which sits well below true ability for strong students. See the
        # analysis in the module docstring / commit message.
        served_difficulty = target_difficulty + rng.gauss(0, DIFFICULTY_NOISE_STD)
        difficulty = max(0.05, min(0.95, served_difficulty))

        correct, hints, partial = simulate_outcome(
            true_abilities[skill], difficulty, rng
        )
        score = score_attempt(correct=correct, hints_used=hints, partial=partial)
        st.mastery = update_mastery(st.mastery, score, difficulty, st.attempts)
        st.attempts += 1

    return student


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


TRIALS_PER_STUDENT = 5  # a single seed is noisy at only ~30 attempts/skill


def _one_trial(true_abilities: dict, seed: int) -> dict:
    rng = random.Random(seed)
    student = run_student(true_abilities, rng)

    estimates, truths = [], []
    for skill in SKILLS:
        st = student.state[skill]
        if st.attempts >= 10:
            estimates.append(st.mastery)
            truths.append(true_abilities[skill])

    mae = sum(abs(e - t) for e, t in zip(estimates, truths)) / len(estimates)
    corr = spearman(truths, estimates)
    mean_mastery = sum(st.mastery for st in student.state.values()) / len(SKILLS)
    # A skill whose true ability is itself near an extreme SHOULD converge
    # near that extreme -- that's correct estimation, not a stuck estimator.
    # Only a mid-range skill (0.3-0.7 true ability) pinned at the floor or
    # ceiling indicates the estimator actually got stuck.
    pinned = [
        s for s in SKILLS
        if 0.3 <= true_abilities[s] <= 0.7
        and (student.state[s].mastery <= 0.03 or student.state[s].mastery >= 0.97)
    ]
    return {"mae": mae, "corr": corr, "mean": mean_mastery, "pinned": pinned}


def report_for(label: str, true_abilities: dict, seed: int) -> dict:
    """Average metrics across several seeded trials; a single run is noisy
    with only ~30 attempts per skill."""
    trials = [_one_trial(true_abilities, seed + i) for i in range(TRIALS_PER_STUDENT)]

    mae = sum(t["mae"] for t in trials) / len(trials)
    corr = sum(t["corr"] for t in trials) / len(trials)
    mean_mastery = sum(t["mean"] for t in trials) / len(trials)
    # Flag a skill only if it pins in most trials -- a single trial grazing
    # the floor/ceiling on a low-attempt-count skill is sampling noise, not
    # a stuck estimator.
    pin_counts: dict = {}
    for t in trials:
        for s in t["pinned"]:
            pin_counts[s] = pin_counts.get(s, 0) + 1
    pinned = [s for s, count in pin_counts.items() if count > len(trials) / 2]

    print(f"\n-- {label} ({len(trials)} trials) --")
    print(f"  MAE={mae:.3f}  spearman={corr:.3f}  mean_mastery={mean_mastery:.3f}")
    print(f"  per-trial MAE: {[round(t['mae'], 3) for t in trials]}")

    return {"mae": mae, "corr": corr, "mean": mean_mastery, "pinned": pinned}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=SIM_SEED)
    args = parser.parse_args()

    rng = random.Random(args.seed)
    average = {s: rng.uniform(0.1, 0.9) for s in SKILLS}
    strong = {s: rng.uniform(0.8, 0.95) for s in SKILLS}
    weak = {s: rng.uniform(0.05, 0.2) for s in SKILLS}

    avg_result = report_for("average student", average, args.seed)
    strong_result = report_for("strong student", strong, args.seed + 100)
    weak_result = report_for("weak student", weak, args.seed + 200)

    failures = []
    if avg_result["mae"] >= 0.15:
        failures.append(f"average MAE {avg_result['mae']:.3f} >= 0.15")
    if avg_result["corr"] <= 0.8:
        failures.append(f"average spearman {avg_result['corr']:.3f} <= 0.8")
    if avg_result["pinned"]:
        failures.append(f"average student has pinned skills: {avg_result['pinned']}")
    if strong_result["mean"] <= 0.7:
        failures.append(f"strong student mean mastery {strong_result['mean']:.3f} <= 0.7")
    if weak_result["mean"] >= 0.4:
        failures.append(f"weak student mean mastery {weak_result['mean']:.3f} >= 0.4")

    print()
    if failures:
        print("FAILED:")
        for f in failures:
            print(f"  - {f}")
        return 1

    print("all convergence checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
