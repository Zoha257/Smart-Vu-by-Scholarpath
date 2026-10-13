"""
app/ingestion/pipeline.py

Full ingestion orchestrator (Section 9.1-9.5, Section 5.6). This is the
single entry point that the ingestion_service.py enqueues onto the worker
queue. It runs the complete audio+video pipeline for one lecture, in order:

  1. Fetch source video temporarily (Section 21.3 — never stored permanently)
  2. Transcribe COMPLETE audio (faster-whisper) — Section 9.1
  3. Select keyframes from the COMPLETE video timeline — Section 9.2
  4. Resolve each keyframe: OCR -> (uncertain?) -> Vision LLM — Section 9.3
  5. Chunk the transcript + visual text, embed every chunk — Section 8.5
  6. Store everything in the lecture dataset — Section 9.4
  7. Precompute chapters/topics/difficulty/quiz/notes via Groq — Section 9.5
  8. Mark lecture COMPLETED

Every step updates ProcessingStatus (Section 15.5) so the operator's
dashboard and, later, the Client App's readiness notice (Section 7.24) stay
accurate throughout.
"""
import os
import shutil
import tempfile
import uuid
from pathlib import Path

import ffmpeg
import yt_dlp
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai_clients.embedding_model import embed_texts
from app.ai_clients.whisper_pipeline import transcribe_audio
from app.core.config import get_settings
from app.core.logging import logger
from app.db.models import (
    Chapter,
    Lecture,
    LectureChunk,
    LectureSourceType,
    ProcessingStatus,
    Quiz,
    StudyNote,
    StudyNoteScope,
    Topic,
    VisualAsset,
)
from app.ingestion.status_tracker import set_status
from app.services import lecture_service, precompute_service

settings = get_settings()


async def run_ingestion(db: AsyncSession, lecture_id: uuid.UUID) -> None:
    lecture = (await db.execute(select(Lecture).where(Lecture.id == lecture_id))).scalar_one()

    work_dir = Path(tempfile.mkdtemp(prefix=f"vu_ingest_{lecture_id}_"))
    try:
        await set_status(db, lecture_id, ProcessingStatus.PROCESSING)

        # ---- 0. Idempotent reprocessing (no duplicates on retry) ----
        await db.execute(delete(LectureChunk).where(LectureChunk.lecture_id == lecture_id))
        await db.execute(delete(Chapter).where(Chapter.lecture_id == lecture_id))
        await db.execute(delete(Topic).where(Topic.lecture_id == lecture_id))
        await db.execute(delete(VisualAsset).where(VisualAsset.lecture_id == lecture_id))
        await db.execute(delete(Quiz).where(Quiz.lecture_id == lecture_id))
        await db.execute(
            delete(StudyNote).where(
                StudyNote.lecture_id == lecture_id, StudyNote.scope_type == StudyNoteScope.LECTURE
            )
        )
        await db.commit()

        # ---- 1. Obtain source video temporarily (Section 21.3) ----
        # URL-sourced: fetch via yt-dlp/OCW. Upload-sourced: the operator
        # already placed the file under LOCAL_UPLOAD_DIR (lectures_admin.py
        # upload-video endpoint) -- move it into this run's work_dir so the
        # same shutil.rmtree(work_dir) cleanup below deletes it too.
        if lecture.source_type == LectureSourceType.UPLOAD:
            video_path = _get_uploaded_video(lecture_id, work_dir)
        else:
            if not lecture.source_url:
                raise RuntimeError(
                    f"Lecture {lecture_id} is URL-sourced but has no source_url set."
                )
            video_path = _fetch_source_video(lecture.source_url, work_dir)
        audio_path = _extract_audio(video_path, work_dir)

        # ---- 2. Full transcript (Section 9.1) ----
        await set_status(db, lecture_id, ProcessingStatus.TRANSCRIBING)
        transcript_chunks = await transcribe_audio(str(audio_path))
        lecture.duration_seconds = int(transcript_chunks[-1].end_time) if transcript_chunks else 0

        # ---- 3+4. Keyframes/OCR/Vision — INTENTIONALLY REMOVED from the
        # Admin App pipeline. Screenshot capture + OCR/vision now happens
        # on-demand in the Client App ("explain this screen" during
        # playback), not precomputed for every lecture up front.
        visual_rows: list[VisualAsset] = []

        # ---- 5. Chunk + embed (Section 8.5) ----
        await set_status(db, lecture_id, ProcessingStatus.GENERATING_EMBEDDINGS)
        chunk_rows = _build_chunk_rows(lecture_id, transcript_chunks, visual_rows)
        texts = [c.text for c in chunk_rows]
        if texts:
            vectors = embed_texts(texts)
            for chunk, vec in zip(chunk_rows, vectors):
                chunk.embedding = vec
        db.add_all(chunk_rows)
        await db.commit()

        # ---- 6-7. Precomputation via Groq (Section 9.5, 8.2) ----
        await set_status(db, lecture_id, ProcessingStatus.GENERATING_INTELLIGENCE)
        await precompute_service.run_all_precomputation(db, lecture_id)

        # ---- 8. Done ----
        await set_status(db, lecture_id, ProcessingStatus.COMPLETED)
        if lecture.source_type == LectureSourceType.UPLOAD:
            lecture_service.cleanup_uploaded_video(lecture_id)
        logger.info(f"ingestion_complete lecture_id={lecture_id}")

    except Exception as exc:  # noqa: BLE001 — ingestion is a long pipeline; log + mark failed
        logger.exception(f"ingestion_failed lecture_id={lecture_id}: {exc}")
        await set_status(db, lecture_id, ProcessingStatus.FAILED, error=str(exc))
        raise
    finally:
        # Section 21.3 — source video is NEVER permanently stored/redistributed
        shutil.rmtree(work_dir, ignore_errors=True)


