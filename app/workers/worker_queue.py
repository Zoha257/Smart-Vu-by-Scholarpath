"""
app/workers/worker_queue.py — Section 15.3 (Background Workers)

Implementation note: the SRS lists six separate worker files (transcription,
OCR, vision, embedding, LLM, enhancement) plus this queue. On a single Oracle
Always Free VM, running six separate OS processes is unnecessary overhead —
so this queue dispatches each job to app/ingestion/pipeline.py, which calls
the SAME underlying functions those six worker files expose (see
transcription_worker.py etc. — each is a thin, independently importable
wrapper around one pipeline stage). If ingestion volume ever outgrows one VM,
swap this asyncio.Queue for Redis + RQ/Celery and run each *_worker.py as
its own process without changing any business logic — the stage functions
are already isolated for exactly that split.

Retry handling (Section 15.6): failed jobs are retried up to MAX_ATTEMPTS
with backoff, and IngestionJob rows record attempts/last_error so the
operator can see what failed and why.
"""
import asyncio
import uuid

from sqlalchemy import select

from app.core.logging import logger
from app.db.models import IngestionJob
from app.db.session import AsyncSessionLocal

MAX_ATTEMPTS = 3

_queue: asyncio.Queue[uuid.UUID] = asyncio.Queue()
_worker_task: asyncio.Task | None = None


async def enqueue_ingestion_job(lecture_id: uuid.UUID) -> None:
    async with AsyncSessionLocal() as db:
        db.add(IngestionJob(lecture_id=lecture_id, stage="full_pipeline", status="queued"))
        await db.commit()
    await _queue.put(lecture_id)


async def _worker_loop() -> None:
    logger.info("worker_queue_started")
    while True:
        lecture_id = await _queue.get()
        try:
            await _process_one(lecture_id)
        except Exception as exc:
            logger.error(f"worker_loop_unhandled_error lecture_id={lecture_id} error={exc}")
        finally:
            _queue.task_done()


async def _process_one(lecture_id: uuid.UUID) -> None:
    from app.ingestion.pipeline import run_ingestion  # local import avoids circular import

    async with AsyncSessionLocal() as db:
        job = (
            await db.execute(
                select(IngestionJob)
                .where(IngestionJob.lecture_id == lecture_id, IngestionJob.status == "queued")
                .order_by(IngestionJob.created_at.desc())
            )
        ).scalars().first()

        attempts = job.attempts if job else 0
        for attempt in range(attempts, MAX_ATTEMPTS):
            try:
                if job:
                    job.status = "running"
                    job.attempts = attempt + 1
                    await db.commit()

                await run_ingestion(db, lecture_id)

                if job:
                    job.status = "done"
                    await db.commit()
                return

            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    f"ingestion_attempt_failed lecture_id={lecture_id} "
                    f"attempt={attempt + 1}/{MAX_ATTEMPTS} error={exc}"
                )
                if job:
                    job.status = "failed" if attempt + 1 >= MAX_ATTEMPTS else "queued"
                    job.last_error = str(exc)
                    await db.commit()
                await asyncio.sleep(min(2 ** attempt, 30))  # exponential backoff

        logger.error(f"ingestion_exhausted_retries lecture_id={lecture_id}")


def start_worker() -> None:
    """Called once from admin_main.py's startup event."""
    global _worker_task
    if _worker_task is None:
        loop = asyncio.get_event_loop()
        _worker_task = loop.create_task(_worker_loop())


def stop_worker() -> None:
    global _worker_task
    if _worker_task is not None:
        _worker_task.cancel()
        _worker_task = None
