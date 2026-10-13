"""
app/services/precompute_service.py

Ingestion-time precomputation (Section 9.5): chapters, topics, difficulty
scores, exam-relevant points, a quiz, and per-lecture study notes — all
generated once, via Groq (Section 8.2), and stored so the Client App never
has to regenerate them per visitor.

Course-level notes and follow-up suggestions are explicitly NOT precomputed
here (Section 9.5) — they are Client App, on-demand, cached-on-first-use
responsibilities (Section 10.5, 7.24).
"""
import json
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai_clients.groq_client import generate_structured, generate_text
from app.core.logging import logger
from app.db.models import (
    Chapter,
    Lecture,
    LectureChunk,
    ModelUsageLog,
    Question,
    Quiz,
    StudyNote,
    StudyNoteScope,
    StudyNoteSource,
    StudyNoteStyle,
    Topic,
)

MAX_TRANSCRIPT_CHARS_FOR_PROMPT = 16000  # single-call prompt budget (Groq TPM limit on this account: 8000 tokens/req)
WINDOW_CHARS = 10000  # per-window budget when map-reduce summarizing is needed


async def run_all_precomputation(db: AsyncSession, lecture_id: uuid.UUID) -> None:
    lecture = (await db.execute(select(Lecture).where(Lecture.id == lecture_id))).scalar_one()
    chunks = (
        (
            await db.execute(
                select(LectureChunk)
                .where(LectureChunk.lecture_id == lecture_id)
                .order_by(LectureChunk.start_time)
            )
        )
        .scalars()
        .all()
    )
    full_text = _join_transcript(chunks)
    prepared_text = await _prepare_transcript_for_prompts(db, lecture, full_text)

    await _generate_topics_and_difficulty(db, lecture, prepared_text)
    await _generate_chapters(db, lecture, chunks, prepared_text)
    await _generate_quiz(db, lecture, prepared_text)
    await _generate_lecture_notes(db, lecture, prepared_text)

    logger.info(f"precomputation_complete lecture_id={lecture_id}")


def _join_transcript(chunks: list[LectureChunk]) -> str:
    return "\n".join(f"[{c.start_time:.0f}s] {c.text}" for c in chunks if c.source_type == "transcript")


async def _prepare_transcript_for_prompts(db: AsyncSession, lecture: Lecture, full_text: str) -> str:
    if len(full_text) <= MAX_TRANSCRIPT_CHARS_FOR_PROMPT:
        return full_text

    windows = _split_into_windows(full_text, WINDOW_CHARS)
    logger.info(f"map_reduce_summarizing lecture_id={lecture.id} windows={len(windows)}")

    summaries = []
    for window in windows:
        system = (
            "You are condensing one segment of a university lecture transcript for "
            "downstream summarization. Preserve every distinct concept, definition, "
            "example, and formula mentioned, and KEEP the [Ns] timestamp markers "
            "attached to the point they belong to (approximate is fine). Do not add "
            "commentary or omit content — only remove redundant phrasing and filler "
            "words. Output plain condensed text, not JSON."
        )
        condensed, meta = await generate_text(
            system_prompt=system,
            user_prompt=window,
            tier="default",
            feature="precompute.window_summarize",
            max_tokens=1500,
        )
        await _log_usage(db, "precompute.window_summarize", meta, lecture.id)
        summaries.append(condensed)

    merged = "\n\n".join(summaries)
    if len(merged) > MAX_TRANSCRIPT_CHARS_FOR_PROMPT:
        logger.warning(
            f"map_reduce_merge_still_over_budget lecture_id={lecture.id} "
            f"chars={len(merged)} — truncating as last resort"
        )
        merged = merged[:MAX_TRANSCRIPT_CHARS_FOR_PROMPT]
    return merged


def _split_into_windows(full_text: str, window_chars: int) -> list[str]:
    lines = full_text.split("\n")
    windows: list[str] = []
    current: list[str] = []
    current_len = 0
    for line in lines:
        if current_len + len(line) + 1 > window_chars and current:
            windows.append("\n".join(current))
            current, current_len = [], 0
        current.append(line)
        current_len += len(line) + 1
    if current:
        windows.append("\n".join(current))
    return windows


async def _log_usage(db: AsyncSession, feature: str, meta: dict, lecture_id: uuid.UUID) -> None:
    db.add(
        ModelUsageLog(
            application="admin",
            feature=feature,
            model_used=meta["model"],
            lecture_id=lecture_id,
            prompt_tokens=meta.get("prompt_tokens"),
            completion_tokens=meta.get("completion_tokens"),
            latency_ms=meta.get("latency_ms"),
        )
    )


