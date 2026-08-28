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

from app.api.dependencies import get_session
from app.models.enums import SkillOrigin
from app.models.skill import Skill
from app.engine.schemas import AttemptCreate, AttemptResult
from app.schemas.taxonomy import TaxonomyPlan
from app.engine import simulation, student_model_service
from app.engine.selection import mark_served, pick_topic
from app.engine.student_model_service import UnknownSkillError
from app.services.taxonomy import TaxonomyError, append_skills, build_taxonomy

router = APIRouter(prefix="/dev", tags=["dev"])

_DASHBOARD_PATH = Path(__file__).resolve().parent.parent / "static" / "dashboard.html"


@router.post("/courses/{course_id}/skills/import", include_in_schema=False)
def import_skills(
    course_id: str,
    payload: TaxonomyPlan,
    session: Session = Depends(get_session),
) -> dict:
    """Post a raw topic batch straight into a course, via the file.

    Runs the same build_taxonomy -> append_skills path the piggyback takes,
    so a pasted list is exercised exactly like model-identified topics --
    the fastest way to test a course's topic list without a model call.
    """
    raw = [entry.model_dump() for entry in payload.skills]
    try:
        produced = build_taxonomy(course_id, raw, SkillOrigin.GENERATED)
        added = append_skills(session, course_id, produced)
    except TaxonomyError as exc:
        raise HTTPException(400, str(exc)) from exc
    requested_ids = {s.id for s in produced}
    skipped = sorted(requested_ids - set(added))
    return {"added": added, "skipped": skipped}


@router.post("/courses/{course_id}/attempts", response_model=AttemptResult,
             include_in_schema=False)
def create_synthetic_attempt(
    course_id: str,
    payload: AttemptCreate,
    session: Session = Depends(get_session),
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
    students: int = Query(default=12, ge=1, le=60),
    questions_each: int = Query(default=24, ge=1, le=200),
    seed: int = 0,
    session: Session = Depends(get_session),
) -> dict:
    """Replay the selection policy against synthetic students. Dev only.

    Answers the questions pytest cannot: does a student's accuracy actually
    rise, how much of the course do they reach, does difficulty track. Runs
    against a throwaway in-memory database -- no synthetic student is ever
    written to mentora.db, so this is safe to run against a live course.
    """
    skills = session.exec(select(Skill).where(Skill.course_id == course_id)).all()
    if not skills:
        raise HTTPException(404, f"course '{course_id}' has no topics to simulate")
    report = simulation.simulate(
        list(skills), students=students, questions_each=questions_each, seed=seed
    )
    return report.as_dict()


@router.get("/dashboard", response_class=HTMLResponse, include_in_schema=False)
def dashboard() -> str:
    return _DASHBOARD_PATH.read_text(encoding="utf-8")
