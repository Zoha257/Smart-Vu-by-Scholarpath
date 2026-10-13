"""
app/workers/transcription_worker.py — Section 15.3

Thin, independently-importable wrapper around the transcription stage. In
the current single-VM deployment, app/ingestion/pipeline.py calls
whisper_pipeline.transcribe_audio() directly for simplicity (see
worker_queue.py's note). This module exposes the same stage as a standalone
callable so it can be run as its own process/consumer later without touching
business logic — just point a queue consumer at `process_job`.
"""
from app.ai_clients.whisper_pipeline import TranscriptChunk, transcribe_audio
from app.core.logging import logger


def process_job(audio_path: str, language: str | None = None) -> list[TranscriptChunk]:
    logger.info(f"transcription_worker_job_start audio={audio_path}")
    result = transcribe_audio(audio_path, language=language)
    logger.info(f"transcription_worker_job_done audio={audio_path} chunks={len(result)}")
    return result
