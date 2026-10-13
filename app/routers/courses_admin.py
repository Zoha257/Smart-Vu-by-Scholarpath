"""
app/routers/courses_admin.py — Section 4.2, 5.7.2

Course create/manage routes. Admin-key protected (Section 17.2) — and, more
importantly, this whole router only exists in the Admin App's deployed
codebase, which is never bound to a public interface (Section 5.7.2, 18.5).
"""
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import require_admin_key
from app.db.session import get_db
from app.schemas import CourseCreate, CourseOut, CourseUpdate
from app.services import course_service

router = APIRouter(
    prefix="/api/admin/courses",
    tags=["admin:courses"],
    dependencies=[Depends(require_admin_key)],
)


@router.post("", response_model=CourseOut, status_code=status.HTTP_201_CREATED)
async def create_course(payload: CourseCreate, db: AsyncSession = Depends(get_db)):
    course = await course_service.create_course(
        db, payload.course_code, payload.title, payload.description
    )
    return course


@router.get("", response_model=list[CourseOut])
async def list_courses(db: AsyncSession = Depends(get_db)):
    return await course_service.list_courses(db)


@router.get("/{course_id}", response_model=CourseOut)
async def get_course(course_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    course = await course_service.get_course(db, course_id)
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")
    return course


@router.patch("/{course_id}", response_model=CourseOut)
async def update_course(
    course_id: uuid.UUID, payload: CourseUpdate, db: AsyncSession = Depends(get_db)
):
    course = await course_service.update_course(db, course_id, payload.title, payload.description)
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")
    return course


@router.delete("/{course_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_course(course_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    deleted = await course_service.delete_course(db, course_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Course not found")
