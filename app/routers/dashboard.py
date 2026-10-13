"""
app/routers/dashboard.py — Section 12.8 (Admin App Interface)

A deliberately minimal, server-rendered dashboard (Jinja2, no build step) for
course/lecture management, ingestion triggering, and status monitoring. This
interface is NOT reachable from, linked to, or bundled with the Client App's
static assets in any way (Section 5.7.3) — it lives entirely in this
separate FastAPI application, and this application is never deployed to a
public address (Section 18.5, 24.3).

Auth model: a session cookie holding the admin key, set once via the login
form, checked on every dashboard page. This is DIFFERENT from the JSON API's
X-Admin-Key header check (app/core/security.py) — same secret, two transport
mechanisms, because a browser can't easily send a custom header on a normal
page navigation.
"""
import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.session import get_db
from app.services import course_service, ingestion_service, lecture_service

router = APIRouter(tags=["dashboard"])
templates = Jinja2Templates(directory="app/templates")
settings = get_settings()


def _require_session(request: Request) -> None:
    if request.session.get("admin_key") != settings.ADMIN_API_KEY:
        raise HTTPException(status_code=status.HTTP_303_SEE_OTHER, headers={"Location": "/login"})


@router.get("/login", response_class=HTMLResponse)
async def login_form(request: Request):
    return templates.TemplateResponse("login.html", {"request": request, "error": None})


@router.post("/login")
async def login_submit(request: Request, admin_key: str = Form(...)):
    if admin_key != settings.ADMIN_API_KEY:
        return templates.TemplateResponse(
            "login.html", {"request": request, "error": "Invalid admin key."}, status_code=401
        )
    request.session["admin_key"] = admin_key
    return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/", response_class=HTMLResponse)
async def dashboard_home(request: Request, db: AsyncSession = Depends(get_db)):
    if request.session.get("admin_key") != settings.ADMIN_API_KEY:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)

    courses = await course_service.list_courses(db)
    today_count = await lecture_service.count_lectures_ingested_today(db)
    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "courses": courses,
            "today_count": today_count,
            "daily_cap": settings.MAX_LECTURES_INGESTED_PER_DAY,
        },
    )


@router.post("/courses/create")
async def create_course_form(
    request: Request,
    course_code: str = Form(...),
    title: str = Form(...),
    description: str = Form(""),
    db: AsyncSession = Depends(get_db),
):
    if request.session.get("admin_key") != settings.ADMIN_API_KEY:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    await course_service.create_course(db, course_code, title, description)
    return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/courses/{course_id}", response_class=HTMLResponse)
async def course_detail(course_id: uuid.UUID, request: Request, db: AsyncSession = Depends(get_db)):
    if request.session.get("admin_key") != settings.ADMIN_API_KEY:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)

    course = await course_service.get_course(db, course_id)
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")
    lectures = await lecture_service.list_lectures(db, course_id)
    return templates.TemplateResponse(
        "course_detail.html", {"request": request, "course": course, "lectures": lectures}
    )


