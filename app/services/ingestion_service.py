"""
app/services/ingestion_service.py — Section 15.2 (Admin App Services)

Triggers ingestion for a lecture. Enforces the Section 22.7 pacing guideline
(soft daily cap) as a courtesy warning — the operator can still force it, but
the dashboard/API makes the shared-budget risk (Section 25.12) visible rather
than silent.
"""
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.logging import logger
from app.db.models import ProcessingStatus
from app.services import lecture_service
from app.workers.worker_queue import enqueue_ingestion_job

settings = get_settings()


class DailyIngestionCapExceeded(Exception):
    pass


async def trigger_ingestion(
    db: AsyncSession, lecture_id: uuid.UUID, force: bool = False
) -> None:
    lecture = await lecture_service.get_lecture(db, lecture_id)
    if lecture is None:
        raise ValueError(f"Lecture {lecture_id} not found")

    if lecture.processing_status == ProcessingStatus.PROCESSING:
        logger.warning(f"ingestion_already_running lecture_id={lecture_id}")
        return

    if not force:
        today_count = await lecture_service.count_lectures_ingested_today(db)
        if today_count >= settings.MAX_LECTURES_INGESTED_PER_DAY:
            raise DailyIngestionCapExceeded(
                f"Daily ingestion cap of {settings.MAX_LECTURES_INGESTED_PER_DAY} lectures "
                f"reached (Section 22.7 — protects the Client App's share of the shared Groq "
                f"budget, Section 20.7). Pass force=True to override, or wait until tomorrow."
            )

    await enqueue_ingestion_job(lecture_id)
    logger.info(f"ingestion_enqueued lecture_id={lecture_id} force={force}")


async def trigger_reprocessing(db: AsyncSession, lecture_id: uuid.UUID) -> None:
    """
    Section 25.9 (Course-Level Composition Drift): reprocessing an already-
    completed lecture is what the Client App's cache layer watches for to
    invalidate stale CachedAnswer/StudyNote rows referencing this lecture.
    """
    from app.ingestion.status_tracker import mark_reprocessed

    await mark_reprocessed(db, lecture_id)
    await enqueue_ingestion_job(lecture_id)
    logger.info(f"reprocessing_enqueued lecture_id={lecture_id}")
