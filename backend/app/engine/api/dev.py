"""Dev-only learning-engine surface: the dashboard page and skills import.

Not part of the product: there is no student-facing view of the engine at
all, so the dashboard is the only way to see a course's topic list, a
student's per-topic accuracy, and drive the loop with synthetic attempts.
The page itself lives in app/static/dashboard.html rather than a string
literal here -- it is HTML, CSS, and JavaScript, and should be editable and
lintable as such.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse
from sqlmodel import Session, select

from app.api.dependencies import get_session, require_course
from app.models.enums import SkillOrigin
from app.models.problem_skill import ProblemSkill
from app.models.skill import Skill
from app.engine.models.skill_state import SkillState
from app.engine.schemas import AttemptCreate, AttemptResult
from app.schemas.taxonomy import TaxonomyPlan
from app.engine import simulation, student_model_service
from app.engine.selection import mark_served, pick_topic
from app.engine.student_model_service import UnknownSkillError
from app.services.taxonomy import TaxonomyError, add_skills, build_taxonomy

router = APIRouter(prefix="/dev", tags=["dev"])

_DASHBOARD_PATH = Path(__file__).resolve().parent.parent / "static" / "dashboard.html"


@router.post("/courses/{course_id}/skills/import", include_in_schema=False)
def import_skills(
    course_id: str,
    payload: TaxonomyPlan,
    session: Session = Depends(get_session),
    _course=Depends(require_course),
) -> dict:
    """Post a raw topic batch straight into a course.

    Runs the same build_taxonomy -> add_skills path the piggyback takes, so a
    pasted list is exercised exactly like model-identified topics -- the
    fastest way to test a course's topic list without a model call.
    """
    raw = [entry.model_dump() for entry in payload.skills]
    try:
        produced = build_taxonomy(course_id, raw, SkillOrigin.GENERATED)
        added = add_skills(session, course_id, produced)
    except TaxonomyError as exc:
        raise HTTPException(400, str(exc)) from exc
    requested_ids = {s.id for s in produced}
    skipped = sorted(requested_ids - set(added))
    return {"added": added, "skipped": skipped}


@router.delete("/courses/{course_id}/skills/{skill_id}", include_in_schema=False)
def delete_skill(
    course_id: str,
    skill_id: str,
    session: Session = Depends(get_session),
    _course=Depends(require_course),
) -> dict:
    """Remove one topic from a course. Dev only, and deliberately not on the
    product API: nothing a student does should be able to delete a topic.

    `add_skills` only ever inserts, so before this route the only way to undo
    a bad piggyback mint (a typo'd name, a duplicate the canonical key missed)
    was editing SQLite by hand.

    What goes with it:

    - `ProblemSkill` rows cascade on the real foreign key, so problems already
      attributed to this topic lose that attribution. A later attempt on such
      a problem resolves to no known skill and records nothing, which is the
      same path a hand-deleted skill already took.
    - `SkillState` rows are deleted explicitly, because that table has no
      foreign key to `skill.id`. Leaving them would not just leak rows: skill
      ids are deterministic (`normalize_slug`), so re-importing a topic under
      the same name would silently adopt the deleted topic's per-student
      history.
    - `Attempt` rows are left completely alone. The ledger is immutable and
      stores its own resolved `expected_skills`, so history stays readable
      even for a topic that no longer exists.
    """
    skill = session.get(Skill, skill_id)
    if skill is None or skill.course_id != course_id:
        raise HTTPException(404, f"skill '{skill_id}' is not a topic in this course")

    states = session.exec(
        select(SkillState).where(SkillState.skill_id == skill_id)
    ).all()
    attributions = session.exec(
        select(ProblemSkill).where(ProblemSkill.skill_id == skill_id)
    ).all()

    for state in states:
        session.delete(state)
    session.delete(skill)
    session.commit()

    return {
        "deleted": skill_id,
        "skill_states_removed": len(states),
        "problem_attributions_removed": len(attributions),
    }


@router.post("/courses/{course_id}/attempts", response_model=AttemptResult,
             include_in_schema=False)
def create_synthetic_attempt(
    course_id: str,
    payload: AttemptCreate,
    session: Session = Depends(get_session),
    _course=Depends(require_course),
):
    """Record an attempt from an explicitly stated outcome. Dev only.

    This route takes `correct` from its caller, which is exactly why it is
    not on the product API. Real work goes through POST
    /api/courses/{id}/work, where the tutor decides. This exists so the
    dashboard can drive the loop without a canvas and a model call.

    It stamps last_served as well as recording, because on the real path a
    topic is always served before it is marked. Without that the dashboard
    would show selection behaving differently here than it does in
    production -- the recency penalty would never fire.
    """
    try:
        result = student_model_service.record_attempt(session, course_id, payload)
    except UnknownSkillError as exc:
        raise HTTPException(400, str(exc)) from exc
    if payload.expected_skills:
        mark_served(session, course_id, payload.student_id, payload.expected_skills[0])
    return result


@router.get("/courses/{course_id}/next-topic", include_in_schema=False)
def preview_next_topic(
    course_id: str,
    student_id: str,
    session: Session = Depends(get_session),
    _course=Depends(require_course),
) -> dict:
    """What pick_topic would choose right now, without serving it.

    The product has no "next topic" route on purpose -- selection happens
    inside question generation. This is the dashboard's window onto that
    decision, and it is read-only: it does not stamp last_served, so looking
    at the answer does not change it.
    """
    pick = pick_topic(session, course_id, student_id)
    if pick is None:
        raise HTTPException(404, f"course '{course_id}' has no topics")
    return {"skill_id": pick.skill_id, "target_difficulty": pick.target_difficulty}


@router.post("/courses/{course_id}/simulate", include_in_schema=False)
def simulate_course(
    course_id: str,
    profile: str = Query(default="mixed"),
    students: int = Query(default=12, ge=1, le=60),
    questions_each: int = Query(default=24, ge=1, le=200),
    seed: int = 0,
    session: Session = Depends(get_session),
    _course=Depends(require_course),
) -> dict:
    """Replay the selection policy against synthetic students. Dev only.

    Answers the questions pytest cannot: does a student's accuracy actually
    rise, how much of the course do they reach, does difficulty track. Runs
    against a throwaway in-memory database -- no synthetic student is ever
    written to mentora.db, so this is safe to run against a live course.

    `profile` picks the cohort's ability range and learning rate (see
    simulation.STUDENT_PROFILES) -- `students` alone only adds more of the
    same cohort, which narrows noise but tests nothing new.
    """
    skills = session.exec(select(Skill).where(Skill.course_id == course_id)).all()
    if not skills:
        raise HTTPException(404, f"course '{course_id}' has no topics to simulate")
    try:
        report = simulation.simulate(
            list(skills),
            profile=profile,
            students=students,
            questions_each=questions_each,
            seed=seed,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return report.as_dict()


@router.get("/dashboard", response_class=HTMLResponse, include_in_schema=False)
def dashboard() -> str:
    return _DASHBOARD_PATH.read_text(encoding="utf-8")
