"""lecture local-upload source support (alternative to URL fetch, Section 21.3)

Adds source_type ("url" | "upload") to lectures, and makes source_url
nullable since an upload-sourced lecture has no URL.

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-22
"""
from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    lecture_source_type = sa.Enum("url", "upload", name="lecturesourcetype")
    lecture_source_type.create(op.get_bind(), checkfirst=True)

    op.add_column(
        "lectures",
        sa.Column(
            "source_type",
            lecture_source_type,
            nullable=False,
            server_default="url",  # every existing row was URL-sourced before this migration
        ),
    )
    op.alter_column("lectures", "source_url", existing_type=sa.String(1024), nullable=True)


def downgrade() -> None:
    # Any upload-sourced lecture has no source_url, so this cannot be
    # reversed without data loss for those rows -- fail loudly instead of
    # silently reintroducing a NOT NULL constraint that data would violate.
    conn = op.get_bind()
    orphaned = conn.execute(
        sa.text("SELECT count(*) FROM lectures WHERE source_url IS NULL")
    ).scalar()
    if orphaned:
        raise RuntimeError(
            f"Cannot downgrade: {orphaned} lecture(s) have no source_url "
            f"(they are upload-sourced). Assign a source_url or delete them first."
        )
    op.alter_column("lectures", "source_url", existing_type=sa.String(1024), nullable=False)
    op.drop_column("lectures", "source_type")
    sa.Enum(name="lecturesourcetype").drop(op.get_bind(), checkfirst=True)
