"""initial schema — pgvector extension + Section 13 tables

Revision ID: 0001
Revises:
Create Date: 2026-09-20
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID
from pgvector.sqlalchemy import Vector

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

EMBEDDING_DIM = 384  # keep in sync with .env EMBEDDING_DIM


def upgrade() -> None:
    # Section 14.2 — pgvector extension, self-hosted Postgres (Section 14.1)
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"')

    op.create_table(
        "courses",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("course_code", sa.String(32), unique=True, nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("description", sa.Text, server_default=""),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, server_default=sa.func.now()),
    )

    op.create_table(
        "lectures",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("course_id", UUID(as_uuid=True), sa.ForeignKey("courses.id", ondelete="CASCADE")),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("lecture_number", sa.Integer, nullable=False),
        sa.Column("source_url", sa.String(1024), nullable=False),
        sa.Column("duration_seconds", sa.Integer, nullable=True),
        sa.Column(
            "processing_status",
            sa.Enum(
                "pending", "processing", "transcribing", "extracting_visuals",
                "generating_embeddings", "generating_intelligence", "completed",
                "failed", "reprocessed",
                name="processingstatus",
            ),
            server_default="pending",
        ),
        sa.Column("processing_error", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, server_default=sa.func.now()),
        sa.UniqueConstraint("course_id", "lecture_number", name="uq_course_lecture_number"),
    )

    op.create_table(
        "topics",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("lecture_id", UUID(as_uuid=True), sa.ForeignKey("lectures.id", ondelete="CASCADE")),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text, server_default=""),
        sa.Column("difficulty_score", sa.Float, server_default="0"),
        sa.Column("importance_score", sa.Float, server_default="0"),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
    )

    op.create_table(
        "chapters",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("lecture_id", UUID(as_uuid=True), sa.ForeignKey("lectures.id", ondelete="CASCADE")),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("start_time", sa.Float, nullable=False),
        sa.Column("end_time", sa.Float, nullable=False),
        sa.Column("topic_id", UUID(as_uuid=True), sa.ForeignKey("topics.id", ondelete="SET NULL"), nullable=True),
    )

    op.create_table(
        "visual_assets",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("lecture_id", UUID(as_uuid=True), sa.ForeignKey("lectures.id", ondelete="CASCADE")),
        sa.Column("timestamp", sa.Float, nullable=False),
        sa.Column("asset_url", sa.String(1024), nullable=False),
        sa.Column("asset_type", sa.String(32), nullable=False),
        sa.Column("ocr_text", sa.Text, server_default=""),
        sa.Column("ocr_confidence", sa.Float, server_default="0"),
        sa.Column("vision_llm_used", sa.Boolean, server_default=sa.false()),
        sa.Column("uncertainty_flag", sa.Boolean, server_default=sa.false()),
        sa.Column("processing_status", sa.String(32), server_default="pending"),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
    )

    op.create_table(
        "lecture_chunks",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("lecture_id", UUID(as_uuid=True), sa.ForeignKey("lectures.id", ondelete="CASCADE")),
        sa.Column("text", sa.Text, nullable=False),
        sa.Column("start_time", sa.Float, nullable=False),
        sa.Column("end_time", sa.Float, nullable=False),
        sa.Column("chunk_index", sa.Integer, nullable=False),
        sa.Column("source_type", sa.String(32), server_default="transcript"),
        sa.Column("topic_id", UUID(as_uuid=True), sa.ForeignKey("topics.id", ondelete="SET NULL"), nullable=True),
        sa.Column("chapter_id", UUID(as_uuid=True), sa.ForeignKey("chapters.id", ondelete="SET NULL"), nullable=True),
        sa.Column("visual_asset_id", UUID(as_uuid=True), sa.ForeignKey("visual_assets.id", ondelete="SET NULL"), nullable=True),
        sa.Column("embedding", Vector(EMBEDDING_DIM), nullable=True),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
    )
    # IVFFlat index for fast approximate nearest-neighbour search (Section 14.2)
    op.execute(
        "CREATE INDEX ix_lecture_chunks_embedding ON lecture_chunks "
        "USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100)"
    )

    op.create_table(
        "quizzes",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("lecture_id", UUID(as_uuid=True), sa.ForeignKey("lectures.id", ondelete="CASCADE")),
        sa.Column("generated_at", sa.DateTime, server_default=sa.func.now()),
    )

    op.create_table(
        "questions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("quiz_id", UUID(as_uuid=True), sa.ForeignKey("quizzes.id", ondelete="CASCADE")),
        sa.Column("text", sa.Text, nullable=False),
        sa.Column("options", JSONB, server_default="{}"),
        sa.Column("correct_answer", sa.String(8), nullable=False),
        sa.Column("explanation", sa.Text, server_default=""),
        sa.Column("source_timestamp", sa.Float, nullable=True),
        sa.Column("difficulty", sa.String(16), server_default="medium"),
    )

    op.create_table(
        "study_notes",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("scope_type", sa.Enum("lecture", "course", name="studynotescope"), nullable=False),
        sa.Column("lecture_id", UUID(as_uuid=True), sa.ForeignKey("lectures.id", ondelete="CASCADE"), nullable=True),
        sa.Column("course_id", UUID(as_uuid=True), sa.ForeignKey("courses.id", ondelete="CASCADE"), nullable=True),
        sa.Column("scope_lectures", JSONB, server_default="[]"),
        sa.Column("topic_filter", sa.String(255), nullable=True),
        sa.Column(
            "style",
            sa.Enum("quick", "full", "exam_focused", name="studynotestyle"),
            server_default="full",
        ),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
    )

    op.create_table(
        "study_note_sources",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("study_note_id", UUID(as_uuid=True), sa.ForeignKey("study_notes.id", ondelete="CASCADE")),
        sa.Column("lecture_id", UUID(as_uuid=True), sa.ForeignKey("lectures.id", ondelete="CASCADE")),
        sa.Column("chunk_id", UUID(as_uuid=True), sa.ForeignKey("lecture_chunks.id", ondelete="SET NULL"), nullable=True),
        sa.Column("start_time", sa.Float, nullable=False),
        sa.Column("end_time", sa.Float, nullable=False),
    )

    op.create_table(
        "ingestion_jobs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("lecture_id", UUID(as_uuid=True), sa.ForeignKey("lectures.id", ondelete="CASCADE")),
        sa.Column("stage", sa.String(32), nullable=False),
        sa.Column("status", sa.String(16), server_default="queued"),
        sa.Column("attempts", sa.Integer, server_default="0"),
        sa.Column("last_error", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, server_default=sa.func.now()),
    )

    op.create_table(
        "model_usage_log",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("application", sa.String(16), server_default="admin"),
        sa.Column("feature", sa.String(64), nullable=False),
        sa.Column("model_used", sa.String(64), nullable=False),
        sa.Column("lecture_id", UUID(as_uuid=True), sa.ForeignKey("lectures.id", ondelete="SET NULL"), nullable=True),
        sa.Column("prompt_tokens", sa.Integer, nullable=True),
        sa.Column("completion_tokens", sa.Integer, nullable=True),
        sa.Column("latency_ms", sa.Integer, nullable=True),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
    )
    op.create_index("ix_model_usage_log_created_at", "model_usage_log", ["created_at"])


def downgrade() -> None:
    op.drop_table("model_usage_log")
    op.drop_table("ingestion_jobs")
    op.drop_table("study_note_sources")
    op.drop_table("study_notes")
    op.drop_table("questions")
    op.drop_table("quizzes")
    op.execute("DROP INDEX IF EXISTS ix_lecture_chunks_embedding")
    op.drop_table("lecture_chunks")
    op.drop_table("visual_assets")
    op.drop_table("chapters")
    op.drop_table("topics")
    op.drop_table("lectures")
    op.drop_table("courses")
    op.execute("DROP TYPE IF EXISTS studynotestyle")
    op.execute("DROP TYPE IF EXISTS studynotescope")
    op.execute("DROP TYPE IF EXISTS processingstatus")
