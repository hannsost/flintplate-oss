"""032 absences – Worker absence management

Revision ID: 032
Revises: 031
Create Date: 2026-03-27
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op

revision = "032"
down_revision = "031"
branch_labels = None
depends_on = None

# vacation | sick | unpaid | special | other
ABSENCE_TYPES = ("vacation", "sick", "unpaid", "special", "other")
# pending | approved | rejected | cancelled
ABSENCE_STATUS = ("pending", "approved", "rejected", "cancelled")


def upgrade() -> None:
    op.create_table(
        "absences",
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
        # vacation | sick | unpaid | special | other
        sa.Column("absence_type", sa.String(30), nullable=False),
        sa.Column("start_date", sa.Date, nullable=False),
        sa.Column("end_date", sa.Date, nullable=False),
        # Calculated, stored for quick queries (excludes weekends)
        sa.Column("working_days", sa.Integer, nullable=True),
        # Worker's reason / note
        sa.Column("worker_note", sa.Text, nullable=True),
        # HR decision
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column(
            "reviewed_by",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("reviewed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("reviewer_note", sa.Text, nullable=True),
        # Sick leave: certificate uploaded?
        sa.Column("certificate_uploaded", sa.Boolean, nullable=False, server_default="false"),
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
    op.create_index("ix_absences_worker_date", "absences", ["worker_id", "start_date"])
    op.create_index("ix_absences_tenant_status", "absences", ["tenant_id", "status"])


def downgrade() -> None:
    op.drop_index("ix_absences_tenant_status", "absences")
    op.drop_index("ix_absences_worker_date", "absences")
    op.drop_table("absences")
