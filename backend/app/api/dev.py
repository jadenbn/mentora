"""Dev-only learning-engine surface: the dashboard page and skills import.

Not part of the product: the dashboard is the only view of a course's whole
taxonomy with per-student mastery, so it is the tool for watching selection
and the mastery estimator behave. The page itself lives in
app/static/dashboard.html rather than a string literal here -- it is HTML,
CSS, and JavaScript, and it should be editable and lintable as such.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
from sqlmodel import Session

from app.api.dependencies import get_session
from app.models.enums import SkillOrigin
from app.schemas.taxonomy import TaxonomyPlan
from app.services.taxonomy import TaxonomyError, build_taxonomy, merge_generated

router = APIRouter(prefix="/dev", tags=["dev"])

_DASHBOARD_PATH = Path(__file__).resolve().parent.parent / "static" / "dashboard.html"


@router.post("/courses/{course_id}/skills/import", include_in_schema=False)
def import_skills(
    course_id: str,
    payload: TaxonomyPlan,
    session: Session = Depends(get_session),
) -> dict:
    """Post a raw skills batch straight into a course's taxonomy.

    Runs the same build_taxonomy -> merge_generated path every other skill
    source takes, so a pasted taxonomy is exercised exactly like a generated
    one -- the fastest way to test selection against a specific graph shape
    without spending a model call. Always tagged GENERATED; seed ids stay
    protected.
    """
    raw = [entry.model_dump() for entry in payload.skills]
    try:
        produced = build_taxonomy(course_id, raw, SkillOrigin.GENERATED)
        report = merge_generated(session, course_id, produced)
    except TaxonomyError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {
        "added": report.added,
        "updated": report.updated,
        "blocked_seed_collisions": report.blocked_seed_collisions,
    }


@router.get("/dashboard", response_class=HTMLResponse, include_in_schema=False)
def dashboard() -> str:
    return _DASHBOARD_PATH.read_text(encoding="utf-8")
