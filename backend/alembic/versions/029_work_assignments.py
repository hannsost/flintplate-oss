"""029 worker_assignments – Einsatzplanung / Schichtplan

Revision ID: 029
Revises: 028
Create Date: 2026-03-27
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op

revision = "029"
down_revision = "028"
branch_labels = None
depends_on = None

# planned | confirmed | active | completed | cancelled
ASSIGNMENT_STATUS = ("planned", "confirmed", "active", "completed", "cancelled")


def upgrade() -> None:
    # ── worker_assignments ──────────────────────────────────────────────────────
    op.create_table(
        "worker_assignments",
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
        sa.Column(
            "created_by",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        # Date range
        sa.Column("start_date", sa.Date, nullable=False),
        sa.Column("end_date", sa.Date, nullable=False),
        # Daily shift window (optional – can be a full-day assignment)
        sa.Column("shift_start", sa.Time, nullable=True),  # e.g. 08:00
        sa.Column("shift_end", sa.Time, nullable=True),  # e.g. 17:00
        # Location / context
        sa.Column("customer_company", sa.String(255), nullable=True),
        sa.Column("location", sa.String(255), nullable=True),
        sa.Column("role_description", sa.String(255), nullable=True),
        sa.Column("notes", sa.Text, nullable=True),
        # Status: planned | confirmed | active | completed | cancelled
        sa.Column("status", sa.String(30), nullable=False, server_default="planned"),
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
    op.create_index(
        "ix_worker_assignments_worker", "worker_assignments", ["worker_id", "start_date"]
    )
    op.create_index(
        "ix_worker_assignments_tenant", "worker_assignments", ["tenant_id", "start_date"]
    )

    # ── Add deferred FK from time_entries → worker_assignments ─────────────────
    op.create_foreign_key(
        "fk_time_entries_assignment_id",
        "time_entries",
        "worker_assignments",
        ["assignment_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_time_entries_assignment_id", "time_entries", type_="foreignkey")
    op.drop_index("ix_worker_assignments_tenant", "worker_assignments")
    op.drop_index("ix_worker_assignments_worker", "worker_assignments")
    op.drop_table("worker_assignments")
