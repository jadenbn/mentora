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

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
from sqlmodel import Session

from app.api.dependencies import get_session
from app.models.enums import SkillOrigin
from app.schemas.learning import AttemptCreate, AttemptResult
from app.schemas.taxonomy import TaxonomyPlan
from app.services import student_model_service
from app.services.student_model_service import UnknownSkillError
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
    """
    try:
        return student_model_service.record_attempt(session, course_id, payload)
    except UnknownSkillError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/dashboard", response_class=HTMLResponse, include_in_schema=False)
def dashboard() -> str:
    return _DASHBOARD_PATH.read_text(encoding="utf-8")
