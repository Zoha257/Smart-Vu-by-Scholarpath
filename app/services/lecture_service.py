"""
app/services/lecture_service.py — Section 15.2 (Admin App Services)
"""
import shutil
import uuid
from pathlib import Path

from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.logging import logger
from app.db.models import Lecture, LectureSourceType, ProcessingStatus

settings = get_settings()


async def create_lecture(
    db: AsyncSession,
    course_id: uuid.UUID,
    title: str,
    lecture_number: int,
    source_url: str | None = None,
) -> Lecture:
    """
    Section 21.3: source_url should prefer the VU Open Courseware portal
    where a direct downloadable file is available, falling back to an
    authorized YouTube embed URL otherwise.

    If source_url is None, the lecture is created as an UPLOAD-sourced
    lecture; the operator must then call save_uploaded_video() (via
    POST /api/admin/lectures/{id}/upload-video) before triggering ingestion.
    """
    lecture = Lecture(
        course_id=course_id,
        title=title,
        lecture_number=lecture_number,
        source_type=LectureSourceType.URL if source_url else LectureSourceType.UPLOAD,
        source_url=source_url,
        processing_status=ProcessingStatus.PENDING,
    )
    db.add(lecture)
    await db.commit()
    await db.refresh(lecture)
    return lecture


def _upload_dir_for(lecture_id: uuid.UUID) -> Path:
    return Path(settings.LOCAL_UPLOAD_DIR) / str(lecture_id)


async def save_uploaded_video(lecture_id: uuid.UUID, file: UploadFile) -> tuple[str, int]:
    """
    Streams an operator-uploaded video to disk in chunks (never fully
    buffered in memory, so this is safe for a multi-hundred-MB lecture
    file). The pipeline picks this up from the same location at ingestion
    time and deletes it afterwards, exactly as it deletes a yt-dlp-fetched
    file (Section 21.3 — never stored permanently).

    Returns (stored_filename, size_bytes).
    """
    dest_dir = _upload_dir_for(lecture_id)
    dest_dir.mkdir(parents=True, exist_ok=True)

    # Clear out any previous upload for this lecture (e.g. a retry).
    for existing in dest_dir.glob("source.*"):
        existing.unlink()

    suffix = Path(file.filename or "").suffix or ".mp4"
    dest_path = dest_dir / f"source{suffix}"

    max_bytes = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024
    size = 0
    chunk_size = 8 * 1024 * 1024  # 8MB chunks

    with open(dest_path, "wb") as out:
        while chunk := await file.read(chunk_size):
            size += len(chunk)
            if size > max_bytes:
                out.close()
                dest_path.unlink(missing_ok=True)
                raise ValueError(
                    f"Upload exceeds MAX_UPLOAD_SIZE_MB={settings.MAX_UPLOAD_SIZE_MB}MB"
                )
            out.write(chunk)

    logger.info(f"lecture_video_uploaded lecture_id={lecture_id} size_bytes={size} path={dest_path}")
    return dest_path.name, size


def get_uploaded_video_path(lecture_id: uuid.UUID) -> Path | None:
    """Used by the ingestion pipeline (Section 5.6) to locate an uploaded file."""
    dest_dir = _upload_dir_for(lecture_id)
    candidates = list(dest_dir.glob("source.*"))
    return candidates[0] if candidates else None


def cleanup_uploaded_video(lecture_id: uuid.UUID) -> None:
    """Called by the pipeline after ingestion completes (Section 21.3)."""
    dest_dir = _upload_dir_for(lecture_id)
    if dest_dir.exists():
        shutil.rmtree(dest_dir, ignore_errors=True)


async def list_lectures(db: AsyncSession, course_id: uuid.UUID | None = None) -> list[Lecture]:
    stmt = select(Lecture).order_by(Lecture.lecture_number)
    if course_id:
        stmt = stmt.where(Lecture.course_id == course_id)
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def get_lecture(db: AsyncSession, lecture_id: uuid.UUID) -> Lecture | None:
    result = await db.execute(select(Lecture).where(Lecture.id == lecture_id))
    return result.scalar_one_or_none()


async def delete_lecture(db: AsyncSession, lecture_id: uuid.UUID) -> bool:
    lecture = await get_lecture(db, lecture_id)
    if not lecture:
        return False
    await db.delete(lecture)
    await db.commit()
    return True


async def count_lectures_ingested_today(db: AsyncSession) -> int:
    """
    Supports Section 22.7's ingestion-pacing guideline: the operator should
    not process an entire course in one day (shared Groq budget, Section
    20.7 / 25.12). This counts lectures whose processing started today.
    """
    from datetime import datetime, timezone

    from sqlalchemy import func

    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=None)
    stmt = select(func.count(Lecture.id)).where(
        Lecture.updated_at >= today_start,
        Lecture.processing_status != ProcessingStatus.PENDING,
    )
    result = await db.execute(stmt)
    return result.scalar_one()
