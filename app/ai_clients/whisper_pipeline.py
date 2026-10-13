"""
app/ai_clients/whisper_pipeline.py — Groq-hosted Whisper transcription.
"""
import os
from dataclasses import dataclass
from pathlib import Path

from groq import AsyncGroq

from app.core.config import get_settings
from app.core.logging import logger

settings = get_settings()
_client = AsyncGroq(api_key=settings.GROQ_API_KEY)

_MODEL = "whisper-large-v3-turbo"
_MAX_BYTES = 24 * 1024 * 1024
_CHUNK_SECONDS = 20 * 60
_OVERLAP_SECONDS = 5


@dataclass
class TranscriptChunk:
    chunk_index: int
    start_time: float
    end_time: float
    text: str


async def transcribe_audio(audio_path: str, language: str | None = None) -> list[TranscriptChunk]:
    size = os.path.getsize(audio_path)
    if size <= _MAX_BYTES:
        segments = await _transcribe_one(audio_path, language)
        chunks = _to_chunks(segments)
    else:
        chunks = await _transcribe_in_chunks(audio_path, language)
    logger.info(f"transcription_complete audio={audio_path} chunks={len(chunks)}")
    return chunks


async def _transcribe_one(path: str, language: str | None) -> list:
    with open(path, "rb") as f:
        response = await _client.audio.transcriptions.create(
            file=(os.path.basename(path), f.read()),
            model=_MODEL,
            language=language,
            response_format="verbose_json",
            timestamp_granularities=["segment"],
        )
    return getattr(response, "segments", None) or []


def _to_chunks(segments: list, offset: float = 0.0, start_index: int = 0) -> list[TranscriptChunk]:
    chunks = []
    for idx, seg in enumerate(segments):
        start = seg["start"] if isinstance(seg, dict) else seg.start
        end = seg["end"] if isinstance(seg, dict) else seg.end
        text = seg["text"] if isinstance(seg, dict) else seg.text
        chunks.append(TranscriptChunk(start_index + idx, start + offset, end + offset, text.strip()))
    return chunks


async def _transcribe_in_chunks(audio_path: str, language: str | None) -> list[TranscriptChunk]:
    import ffmpeg
    probe = ffmpeg.probe(audio_path)
    duration = float(probe["format"]["duration"])
    work_dir = Path(audio_path).parent / "audio_chunks"
    work_dir.mkdir(exist_ok=True)
    all_chunks: list[TranscriptChunk] = []
    start = 0.0
    idx = 0
    while start < duration:
        end = min(start + _CHUNK_SECONDS, duration)
        chunk_path = work_dir / f"chunk_{idx}.mp3"
        (ffmpeg.input(audio_path, ss=start, t=(end - start))
            .output(str(chunk_path), acodec="libmp3lame", audio_bitrate="32k", ac=1, ar="16000")
            .overwrite_output().run(quiet=True))
        segments = await _transcribe_one(str(chunk_path), language)
        all_chunks.extend(_to_chunks(segments, offset=start, start_index=len(all_chunks)))
        idx += 1
        start += _CHUNK_SECONDS - _OVERLAP_SECONDS
    return all_chunks
