"""
app/routers/ingestion_admin.py — Section 4.2, 5.7.2, 15.5

Ingestion trigger/monitor routes. Admin-key protected, private-network only.
"""
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import require_admin_key
from app.db.session import get_db
from app.schemas import IngestionStatusOut, IngestionTriggerRequest
from app.services import ingestion_service, lecture_service

router = APIRouter(
    prefix="/api/admin/ingestion",
    tags=["admin:ingestion"],
    dependencies=[Depends(require_admin_key)],
)


@router.post("/{lecture_id}/trigger", status_code=status.HTTP_202_ACCEPTED)
async def trigger_ingestion(
    lecture_id: uuid.UUID,
    payload: IngestionTriggerRequest = IngestionTriggerRequest(),
    db: AsyncSession = Depends(get_db),
):
    try:
        await ingestion_service.trigger_ingestion(db, lecture_id, force=payload.force)
    except ingestion_service.DailyIngestionCapExceeded as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"detail": "Ingestion enqueued", "lecture_id": str(lecture_id)}


@router.post("/{lecture_id}/reprocess", status_code=status.HTTP_202_ACCEPTED)
async def reprocess_lecture(lecture_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """Section 25.9 — reprocessing marks the lecture REPROCESSED so the Client
    App's cache layer knows to invalidate anything scoped to it."""
    await ingestion_service.trigger_reprocessing(db, lecture_id)
    return {"detail": "Reprocessing enqueued", "lecture_id": str(lecture_id)}


@router.get("/{lecture_id}/status", response_model=IngestionStatusOut)
async def get_ingestion_status(lecture_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    lecture = await lecture_service.get_lecture(db, lecture_id)
    if not lecture:
        raise HTTPException(status_code=404, detail="Lecture not found")
    return IngestionStatusOut(
        lecture_id=lecture.id,
        processing_status=lecture.processing_status.value,
        processing_error=lecture.processing_error,
    )
