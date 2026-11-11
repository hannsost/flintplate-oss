"""Interview schedules table

Revision ID: 010_interview_schedules
Revises: 009_companies_recruiter
Create Date: 2026-03-23
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "010_interview_schedules"
down_revision: str | None = "009_companies_recruiter"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "interview_schedules",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "application_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("applications.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "proposed_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=False),
        # proposed / confirmed / declined / cancelled
        sa.Column("status", sa.String(20), nullable=False, server_default="proposed"),
        sa.Column("meeting_url", sa.String(1000), nullable=True),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("reminder_sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_interview_schedules_application_id",
        "interview_schedules",
        ["application_id"],
    )
    op.create_index(
        "ix_interview_schedules_scheduled_at",
        "interview_schedules",
        ["scheduled_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_interview_schedules_scheduled_at", table_name="interview_schedules")
    op.drop_index("ix_interview_schedules_application_id", table_name="interview_schedules")
    op.drop_table("interview_schedules")
