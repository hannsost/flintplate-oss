"""Align time-correction timestamps with the inherited ORM and timestamptz schema."""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "060"
down_revision = "059"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "time_entry_corrections",
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )


def downgrade() -> None:
    op.drop_column("time_entry_corrections", "updated_at")