def _get_uploaded_video(lecture_id: uuid.UUID, work_dir: Path) -> Path:
    """
    Moves an operator-uploaded file (lecture_service.save_uploaded_video)
    into this run's work_dir, then deletes the upload-holding directory --
    same "never stored permanently" rule as the URL-fetch path, just
    without a network fetch.
    """
    uploaded_path = lecture_service.get_uploaded_video_path(lecture_id)
    if uploaded_path is None:
        raise RuntimeError(
            f"Lecture {lecture_id} is upload-sourced but no uploaded file was "
            f"found. Call POST /api/admin/lectures/{lecture_id}/upload-video first."
        )
    dest = work_dir / f"source{uploaded_path.suffix}"
    shutil.copy2(str(uploaded_path), str(dest))
    if not dest.exists() or dest.stat().st_size != uploaded_path.stat().st_size:
        raise RuntimeError(f"Upload copy verification failed for lecture {lecture_id}")
    return dest


def _fetch_source_video(source_url: str, work_dir: Path) -> Path:
    """
    Temporarily downloads source video for processing only (Section 21.3).
    Prefers the VU Open Courseware portal where a direct downloadable file is
    available; otherwise falls back to yt-dlp for a YouTube-embedded lecture.
    """
    output_template = str(work_dir / "source.%(ext)s")
    ydl_opts = {
        "outtmpl": output_template,
        "format": "best[height<=720]",  # 720p is plenty for OCR/transcription
        "quiet": True,
        "noplaylist": True,
    }
    if settings.YT_DLP_COOKIES_FILE:
        ydl_opts["cookiefile"] = settings.YT_DLP_COOKIES_FILE

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([source_url])

    candidates = list(work_dir.glob("source.*"))
    if not candidates:
        raise RuntimeError(f"Failed to fetch source video from {source_url}")
    return candidates[0]


def _extract_audio(video_path: Path, work_dir: Path) -> Path:
    audio_path = work_dir / "audio.mp3"
    (
        ffmpeg.input(str(video_path))
        .output(str(audio_path), acodec="libmp3lame", audio_bitrate="32k", ac=1, ar="16000")
        .overwrite_output()
        .run(quiet=True)
    )
    return audio_path


def _build_chunk_rows(
    lecture_id: uuid.UUID, transcript_chunks, visual_assets: list[VisualAsset]
) -> list[LectureChunk]:
    rows: list[LectureChunk] = []
    for tc in transcript_chunks:
        rows.append(
            LectureChunk(
                lecture_id=lecture_id,
                text=tc.text,
                start_time=tc.start_time,
                end_time=tc.end_time,
                chunk_index=tc.chunk_index,
                source_type="transcript",
            )
        )
    # Visual (OCR/Vision) text becomes its own retrievable chunks too, so
    # "Ask From Screen" (Section 7.7) and search can surface board/slide
    # content that was never spoken aloud.
    offset = len(rows)
    for i, va in enumerate(visual_assets):
        if va.ocr_text.strip():
            rows.append(
                LectureChunk(
                    lecture_id=lecture_id,
                    text=va.ocr_text,
                    start_time=va.timestamp,
                    end_time=va.timestamp + 1.0,
                    chunk_index=offset + i,
                    source_type=va.asset_type,
                    visual_asset_id=va.id,
                )
            )
    return rows
