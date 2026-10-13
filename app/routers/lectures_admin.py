"""
app/routers/lectures_admin.py — Section 4.2, 5.7.2
Lecture create/manage routes. Admin-key protected, private-network only.
"""
import uuid

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import require_admin_key
from app.db.models import LectureSourceType
from app.db.session import get_db
from app.schemas import LectureCreate, LectureOut, LectureUploadOut
from app.services import lecture_service

router = APIRouter(
    prefix="/api/admin/lectures",
    tags=["admin:lectures"],
    dependencies=[Depends(require_admin_key)],
)


@router.post("", response_model=LectureOut, status_code=status.HTTP_201_CREATED)
async def create_lecture(payload: LectureCreate, db: AsyncSession = Depends(get_db)):
    """
    Create a lecture record. If source_url is provided, the lecture is
    URL-sourced (pipeline will fetch it via yt-dlp/OCW at ingestion time).
    If source_url is omitted, the lecture is created as upload-sourced --
    follow up with POST /{lecture_id}/upload-video before triggering
    ingestion, or ingestion will fail with "no video source found".
    """
    lecture = await lecture_service.create_lecture(
        db, payload.course_id, payload.title, payload.lecture_number, payload.source_url
    )
    return lecture


@router.post("/{lecture_id}/upload-video", response_model=LectureUploadOut)
async def upload_lecture_video(
    lecture_id: uuid.UUID,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    """
    Local-file alternative to a source_url (Section 21.3). Accepts the raw
    lecture video directly from the operator's machine -- useful whenever a
    URL-based fetch (yt-dlp / OCW) is unreliable (e.g. YouTube's anti-bot
    challenge), since a manually-downloaded or screen-recorded file can be
    uploaded here instead. Streamed to disk in chunks, never fully buffered
    in memory, and deleted by the pipeline after ingestion completes --
    the same "never stored permanently" rule as a URL fetch.
    """
    lecture = await lecture_service.get_lecture(db, lecture_id)
    if not lecture:
        raise HTTPException(status_code=404, detail="Lecture not found")

    try:
        stored_filename, size_bytes = await lecture_service.save_uploaded_video(lecture_id, file)
    except ValueError as exc:
        raise HTTPException(status_code=413, detail=str(exc))

    lecture.source_type = LectureSourceType.UPLOAD
    lecture.source_url = None
    await db.commit()

    return LectureUploadOut(
        lecture_id=lecture_id,
        source_type="upload",
        stored_filename=stored_filename,
        size_bytes=size_bytes,
    )


@router.get("", response_model=list[LectureOut])
async def list_lectures(
    course_id: uuid.UUID | None = Query(None), db: AsyncSession = Depends(get_db)
):
    return await lecture_service.list_lectures(db, course_id)


@router.get("/{lecture_id}", response_model=LectureOut)
async def get_lecture(lecture_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    lecture = await lecture_service.get_lecture(db, lecture_id)
    if not lecture:
        raise HTTPException(status_code=404, detail="Lecture not found")
    return lecture


@router.delete("/{lecture_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_lecture(lecture_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    deleted = await lecture_service.delete_lecture(db, lecture_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Lecture not found")
