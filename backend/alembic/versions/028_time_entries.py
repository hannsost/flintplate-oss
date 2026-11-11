"""028 time_entries – Worker time tracking

Revision ID: 028
Revises: 027
Create Date: 2026-03-27
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

from alembic import op

revision = "028"
down_revision = "027"
branch_labels = None
depends_on = None

# draft | submitted | approved | rejected | correction_requested
TIME_ENTRY_STATUS = ("draft", "submitted", "approved", "rejected", "correction_requested")


def upgrade() -> None:
    # ── time_entries ──────────────────────────────────────────────────────────
    op.create_table(
        "time_entries",
        sa.Column(
            "id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")
        ),
        sa.Column(
            "worker_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "tenant_id",
            UUID(as_uuid=True),
            sa.ForeignKey("customers.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        # Optional link to a work assignment (FK added in 029 after work_assignments is created)
        sa.Column("assignment_id", UUID(as_uuid=True), nullable=True),
        sa.Column("entry_date", sa.Date, nullable=False),
        sa.Column("clock_in", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("clock_out", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("break_minutes", sa.Integer, nullable=False, server_default="0"),
        sa.Column("status", sa.String(30), nullable=False, server_default="draft"),
        sa.Column("location_note", sa.String(255), nullable=True),
        sa.Column("project_code", sa.String(100), nullable=True),
        sa.Column("cost_center", sa.String(100), nullable=True),
        # GPS (optional)
        sa.Column("gps_lat", sa.Numeric(10, 7), nullable=True),
        sa.Column("gps_lon", sa.Numeric(10, 7), nullable=True),
        # Approval
        sa.Column(
            "approved_by",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("approved_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("rejection_note", sa.Text, nullable=True),
        sa.Column("worker_note", sa.Text, nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_time_entries_worker_date", "time_entries", ["worker_id", "entry_date"])
    op.create_index("ix_time_entries_tenant_status", "time_entries", ["tenant_id", "status"])

    # ── time_entry_corrections ────────────────────────────────────────────────
    op.create_table(
        "time_entry_corrections",
        sa.Column(
            "id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")
        ),
        sa.Column(
            "entry_id",
            UUID(as_uuid=True),
            sa.ForeignKey("time_entries.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "requested_by",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("old_values", JSONB, nullable=False),  # snapshot before change
        sa.Column("new_values", JSONB, nullable=False),  # requested new values
        sa.Column("reason", sa.Text, nullable=False),
        # pending | approved | rejected
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column(
            "resolved_by",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("resolved_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )


def downgrade() -> None:
    op.drop_table("time_entry_corrections")
    op.drop_index("ix_time_entries_tenant_status", "time_entries")
    op.drop_index("ix_time_entries_worker_date", "time_entries")
    op.drop_table("time_entries")