# --------------------------------------------------------------------------
# Topics + difficulty/importance scoring (Section 7.14, 7.21, FR-018, FR-019)
# --------------------------------------------------------------------------
async def _generate_topics_and_difficulty(db: AsyncSession, lecture: Lecture, full_text: str) -> None:
    system = (
        "You are an academic content analyst for a university lecture platform. "
        "Identify the distinct topics covered in this lecture transcript. For each "
        "topic, estimate a difficulty_score and importance_score between 0.0 and 1.0. "
        "difficulty_score reflects how hard the topic is to understand (concept "
        "density, technical terminology, formula density, prerequisite dependency). "
        "importance_score reflects likely exam relevance — NOT a guarantee the topic "
        "will appear on any exam. The transcript lines are prefixed with their "
        "timestamp in seconds, like [125s] — use those to estimate where in the "
        "lecture (start_time/end_time, in seconds) each topic is mainly discussed; "
        "use null for either if the topic isn't tied to one segment. Respond ONLY "
        'with JSON: {"topics": [{"name": str, "description": str, "difficulty_score": '
        'float, "importance_score": float, "start_time": float|null, "end_time": float|null}]}'
    )
    parsed, meta = await generate_structured(
        system_prompt=system,
        user_prompt=full_text,
        tier="default",
        feature="precompute.topics_difficulty",
    )
    await _log_usage(db, "precompute.topics_difficulty", meta, lecture.id)

    topics_list = parsed.get("topics", [])
    if not topics_list:
        raise RuntimeError(
            "topics_difficulty returned zero topics -- treating as a failed "
            "generation (likely truncated/empty model output) so it retries "
            "instead of silently saving an empty result."
        )

    for t in topics_list:
        db.add(
            Topic(
                lecture_id=lecture.id,
                name=t.get("name", "Untitled Topic")[:255],
                description=t.get("description", ""),
                difficulty_score=float(t.get("difficulty_score", 0.5)),
                importance_score=float(t.get("importance_score", 0.5)),
                start_time=t.get("start_time"),
                end_time=t.get("end_time"),
            )
        )
    await db.commit()


# --------------------------------------------------------------------------
# Chapters (Section 7.2)
# --------------------------------------------------------------------------
async def _generate_chapters(
    db: AsyncSession, lecture: Lecture, chunks: list[LectureChunk], full_text: str
) -> None:
    system = (
        "You are segmenting a university lecture transcript into navigable chapters. "
        "The transcript lines are prefixed with their timestamp in seconds, like [125s]. "
        "Produce 4-10 chapters covering the ENTIRE lecture from 0 to the end — do not "
        "skip any part of the transcript. Respond ONLY with JSON: "
        '{"chapters": [{"title": str, "start_time": float, "end_time": float}]}'
    )
    parsed, meta = await generate_structured(
        system_prompt=system,
        user_prompt=full_text,
        tier="default",
        feature="precompute.chapters",
        max_tokens=3000,
    )
    await _log_usage(db, "precompute.chapters", meta, lecture.id)

    chapters_list = parsed.get("chapters", [])
    if not chapters_list:
        raise RuntimeError(
            "chapters generation returned zero chapters -- treating as a failed "
            "generation so it retries instead of silently saving an empty result."
        )

    for ch in chapters_list:
        db.add(
            Chapter(
                lecture_id=lecture.id,
                title=ch.get("title", "Untitled Chapter")[:255],
                start_time=float(ch.get("start_time", 0)),
                end_time=float(ch.get("end_time", 0)),
            )
        )
    await db.commit()


# --------------------------------------------------------------------------
# Quiz (Section 7.19)
# --------------------------------------------------------------------------
async def _generate_quiz(db: AsyncSession, lecture: Lecture, full_text: str) -> None:
    system = (
        "Generate a 6-question multiple-choice quiz grounded strictly in this lecture "
        "transcript. Each question needs 4 options (a-d), the correct answer key, a "
        "short explanation, and the approximate source_timestamp in seconds where the "
        "concept was discussed. Do not invent facts not present in the transcript. "
        'Respond ONLY with JSON: {"questions": [{"text": str, "options": '
        '{"a": str, "b": str, "c": str, "d": str}, "correct_answer": str, '
        '"explanation": str, "source_timestamp": float, "difficulty": '
        '"easy"|"medium"|"hard"}]}'
    )
    parsed, meta = await generate_structured(
        system_prompt=system,
        user_prompt=full_text,
        tier="default",
        feature="precompute.quiz",
        max_tokens=3000,
    )
    await _log_usage(db, "precompute.quiz", meta, lecture.id)

    questions_list = parsed.get("questions", [])
    if not questions_list:
        raise RuntimeError(
            "quiz generation returned zero questions -- treating as a failed "
            "generation so it retries instead of silently saving an empty result."
        )

    quiz = Quiz(lecture_id=lecture.id)
    db.add(quiz)
    await db.flush()  # need quiz.id for the FK below

    for q in questions_list:
        db.add(
            Question(
                quiz_id=quiz.id,
                text=q.get("text", ""),
                options=q.get("options", {}),
                correct_answer=q.get("correct_answer", "a"),
                explanation=q.get("explanation", ""),
                source_timestamp=q.get("source_timestamp"),
                difficulty=q.get("difficulty", "medium"),
            )
        )
    await db.commit()


