"""API routes for course CRUD."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response

from app.api.dependencies import get_course_repository
from app.database import CourseRepository
from app.schemas.courses import Course, CourseCreate, CourseUpdate

router = APIRouter(prefix="/api/courses", tags=["courses"])


@router.post("", response_model=Course)
async def create_course(
    request: CourseCreate,
    repository: CourseRepository = Depends(get_course_repository),
) -> Course:
    return repository.create_course(name=request.name, description=request.description)


@router.get("", response_model=list[Course])
async def list_courses(
    repository: CourseRepository = Depends(get_course_repository),
) -> list[Course]:
    return repository.list_courses()


@router.get("/{course_id}", response_model=Course)
async def get_course(
    course_id: str,
    repository: CourseRepository = Depends(get_course_repository),
) -> Course:
    course = repository.get_course(course_id)
    if course is None:
        raise HTTPException(404, "Course was not found")
    return course


@router.patch("/{course_id}", response_model=Course)
async def update_course(
    course_id: str,
    request: CourseUpdate,
    repository: CourseRepository = Depends(get_course_repository),
) -> Course:
    course = repository.update_course(
        course_id, name=request.name, description=request.description
    )
    if course is None:
        raise HTTPException(404, "Course was not found")
    return course


@router.delete("/{course_id}", status_code=204, response_class=Response)
async def delete_course(
    course_id: str,
    repository: CourseRepository = Depends(get_course_repository),
) -> Response:
    deleted = repository.delete_course(course_id)
    if not deleted:
        raise HTTPException(404, "Course was not found")
    return Response(status_code=204)
