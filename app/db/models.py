"""
app/db/models.py

SQLAlchemy models mirroring SRS Section 13 (Data Requirements).

Ownership (Section 13.13):
  - Admin App has FULL read/write on every table in this file.
  - The Client App has READ access to all of them, and its own separate
    write access to CachedAnswer / FollowUpSuggestion / course-scope
    StudyNote rows (those three are defined in the Client App's codebase,
    NOT here — the Admin App does not need to write to them).

No User, UserProgress, QuizAttempt, or Flashcard table exists anywhere
(Section 13.1, Section 25.10) — this is intentional, not an omission.
"""
import enum
import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from app.core.config import get_settings

settings = get_settings()


class Base(DeclarativeBase):
    pass


def _uuid_col():
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


# --------------------------------------------------------------------------
# Processing status (Section 15.5)
# --------------------------------------------------------------------------
class ProcessingStatus(str, enum.Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    TRANSCRIBING = "transcribing"
    EXTRACTING_VISUALS = "extracting_visuals"
    GENERATING_EMBEDDINGS = "generating_embeddings"
    GENERATING_INTELLIGENCE = "generating_intelligence"
    COMPLETED = "completed"
    FAILED = "failed"
    REPROCESSED = "reprocessed"  # triggers cache invalidation, Section 25.9


# --------------------------------------------------------------------------
# Section 13.2 — Course
# --------------------------------------------------------------------------
class Course(Base):
    __tablename__ = "courses"

    id: Mapped[uuid.UUID] = _uuid_col()
    course_code: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    lectures: Mapped[list["Lecture"]] = relationship(
        back_populates="course", cascade="all, delete-orphan"
    )


# --------------------------------------------------------------------------
# Section 13.3 — Lecture
# --------------------------------------------------------------------------
class LectureSourceType(str, enum.Enum):
    """
    How this lecture's source video is provided. Added alongside local file
    upload support: a URL (VU OCW preferred, YouTube fallback, Section 21.3)
    is fetched by the pipeline via yt-dlp; an upload is provided directly by
    the operator and needs no network fetch at ingestion time.
    """
    URL = "url"
    UPLOAD = "upload"


class Lecture(Base):
    __tablename__ = "lectures"

    id: Mapped[uuid.UUID] = _uuid_col()
    course_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(String(255))
    lecture_number: Mapped[int] = mapped_column(Integer)
    source_type: Mapped[LectureSourceType] = mapped_column(
        Enum(LectureSourceType, values_callable=lambda obj: [e.value for e in obj]),
        default=LectureSourceType.URL,
    )
    # Nullable because an uploaded lecture has no URL — the raw file instead
    # lives temporarily under settings.LOCAL_UPLOAD_DIR/<lecture_id>/ until
    # the pipeline consumes it (Section 21.3: never stored permanently).
    source_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    processing_status: Mapped[ProcessingStatus] = mapped_column(
        Enum(ProcessingStatus, values_callable=lambda obj: [e.value for e in obj]),
        default=ProcessingStatus.PENDING,
        index=True,
    )
    processing_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    course: Mapped["Course"] = relationship(back_populates="lectures")
    chunks: Mapped[list["LectureChunk"]] = relationship(
        back_populates="lecture", cascade="all, delete-orphan"
    )
    chapters: Mapped[list["Chapter"]] = relationship(
        back_populates="lecture", cascade="all, delete-orphan"
    )
    topics: Mapped[list["Topic"]] = relationship(
        back_populates="lecture", cascade="all, delete-orphan"
    )
    visual_assets: Mapped[list["VisualAsset"]] = relationship(
        back_populates="lecture", cascade="all, delete-orphan"
    )
    quizzes: Mapped[list["Quiz"]] = relationship(
        back_populates="lecture", cascade="all, delete-orphan"
    )
    study_notes: Mapped[list["StudyNote"]] = relationship(
        back_populates="lecture", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint("course_id", "lecture_number", name="uq_course_lecture_number"),
    )


# --------------------------------------------------------------------------
# Section 13.4 — Lecture Chunk (+ embedding, Section 8.5 / 14.2)
# --------------------------------------------------------------------------
class LectureChunk(Base):
    __tablename__ = "lecture_chunks"

    id: Mapped[uuid.UUID] = _uuid_col()
    lecture_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("lectures.id", ondelete="CASCADE"))
    text: Mapped[str] = mapped_column(Text)
    start_time: Mapped[float] = mapped_column(Float)  # seconds
    end_time: Mapped[float] = mapped_column(Float)
    chunk_index: Mapped[int] = mapped_column(Integer)
    source_type: Mapped[str] = mapped_column(String(32), default="transcript")
    # transcript | slide | board | formula | code | diagram (Section 11.4)
    topic_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("topics.id", ondelete="SET NULL"), nullable=True
    )
    chapter_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("chapters.id", ondelete="SET NULL"), nullable=True
    )
    visual_asset_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("visual_assets.id", ondelete="SET NULL"), nullable=True
    )
    # pgvector column — dimension pulled from settings (Section 14.2)
    embedding: Mapped[list[float] | None] = mapped_column(
        Vector(settings.EMBEDDING_DIM), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    lecture: Mapped["Lecture"] = relationship(back_populates="chunks")


# --------------------------------------------------------------------------
# Section 13.6 — Topic
# --------------------------------------------------------------------------
class Topic(Base):
    __tablename__ = "topics"

    id: Mapped[uuid.UUID] = _uuid_col()
    lecture_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("lectures.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text, default="")
    difficulty_score: Mapped[float] = mapped_column(Float, default=0.0)  # 0.0-1.0
    importance_score: Mapped[float] = mapped_column(Float, default=0.0)  # 0.0-1.0 (exam relevance)
    start_time: Mapped[float | None] = mapped_column(Float, nullable=True)
    end_time: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    lecture: Mapped["Lecture"] = relationship(back_populates="topics")


# --------------------------------------------------------------------------
# Section 13.7 — Chapter
# --------------------------------------------------------------------------
class Chapter(Base):
    __tablename__ = "chapters"

    id: Mapped[uuid.UUID] = _uuid_col()
    lecture_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("lectures.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(String(255))
    start_time: Mapped[float] = mapped_column(Float)
    end_time: Mapped[float] = mapped_column(Float)
    topic_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("topics.id", ondelete="SET NULL"), nullable=True
    )

    lecture: Mapped["Lecture"] = relationship(back_populates="chapters")


# --------------------------------------------------------------------------
# Section 13.5 — Visual Asset
# --------------------------------------------------------------------------
class VisualAsset(Base):
    __tablename__ = "visual_assets"

    id: Mapped[uuid.UUID] = _uuid_col()
    lecture_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("lectures.id", ondelete="CASCADE"))
    timestamp: Mapped[float] = mapped_column(Float)
    asset_url: Mapped[str] = mapped_column(String(1024))  # Cloudflare R2 URL
    asset_type: Mapped[str] = mapped_column(String(32))  # slide|board|diagram|code|formula
    ocr_text: Mapped[str] = mapped_column(Text, default="")
    ocr_confidence: Mapped[float] = mapped_column(Float, default=0.0)
    vision_llm_used: Mapped[bool] = mapped_column(Boolean, default=False)  # Section 8.3, 20.5
    uncertainty_flag: Mapped[bool] = mapped_column(Boolean, default=False)  # Section 9.3
    processing_status: Mapped[str] = mapped_column(String(32), default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    lecture: Mapped["Lecture"] = relationship(back_populates="visual_assets")


# --------------------------------------------------------------------------
# Section 13.8 — Quiz / Question
# --------------------------------------------------------------------------
class Quiz(Base):
    __tablename__ = "quizzes"

    id: Mapped[uuid.UUID] = _uuid_col()
    lecture_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("lectures.id", ondelete="CASCADE"))
    generated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    lecture: Mapped["Lecture"] = relationship(back_populates="quizzes")
    questions: Mapped[list["Question"]] = relationship(
        back_populates="quiz", cascade="all, delete-orphan"
    )


class Question(Base):
    __tablename__ = "questions"

    id: Mapped[uuid.UUID] = _uuid_col()
    quiz_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("quizzes.id", ondelete="CASCADE"))
    text: Mapped[str] = mapped_column(Text)
    options: Mapped[dict] = mapped_column(JSONB, default=dict)  # {"a": "...", "b": "...", ...}
    correct_answer: Mapped[str] = mapped_column(String(8))  # e.g. "a"
    explanation: Mapped[str] = mapped_column(Text, default="")
    source_timestamp: Mapped[float | None] = mapped_column(Float, nullable=True)
    difficulty: Mapped[str] = mapped_column(String(16), default="medium")  # easy|medium|hard

    quiz: Mapped["Quiz"] = relationship(back_populates="questions")


