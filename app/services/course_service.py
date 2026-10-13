"""
app/services/course_service.py — Section 15.2 (Admin App Services)
"""
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Course


async def create_course(db: AsyncSession, course_code: str, title: str, description: str = "") -> Course:
    course = Course(course_code=course_code, title=title, description=description)
    db.add(course)
    await db.commit()
    await db.refresh(course)
    return course


async def list_courses(db: AsyncSession) -> list[Course]:
    result = await db.execute(select(Course).order_by(Course.created_at.desc()))
    return list(result.scalars().all())


async def get_course(db: AsyncSession, course_id: uuid.UUID) -> Course | None:
    result = await db.execute(select(Course).where(Course.id == course_id))
    return result.scalar_one_or_none()


async def update_course(
    db: AsyncSession, course_id: uuid.UUID, title: str | None = None, description: str | None = None
) -> Course | None:
    course = await get_course(db, course_id)
    if not course:
        return None
    if title is not None:
        course.title = title
    if description is not None:
        course.description = description
    await db.commit()
    await db.refresh(course)
    return course


async def delete_course(db: AsyncSession, course_id: uuid.UUID) -> bool:
    course = await get_course(db, course_id)
    if not course:
        return False
    await db.delete(course)
    await db.commit()
    return True
