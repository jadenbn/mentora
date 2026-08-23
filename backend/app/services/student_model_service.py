"""Attempt ingestion: validates against a problem's declared skills, updates
mastery, and answers what a student currently knows for a course."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlmodel import Session, select

from app.models.attempt import Attempt
from app.models.skill import Skill
from app.models.skill_state import SkillState
from app.models.student_profile import StudentProfile
from app.schemas.learning import AttemptCreate, AttemptResult, SkillStateOut, StudentModelResponse
from app.schemas.tutor import StudentModelSnapshot
from app.services.mastery import apply_decay, confidence, prereq_delta, score_attempt, update_mastery

logger = logging.getLogger(__name__)

TOP_MISCONCEPTIONS_LIMIT = 3
STRENGTH_MASTERY_THRESHOLD = 0.75
STRENGTH_CONFIDENCE_THRESHOLD = 0.5


class UnknownSkillError(ValueError):
    """An attempt declared expected_skills not present in the course taxonomy."""


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _update_streak(streak: int, correct: bool) -> int:
    if correct:
        return streak + 1 if streak >= 0 else 1
    return streak - 1 if streak <= 0 else -1


def _get_or_create_profile(session: Session, student_id: str, course_id: str) -> StudentProfile:
    profile = session.get(StudentProfile, (student_id, course_id))
    if profile is None:
        profile = StudentProfile(student_id=student_id, course_id=course_id)
        session.add(profile)
        session.flush()
    return profile


def _get_or_create_skill_state(
    session: Session, student_id: str, course_id: str, skill_id: str, seed_mastery: float
) -> SkillState:
    state = session.get(SkillState, (student_id, skill_id))
    if state is None:
        state = SkillState(
            student_id=student_id,
            course_id=course_id,
            skill_id=skill_id,
            mastery=seed_mastery,
        )
        session.add(state)
        session.flush()
    return state


def record_attempt(session: Session, course_id: str, payload: AttemptCreate) -> AttemptResult:
    expected_skills = payload.expected_skills
    skills = session.exec(
        select(Skill).where(Skill.course_id == course_id, Skill.id.in_(expected_skills))
    ).all()
    found_ids = {s.id for s in skills}
    missing = set(expected_skills) - found_ids
    if missing:
        raise UnknownSkillError(
            f"expected_skills not found in course '{course_id}': {sorted(missing)}"
        )
    skills_by_id = {s.id: s for s in skills}

    # The guard: an error naming a skill outside this attempt's declared
    # expected_skills is dropped and logged, never trusted. Without this,
    # one misread canvas from grading can corrupt a skill the student never
    # touched, with nothing in the table recording why.
    valid_errors = [e for e in payload.errors if e.skill_id in expected_skills]
    dropped = len(payload.errors) - len(valid_errors)
    if dropped:
        logger.warning(
            "dropped %d error(s) naming skills outside expected_skills %s",
            dropped,
            expected_skills,
        )

    profile = _get_or_create_profile(session, payload.student_id, course_id)
    score = score_attempt(
        correct=payload.correct,
        hints_used=payload.hints_used,
        partial=payload.partial,
        stuck_requests=payload.stuck_requests,
    )

    errors_by_skill: dict[str, list[str]] = {}
    for err in valid_errors:
        errors_by_skill.setdefault(err.skill_id, []).append(err.misconception.value)

    updated_skills: dict[str, float] = {}
    prereq_deltas: dict[str, float] = {}

    for skill_id in expected_skills:
        state = _get_or_create_skill_state(
            session, payload.student_id, course_id, skill_id, profile.global_ability
        )
        new_mastery = update_mastery(state.mastery, score, payload.difficulty, state.attempts)
        delta = new_mastery - state.mastery

        state.mastery = new_mastery
        state.attempts += 1
        if (
            payload.correct
            and payload.hints_used == 0
            and payload.stuck_requests == 0
        ):
            state.correct_unassisted += 1
        state.streak = _update_streak(state.streak, payload.correct)
        if skill_id in errors_by_skill:
            # Reassign rather than mutate in place: SQLAlchemy doesn't track
            # in-place changes to a plain JSON column's contents, only
            # attribute reassignment, so an in-place update here would be
            # silently dropped on commit.
            counts = dict(state.misconception_counts)
            for tag in errors_by_skill[skill_id]:
                counts[tag] = counts.get(tag, 0) + 1
            state.misconception_counts = counts
        state.last_seen = _utcnow()
        session.add(state)

        updated_skills[skill_id] = new_mastery

        for prereq_id in skills_by_id[skill_id].prereqs:
            prereq_deltas[prereq_id] = prereq_deltas.get(prereq_id, 0.0) + prereq_delta(delta)

    # Bleed onto direct prerequisites only (one level), after the primary
    # skills are updated so a skill that is both a target and a prerequisite
    # of another target skill isn't double-counted against a stale mastery.
    for prereq_id, bleed in prereq_deltas.items():
        if prereq_id in updated_skills:
            continue
        prereq_state = _get_or_create_skill_state(
            session, payload.student_id, course_id, prereq_id, profile.global_ability
        )
        prereq_state.mastery = max(0.02, min(0.98, prereq_state.mastery + bleed))
        session.add(prereq_state)

    attempt = Attempt(
        student_id=payload.student_id,
        course_id=course_id,
        session_id=payload.session_id,
        problem_id=payload.problem_id,
        expected_skills=expected_skills,
        difficulty=payload.difficulty,
        correct=payload.correct,
        partial=payload.partial,
        hints_used=payload.hints_used,
        stuck_requests=payload.stuck_requests,
        total_time_ms=payload.total_time_ms,
        errors=[e.model_dump(mode="json") for e in valid_errors],
    )
    session.add(attempt)
    session.commit()

    return AttemptResult(attempt_id=attempt.id, updated_skills=updated_skills, dropped_errors=dropped)


def get_student_model(session: Session, course_id: str, student_id: str) -> StudentModelResponse:
    skills = session.exec(select(Skill).where(Skill.course_id == course_id)).all()
    now = _utcnow()

    out: list[SkillStateOut] = []
    for skill in skills:
        state = session.get(SkillState, (student_id, skill.id))
        if state is None:
            continue
        last_seen = state.last_seen
        if last_seen.tzinfo is None:
            last_seen = last_seen.replace(tzinfo=timezone.utc)
        days_since = (now - last_seen).total_seconds() / 86400
        decayed = apply_decay(state.mastery, days_since)
        top = sorted(state.misconception_counts.items(), key=lambda kv: -kv[1])
        out.append(
            SkillStateOut(
                skill_id=skill.id,
                skill_name=skill.name,
                mastery=decayed,
                confidence=confidence(state.attempts),
                attempts=state.attempts,
                top_misconceptions=[tag for tag, _ in top[:TOP_MISCONCEPTIONS_LIMIT]],
            )
        )

    return StudentModelResponse(student_id=student_id, course_id=course_id, skills=out)


def get_tutor_snapshot(
    session: Session,
    course_id: str,
    student_id: str,
    *,
    current_hint_count: int = 0,
) -> StudentModelSnapshot:
    """Adapt durable mastery state to the tutor's compact prompt contract."""
    model = get_student_model(session, course_id, student_id)
    attempts = session.exec(
        select(Attempt).where(
            Attempt.course_id == course_id,
            Attempt.student_id == student_id,
        )
    ).all()

    attempted_topics: list[str] = []
    recurring_mistakes: list[str] = []
    strengths: list[str] = []
    for skill in model.skills:
        if skill.attempts > 0:
            attempted_topics.append(skill.skill_name)
        recurring_mistakes.extend(
            f"{skill.skill_name}: {tag}" for tag in skill.top_misconceptions
        )
        if (
            skill.mastery >= STRENGTH_MASTERY_THRESHOLD
            and skill.confidence >= STRENGTH_CONFIDENCE_THRESHOLD
        ):
            strengths.append(skill.skill_name)

    return StudentModelSnapshot(
        attempted_topics=attempted_topics,
        recurring_mistakes=recurring_mistakes,
        strengths=strengths,
        total_hints_used=sum(attempt.hints_used for attempt in attempts)
        + current_hint_count,
    )
