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
from sqlmodel import Session, select

from app.api.dependencies import get_session
from app.config import missing_indexing_settings
from app.models.enums import SkillOrigin
from app.models.skill_proposal import ProposalStatus, SkillProposal
from app.schemas.taxonomy import TaxonomyPlan
from app.schemas.learning import AttemptCreate, AttemptResult
from app.services import proposals, student_model_service
from app.services.student_model_service import UnknownSkillError
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


@router.post("/courses/{course_id}/attempts", response_model=AttemptResult,
             include_in_schema=False)
def create_synthetic_attempt(
    course_id: str,
    payload: AttemptCreate,
    session: Session = Depends(get_session),
):
    """Record an attempt from an explicitly stated outcome. Dev only.

    This route takes `correct` from its caller, which is exactly why it is not
    on the product API: a client that states its own grade can set any
    student's mastery to the ceiling. Real work goes through POST
    /api/courses/{id}/work, where the tutor decides. This exists so the
    dashboard can drive the loop without a canvas and a model call.
    """
    try:
        return student_model_service.record_attempt(session, course_id, payload)
    except UnknownSkillError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/courses/{course_id}/proposals", include_in_schema=False)
def list_proposals(course_id: str, session: Session = Depends(get_session)) -> dict:
    """Skills the generator keeps naming that this course doesn't have."""
    rows = session.exec(
        select(SkillProposal)
        .where(SkillProposal.course_id == course_id)
        .order_by(SkillProposal.observations.desc())
    ).all()
    return {
        "proposals": [
            {
                "slug": p.slug,
                "name": p.name,
                "description": p.description,
                "observations": p.observations,
                "status": p.status.value,
                "resolved_skill_id": p.resolved_skill_id,
                "last_seen": p.last_seen.isoformat(),
            }
            for p in rows
        ],
        "min_observations": proposals.PROMOTION_MIN_OBSERVATIONS,
    }


@router.post("/courses/{course_id}/proposals/review", include_in_schema=False)
def review_course_proposals(
    course_id: str,
    session: Session = Depends(get_session),
) -> dict:
    """Promote or merge the proposals that have been named often enough.

    The only place outside seeding and cold-start bootstrap where a course's
    skill count grows. Uses embeddings to fold proposals that are an existing
    skill under another name; without an embedding provider configured it
    promotes on observation count alone and says so.
    """
    embed = None
    if not missing_indexing_settings():
        from app.services.embeddings import embed_texts

        embed = embed_texts

    report = proposals.review_proposals(session, course_id, embed=embed)
    return {
        "promoted": report.promoted,
        "merged": report.merged,
        "still_pending": report.still_pending,
        "skipped_semantic_check": report.skipped_semantic_check,
    }


@router.get("/dashboard", response_class=HTMLResponse, include_in_schema=False)
def dashboard() -> str:
    return _DASHBOARD_PATH.read_text(encoding="utf-8")
