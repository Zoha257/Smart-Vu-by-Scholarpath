"""topic time-range columns (future timeline features, e.g. difficulty heatmap)

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-25
"""
from alembic import op
import sqlalchemy as sa

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("topics", sa.Column("start_time", sa.Float(), nullable=True))
    op.add_column("topics", sa.Column("end_time", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("topics", "end_time")
    op.drop_column("topics", "start_time")
