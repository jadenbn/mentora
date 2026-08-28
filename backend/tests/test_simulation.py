"""The replay harness: does the policy actually help a student?

Every other test here proves the mechanism is correct -- that a score lands
in the right window, that an unknown skill is refused. These are the only
tests that ask whether the *policy* is any good, which is the question the
tuning constants in services/selection.py were set by hand to answer.

They assert on direction and rough magnitude, never on exact numbers: the
synthetic learner is crude, and a test that pins the third decimal place of
a simulation is a test that fails every time a weight is tuned.
"""

from __future__ import annotations

import pytest
from sqlmodel import Session, SQLModel, create_engine

from app.models.skill import Skill
from app.services.simulation import simulate


@pytest.fixture
def session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


def _course(count: int = 15) -> list[Skill]:
    return [
        Skill(
            id=f"calc1.t{i}", course_id="calc1", name=f"Topic {i}",
            description="d", difficulty_band=0.2 + (i % 5) * 0.15,
        )
        for i in range(count)
    ]


def test_a_flat_pool_reaches_most_of_the_course():
    """The failure the unlock gate caused, measured.

    Under the gated design an average student reached 3 of 15 topics: the
    estimate was correct and the threshold was wrong, so most of the course
    stayed locked forever. A flat pool has no such wall.
    """
    report = simulate(_course(15), students=10, questions_each=30)
    assert report.coverage > 0.6


def test_growth_shows_up_as_harder_questions_not_higher_scores():
    """What "improving" looks like in an engine whose difficulty tracks the
    estimate: the student is served harder material at a similar score,
    rather than scoring higher on the same material. Asserting the score
    climbs would be asserting the servo is broken.
    """
    report = simulate(_course(12), students=12, questions_each=30)
    assert report.difficulty_late > report.difficulty_early
    # And the engine is not pushing them past what they can do.
    assert report.score_late > 0.35


def test_coverage_beats_a_topic_the_student_is_already_fine_on():
    """Why W_COVERAGE is 0.30 and not 0.20.

    At 0.20 a topic the student was scoring 0.58 on (weakness base 0.25)
    outranked every topic they had never seen, so the engine ground away at
    a handful of topics and the rest of the course stayed unvisited -- 6 of
    15 topics in 30 questions, measured here. This is the regression test
    for that number.
    """
    report = simulate(_course(15), students=10, questions_each=30)
    assert report.coverage > 0.6


def test_the_engine_does_not_serve_the_same_topic_twice_in_a_row():
    """What the recency penalty is for. Not zero -- a two-topic course has
    nowhere else to go -- but it should be rare on a real course."""
    report = simulate(_course(15), students=10, questions_each=24)
    assert report.repeat_rate < 0.05


def test_harder_questions_produce_lower_scores_on_average_across_seeds():
    """Difficulty calibration: the loop nothing used to close, measured
    honestly instead of pinned to whichever seed happens to look clean.

    `accuracy.difficulty_bucket` collapses a continuous target into three
    words in a prompt. If the level being asked for never reaches the
    student, this comes back flat -- but the metric is *confounded*, not
    just noisy: difficulty is defined as the student's own estimate for the
    topic (selection._target_difficulty), so a "challenging" question is by
    construction one served on a topic the student is already good at. A
    single seed asserted on its own is not a measurement of the policy; it
    is a coin flip over which side of the confound that run landed on --
    hand-checking seeds 1-11 here found the ordering inverted on 2 of them.
    Averaging over the sweep does not remove the confound. It answers a
    narrower, honest question: does the intended direction dominate on
    average. It does, robustly, on the course this suite simulates -- see
    docs/LEARNING_ENGINE.md and Horizon 1 of the engine review for the real
    fix (report the difficulty generation believes it wrote at, and
    calibrate against the delta from the target, rather than against the
    target itself).
    """
    names = ["introductory", "moderate", "challenging"]
    totals: dict[str, list[float]] = {name: [] for name in names}
    for seed in range(1, 12):
        report = simulate(_course(15), students=14, questions_each=30, seed=seed)
        for name, value in report.calibration.items():
            totals[name].append(value)

    averaged = [sum(totals[name]) / len(totals[name]) for name in names if totals[name]]
    assert len(averaged) >= 2, "sweep never spanned two difficulty buckets"
    assert averaged == sorted(averaged, reverse=True)


def test_a_realistic_pace_lets_staleness_compete_with_coverage():
    """What turning the simulator's clock on actually changes.

    Instant attempts (attempt_interval_days=0, the default) never give
    staleness anything to act on -- every topic's `last_seen` is always
    "just now". Real spacing does, and it interacts with coverage: once a
    topic's staleness saturates, a stale-but-known topic can outscore a
    topic the student has never touched at all (W_STALENESS=0.25 sits above
    the W_COVERAGE=0.30 floor once weakness is low), so a fixed question
    budget covers less new ground. This is a real property of the constants
    as they stand -- not a bug in the clock -- and retuning them for it is
    future work; this test exists so the interaction stays visible instead
    of silently regressing back to "never measured".
    """
    instant = simulate(_course(15), students=10, questions_each=30, seed=1)
    spaced = simulate(
        _course(15), students=10, questions_each=30, seed=1, attempt_interval_days=1.0
    )
    assert spaced.coverage < instant.coverage


def test_a_run_is_deterministic_for_a_given_seed():
    first = simulate(_course(10), students=5, questions_each=12, seed=3)
    second = simulate(_course(10), students=5, questions_each=12, seed=3)
    assert first == second


def test_simulating_a_course_with_no_topics_is_an_error():
    with pytest.raises(ValueError):
        simulate([])


def test_the_simulation_never_writes_to_the_real_database(session):
    """It runs the real record_attempt, so this is worth pinning down."""
    from app.models.attempt import Attempt
    from sqlmodel import select

    simulate(_course(5), students=2, questions_each=4)
    assert session.exec(select(Attempt)).all() == []
