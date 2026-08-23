"""API routes for attempt ingestion, student mastery, and problem selection."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session

from app.db import get_session
from app.schemas.learning import AttemptCreate, AttemptResult, GenerationSpec, StudentModelResponse
from app.services import selection, student_model_service
from app.services.student_model_service import UnknownSkillError

router = APIRouter(prefix="/api/courses/{course_id}", tags=["learning"])


@router.post("/attempts", response_model=AttemptResult)
def create_attempt(
    course_id: str,
    payload: AttemptCreate,
    session: Session = Depends(get_session),
):
    """Record an attempt, update the involved skills' mastery, and return the deltas."""
    try:
        return student_model_service.record_attempt(session, course_id, payload)
    except UnknownSkillError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/student-model", response_model=StudentModelResponse)
def get_student_model(
    course_id: str,
    student_id: str,
    session: Session = Depends(get_session),
):
    """Return this student's current mastery per skill, decayed for time elapsed."""
    return student_model_service.get_student_model(session, course_id, student_id)


@router.get("/next-problem-spec", response_model=GenerationSpec)
def get_next_problem_spec(
    course_id: str,
    student_id: str,
    session: Session = Depends(get_session),
):
    """Return what the next problem should target, without generating it."""
    spec = selection.select_next(session, course_id, student_id)
    if spec is None:
        raise HTTPException(404, f"no unlocked skills available for course '{course_id}'")
    return spec