# --------------------------------------------------------------------------
# Section 13.9 — StudyNote (Admin App only writes scope_type="lecture" rows;
# scope_type="course" rows are written by the CLIENT App, not here — but the
# table is shared, so it is modeled once, in the Admin App's migration, and
# the Client App connects to the same table with restricted permissions.)
# --------------------------------------------------------------------------
class StudyNoteScope(str, enum.Enum):
    LECTURE = "lecture"
    COURSE = "course"


class StudyNoteStyle(str, enum.Enum):
    QUICK = "quick"
    FULL = "full"
    EXAM_FOCUSED = "exam_focused"


class StudyNote(Base):
    __tablename__ = "study_notes"

    id: Mapped[uuid.UUID] = _uuid_col()
    scope_type: Mapped[StudyNoteScope] = mapped_column(
        Enum(StudyNoteScope, values_callable=lambda obj: [e.value for e in obj])
    )
    lecture_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("lectures.id", ondelete="CASCADE"), nullable=True
    )
    course_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("courses.id", ondelete="CASCADE"), nullable=True
    )
    scope_lectures: Mapped[list] = mapped_column(JSONB, default=list)  # list[str(uuid)]
    topic_filter: Mapped[str | None] = mapped_column(String(255), nullable=True)
    style: Mapped[StudyNoteStyle] = mapped_column(
        Enum(StudyNoteStyle, values_callable=lambda obj: [e.value for e in obj]),
        default=StudyNoteStyle.FULL,
    )
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    lecture: Mapped["Lecture | None"] = relationship(back_populates="study_notes")
    sources: Mapped[list["StudyNoteSource"]] = relationship(
        back_populates="study_note", cascade="all, delete-orphan"
    )


