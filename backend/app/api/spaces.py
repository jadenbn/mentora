"""API routes for space CRUD, scoped to a course."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response

from app.api.dependencies import get_course_repository
from app.database import CourseRepository
from app.schemas.spaces import Space, SpaceCreate, SpaceUpdate

router = APIRouter(prefix="/api/courses/{course_id}/spaces", tags=["spaces"])


@router.post("", response_model=Space)
async def create_space(
    course_id: str,
    request: SpaceCreate,
    repository: CourseRepository = Depends(get_course_repository),
) -> Space:
    if repository.get_course(course_id) is None:
        raise HTTPException(404, "Course was not found")
    try:
        return repository.create_space(
            course_id=course_id, title=request.title, problem_id=request.problem_id
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("", response_model=list[Space])
async def list_spaces(
    course_id: str,
    repository: CourseRepository = Depends(get_course_repository),
) -> list[Space]:
    return repository.list_spaces(course_id)


@router.patch("/{space_id}", response_model=Space)
async def update_space(
    course_id: str,
    space_id: str,
    request: SpaceUpdate,
    repository: CourseRepository = Depends(get_course_repository),
) -> Space:
    space = repository.get_space(space_id)
    if space is None or space.course_id != course_id:
        raise HTTPException(404, "Space was not found")
    updated = repository.update_space(space_id, title=request.title)
    assert updated is not None
    return updated


@router.delete("/{space_id}", status_code=204, response_class=Response)
async def delete_space(
    course_id: str,
    space_id: str,
    repository: CourseRepository = Depends(get_course_repository),
) -> Response:
    space = repository.get_space(space_id)
    if space is None or space.course_id != course_id:
        raise HTTPException(404, "Space was not found")
    repository.delete_space(space_id)
    return Response(status_code=204)
