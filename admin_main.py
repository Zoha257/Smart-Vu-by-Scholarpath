"""
admin_main.py — Admin App application boundary (Section 5.7.2, 15.1)

CRITICAL: this application SHALL NOT be bound to a public network interface
(Section 18.5, 24.3). Run it with --host 127.0.0.1 (the default below, from
ADMIN_APP_HOST) and reach it only via SSH tunnel / VPN / loopback. Binding
this to 0.0.0.0 on a machine with a public IP defeats the entire Separation
Principle (Section 1.4) this application exists to satisfy.

This process registers ONLY admin routers. It does not import, mount, or
expose anything resembling a Client App route (Section 5.7.3) — that
separation is enforced simply by this file never importing that code, since
the Client App is a different repository/deployment entirely.
"""
import uvicorn
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from app.core.config import get_settings
from app.core.logging import logger
from app.routers import courses_admin, dashboard, ingestion_admin, lectures_admin
from app.workers.worker_queue import start_worker, stop_worker

settings = get_settings()

app = FastAPI(
    title="VU Lecture Intelligence — Admin App",
    description=(
        "Operator-only application (Section 5.7.2). Never deployed to a "
        "public address. Handles course/lecture management and the full "
        "ingestion pipeline (Section 5.6, 9)."
    ),
    version="5.0.0",
    docs_url="/api/docs",   # still fine to expose — this whole app is private
    redoc_url="/api/redoc",
)

# Session cookie for the dashboard's login (Section 12.8). Uses the admin key
# itself as the signing secret — swap for a dedicated SESSION_SECRET env var
# if you want cookie compromise and admin-key compromise to be independent.
app.add_middleware(SessionMiddleware, secret_key=settings.ADMIN_API_KEY)

app.mount("/static", StaticFiles(directory="app/static"), name="static")

# --- Admin-only routers (Section 5.7.2) ---
app.include_router(courses_admin.router)
app.include_router(lectures_admin.router)
app.include_router(ingestion_admin.router)
app.include_router(dashboard.router)  # server-rendered UI, Section 12.8


@app.on_event("startup")
async def on_startup() -> None:
    if settings.ADMIN_APP_HOST not in ("127.0.0.1", "localhost", "::1"):
        logger.warning(
            "ADMIN_APP_HOST is not a loopback address — verify this is a private "
            "network interface, not a public one (Section 18.5)."
        )
    start_worker()
    await _recover_stuck_lectures()
    logger.info(f"admin_app_started host={settings.ADMIN_APP_HOST} port={settings.ADMIN_APP_PORT}")


async def _recover_stuck_lectures() -> None:
    """Queue recovery: re-enqueue any lecture left in a non-terminal status
    from a previous crashed/killed run, so nothing stays PROCESSING forever."""
    from sqlalchemy import select

    from app.db.models import Lecture, ProcessingStatus
    from app.db.session import AsyncSessionLocal
    from app.workers.worker_queue import enqueue_ingestion_job

    terminal = (ProcessingStatus.PENDING, ProcessingStatus.COMPLETED, ProcessingStatus.FAILED)
    async with AsyncSessionLocal() as db:
        stuck = (
            await db.execute(select(Lecture).where(Lecture.processing_status.not_in(terminal)))
        ).scalars().all()
        for lecture in stuck:
            logger.warning(
                f"queue_recovery lecture_id={lecture.id} was stuck at "
                f"status={lecture.processing_status.value}, re-enqueuing"
            )
            await enqueue_ingestion_job(lecture.id)
    if stuck:
        logger.info(f"queue_recovery_complete recovered={len(stuck)}")


@app.on_event("shutdown")
async def on_shutdown() -> None:
    stop_worker()
    logger.info("admin_app_stopped")


@app.get("/healthz", tags=["internal"])
async def health_check():
    return {"status": "ok", "app": "admin"}


if __name__ == "__main__":
    uvicorn.run(
        "admin_main:app",
        host=settings.ADMIN_APP_HOST,  # MUST stay private — Section 18.5
        port=settings.ADMIN_APP_PORT,
        reload=False,
    )