@router.get("/lectures/{lecture_id}/view", response_class=HTMLResponse)
async def lecture_content_view(
    lecture_id: uuid.UUID, request: Request, db: AsyncSession = Depends(get_db)
):
    if request.session.get("admin_key") != settings.ADMIN_API_KEY:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)

    from sqlalchemy import select

    from app.db.models import Chapter, Lecture, LectureChunk, Question, Quiz, StudyNote, Topic, VisualAsset

    lecture = (await db.execute(select(Lecture).where(Lecture.id == lecture_id))).scalar_one_or_none()
    if not lecture:
        raise HTTPException(status_code=404, detail="Lecture not found")

    chunks = (
        await db.execute(
            select(LectureChunk)
            .where(LectureChunk.lecture_id == lecture_id)
            .order_by(LectureChunk.start_time)
        )
    ).scalars().all()
    chapters = (
        await db.execute(
            select(Chapter).where(Chapter.lecture_id == lecture_id).order_by(Chapter.start_time)
        )
    ).scalars().all()
    topics = (
        await db.execute(select(Topic).where(Topic.lecture_id == lecture_id))
    ).scalars().all()
    quiz = (
        await db.execute(select(Quiz).where(Quiz.lecture_id == lecture_id))
    ).scalars().first()
    questions = []
    if quiz:
        questions = (
            await db.execute(select(Question).where(Question.quiz_id == quiz.id))
        ).scalars().all()
    notes = (
        await db.execute(select(StudyNote).where(StudyNote.lecture_id == lecture_id))
    ).scalars().all()
    import markdown as _md
    for _n in notes:
        _n.rendered_html = _md.markdown(
            _n.content, extensions=['tables', 'fenced_code', 'sane_lists']
        )
    slides = (
        await db.execute(
            select(VisualAsset).where(VisualAsset.lecture_id == lecture_id).order_by(VisualAsset.timestamp)
        )
    ).scalars().all()

    return templates.TemplateResponse(
        "lecture_view.html",
        {
            "request": request,
            "lecture": lecture,
            "chunks": chunks,
            "chapters": chapters,
            "topics": topics,
            "questions": questions,
            "notes": notes,
            "slides": slides,
        },
    )


@router.post("/courses/{course_id}/lectures/create")
async def create_lecture_form(
    course_id: uuid.UUID,
    request: Request,
    title: str = Form(...),
    lecture_number: int = Form(...),
    source_mode: str = Form(...),  # "url" | "upload" — set by the template's toggle
    source_url: str = Form(""),
    video_file: UploadFile | None = File(None),
    db: AsyncSession = Depends(get_db),
):
    """
    Section 21.3: two ways to provide the source video.
      source_mode="url"    -> source_url is required (VU OCW preferred, YouTube fallback)
      source_mode="upload" -> video_file is required, streamed to disk and
                               consumed by the pipeline instead of a fetch
    """
    if request.session.get("admin_key") != settings.ADMIN_API_KEY:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)

    if source_mode == "upload":
        if not video_file or not video_file.filename:
            raise HTTPException(status_code=400, detail="Choose a video file to upload.")
        lecture = await lecture_service.create_lecture(
            db, course_id, title, lecture_number, source_url=None
        )
        try:
            await lecture_service.save_uploaded_video(lecture.id, video_file)
        except ValueError as exc:
            raise HTTPException(status_code=413, detail=str(exc))
    else:
        if not source_url.strip():
            raise HTTPException(status_code=400, detail="Paste a VU OCW or YouTube URL.")
        await lecture_service.create_lecture(
            db, course_id, title, lecture_number, source_url=source_url.strip()
        )

    return RedirectResponse(url=f"/courses/{course_id}", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/lectures/{lecture_id}/trigger")
async def trigger_ingestion_form(
    lecture_id: uuid.UUID, request: Request, db: AsyncSession = Depends(get_db)
):
    if request.session.get("admin_key") != settings.ADMIN_API_KEY:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)

    lecture = await lecture_service.get_lecture(db, lecture_id)
    try:
        await ingestion_service.trigger_ingestion(db, lecture_id)
    except ingestion_service.DailyIngestionCapExceeded:
        pass  # surfaced visually by today_count vs daily_cap on the dashboard
    return RedirectResponse(
        url=f"/courses/{lecture.course_id}", status_code=status.HTTP_303_SEE_OTHER
    )


@router.post("/lectures/{lecture_id}/delete")
async def delete_lecture_form(
    lecture_id: uuid.UUID, request: Request, db: AsyncSession = Depends(get_db)
):
    if request.session.get("admin_key") != settings.ADMIN_API_KEY:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)

    lecture = await lecture_service.get_lecture(db, lecture_id)
    if not lecture:
        raise HTTPException(status_code=404, detail="Lecture not found")
    course_id = lecture.course_id
    await db.delete(lecture)
    await db.commit()
    return RedirectResponse(url=f"/courses/{course_id}", status_code=status.HTTP_303_SEE_OTHER)
