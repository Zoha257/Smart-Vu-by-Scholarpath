"""
app/ingestion/status_tracker.py

Writes per-lecture processing status (Section 15.5): Pending, Processing,
Transcribing, Extracting Visuals, Generating Embeddings, Generating
Intelligence, Completed, Failed. The Client App reads this (read-only) to
build the course-notes readiness notice (Section 7.24: "5 of 8 lectures
processed").
"""
from uuid import UUID

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import logger
from app.db.models import Lecture, ProcessingStatus


async def set_status(
    db: AsyncSession, lecture_id: UUID, status: ProcessingStatus, error: str | None = None
) -> None:
    stmt = (
        update(Lecture)
        .where(Lecture.id == lecture_id)
        .values(processing_status=status, processing_error=error)
    )
    await db.execute(stmt)
    await db.commit()
    logger.info(f"status_update lecture_id={lecture_id} status={status.value}")


async def mark_reprocessed(db: AsyncSession, lecture_id: UUID) -> None:
    """
    Called when an operator triggers reprocessing of an already-completed
    lecture (e.g. to fix an OCR error). This status transition is what the
    Client App's cache layer watches for to invalidate stale CachedAnswer /
    StudyNote rows scoped to this lecture (Section 25.9, Course-Level
    Composition Drift).
    """
    await set_status(db, lecture_id, ProcessingStatus.REPROCESSED)