# --------------------------------------------------------------------------
# Per-lecture Auto Study Notes (Section 7.23)
# --------------------------------------------------------------------------
async def _generate_lecture_notes(db: AsyncSession, lecture: Lecture, full_text: str) -> None:
    part1_system = (
        "Write detailed study notes for this single lecture, for a student preparing "
        "for exams. Organize into these sections, in this order, using Markdown headings:\n\n"
        "1. **Overview** - 3-5 sentences giving a clear, concrete sense of what this "
        "lecture is about and why it matters, so a student reading only this section "
        "understands the lecture's purpose and scope before reading further.\n"
        "2. **Main Concepts** - cover every distinct concept taught, with enough "
        "explanation (not just a one-line label) that a student who missed the lecture "
        "could learn the concept from this alone.\n"
        "3. **Definitions** - every term defined or used precisely in the lecture.\n"
        "4. **Examples** - every worked example, with the key numbers/steps preserved.\n"
        "5. **Formulas** - every formula or expression given.\n"
        "6. **Important Points** - the points the lecturer emphasized or that are easy "
        "to get wrong.\n"
        "7. **Exam Revision** - a checklist of what to practice/review before an exam.\n\n"
        "LANGUAGE: Write every section in simple, plain English - short sentences, "
        "everyday words. Many students reading this are not from English-medium "
        "backgrounds and will give up if the writing itself feels academic or hard. "
        "Do not simplify away a technical term that the lecture itself uses (the "
        "student needs that exact term for exams) - instead, **bold the technical "
        "term** and immediately give its plain-English meaning in parentheses right "
        "after it, e.g. **mantissa** (the digits that show the exact value of a number). "
        "Do this the first time each term appears.\n"
        "TABLES: If a table would have more than 10-12 rows, split it into multiple "
        "smaller tables (e.g. by sub-topic) rather than one long table - a long table "
        "feels tiring and students lose focus; several short ones feel manageable.\n\n"
        "Be thorough and concrete - prefer specific detail from the transcript over "
        "generic summary sentences. Base every statement strictly on the transcript "
        "provided; do not add outside facts. Do not write a final summary section - "
        "that will be requested separately."
    )
    part1, meta1 = await generate_text(
        system_prompt=part1_system,
        user_prompt=full_text,
        tier="default",
        feature="precompute.lecture_notes",
        max_tokens=3000,
    )
    await _log_usage(db, "precompute.lecture_notes", meta1, lecture.id)

    part2_system = (
        "Based on this same lecture transcript, write ONE section titled exactly "
        "'## Lecture at a Glance (Explained Simply)'. This is the crux/summary of the "
        "whole lecture - re-teach it from scratch in plain, easy English, the way "
        "you'd explain it to a curious student with no background: short sentences, "
        "everyday words, one idea at a time, with at least one simple example per "
        "major idea. By the end, someone who skipped the lecture should understand "
        "what was taught and why it matters. Base every statement strictly on the "
        "transcript provided; do not add outside facts. Output only this section, "
        "complete and self-contained - nothing before or after it."
    )
    part2, meta2 = await generate_text(
        system_prompt=part2_system,
        user_prompt=full_text,
        tier="default",
        feature="precompute.lecture_notes_crux",
        max_tokens=2500,
    )
    await _log_usage(db, "precompute.lecture_notes_crux", meta2, lecture.id)

    def _looks_broken(text: str) -> bool:
        stripped = text.strip()
        return (
            len(stripped) < 150
            or "i don't have" in stripped.lower()
            or "i'm sorry" in stripped.lower()
            or "please provide" in stripped.lower()
        )

    if _looks_broken(part1) or _looks_broken(part2):
        raise RuntimeError(
            "lecture_notes generation returned an empty/refusal-like or "
            "truncated response instead of real notes -- treating as a failed "
            "generation so it retries instead of silently saving unusable content."
        )

    content = part1.strip() + "\n\n" + part2.strip()

    note = StudyNote(
        scope_type=StudyNoteScope.LECTURE,
        lecture_id=lecture.id,
        style=StudyNoteStyle.FULL,
        content=content,
    )
    db.add(note)
    await db.flush()

    db.add(
        StudyNoteSource(
            study_note_id=note.id,
            lecture_id=lecture.id,
            start_time=0.0,
            end_time=float(lecture.duration_seconds or 0),
        )
    )

