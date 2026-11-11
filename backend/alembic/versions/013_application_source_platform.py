"""Add source_platform to applications for auto-tracking

Revision ID: 013
Revises: 012
Create Date: 2026-03-23
"""

import sqlalchemy as sa

from alembic import op

revision = "013"
down_revision = "012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "applications",
        sa.Column("source_platform", sa.String(100), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("applications", "source_platform")