# --------------------------------------------------------------------------
# Section 13.10 — StudyNoteSource
# --------------------------------------------------------------------------
class StudyNoteSource(Base):
    __tablename__ = "study_note_sources"

    id: Mapped[uuid.UUID] = _uuid_col()
    study_note_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("study_notes.id", ondelete="CASCADE")
    )
    lecture_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("lectures.id", ondelete="CASCADE"))
    chunk_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("lecture_chunks.id", ondelete="SET NULL"), nullable=True
    )
    start_time: Mapped[float] = mapped_column(Float)
    end_time: Mapped[float] = mapped_column(Float)

    study_note: Mapped["StudyNote"] = relationship(back_populates="sources")


# --------------------------------------------------------------------------
# Ingestion job tracking (Section 15.4/15.6) — Admin App internal bookkeeping,
# distinct from the Client App's Answer Cache (Section 10.5, 15.5 note).
# --------------------------------------------------------------------------
class IngestionJob(Base):
    __tablename__ = "ingestion_jobs"

    id: Mapped[uuid.UUID] = _uuid_col()
    lecture_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("lectures.id", ondelete="CASCADE"))
    stage: Mapped[str] = mapped_column(String(32))
    # transcription | ocr | vision | embedding | precompute | enhancement
    status: Mapped[str] = mapped_column(String(16), default="queued")
    # queued | running | done | failed
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )


# --------------------------------------------------------------------------
# Model-usage log (Section 8.2 — "log which application/model/feature served
# each generation" so the shared Groq budget, Section 20.7, can be monitored).
# --------------------------------------------------------------------------
class ModelUsageLog(Base):
    __tablename__ = "model_usage_log"

    id: Mapped[uuid.UUID] = _uuid_col()
    application: Mapped[str] = mapped_column(String(16), default="admin")  # admin|client
    feature: Mapped[str] = mapped_column(String(64))  # e.g. "precompute.chapters"
    model_used: Mapped[str] = mapped_column(String(64))
    lecture_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("lectures.id", ondelete="SET NULL"), nullable=True
    )
    prompt_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    completion_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
