"""Zeitarbeit-Modul – work assignments, availability, dispositions

Revision ID: 012
Revises: 011
Create Date: 2026-03-23
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ARRAY, UUID

from alembic import op

revision = "012"
down_revision = "011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── Work assignments (Aufträge) ───────────────────────────────────────────
    op.create_table(
        "work_assignments",
        sa.Column(
            "id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")
        ),
        sa.Column(
            "recruiter_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "company_id",
            UUID(as_uuid=True),
            sa.ForeignKey("companies.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("required_skills", ARRAY(sa.Text()), nullable=False, server_default="{}"),
        sa.Column("location", sa.String(255), nullable=True),
        sa.Column("shift", sa.String(50), nullable=True),  # day / night / flexible
        sa.Column("hourly_rate", sa.Numeric(8, 2), nullable=True),
        sa.Column("start_date", sa.Date(), nullable=True),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("status", sa.String(50), nullable=False, server_default="incoming"),
        # incoming → matching → active → extended → completed → cancelled
        sa.Column("max_duration_months", sa.Integer(), nullable=False, server_default="18"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_work_assignments_recruiter_id", "work_assignments", ["recruiter_id"])
    op.create_index("ix_work_assignments_status", "work_assignments", ["status"])

    # ── Temp worker availability ───────────────────────────────────────────────
    op.create_table(
        "temp_worker_availability",
        sa.Column(
            "id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")
        ),
        sa.Column(
            "user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("is_in_pool", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("available_from", sa.Date(), nullable=True),
        sa.Column("available_until", sa.Date(), nullable=True),
        sa.Column("preferred_shift", sa.String(50), nullable=True),
        sa.Column("preferred_location", sa.String(255), nullable=True),
        sa.Column("max_commute_km", sa.Integer(), nullable=True),
        sa.Column(
            "total_placed_months", sa.Numeric(5, 2), nullable=False, server_default="0"
        ),  # AÜG tracking
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_temp_worker_availability_user_id", "temp_worker_availability", ["user_id"])
    op.create_index(
        "ix_temp_worker_availability_is_in_pool", "temp_worker_availability", ["is_in_pool"]
    )

    # ── Dispositions (Matching worker ↔ assignment) ───────────────────────────
    op.create_table(
        "dispositions",
        sa.Column(
            "id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")
        ),
        sa.Column(
            "assignment_id",
            UUID(as_uuid=True),
            sa.ForeignKey("work_assignments.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "worker_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("score", sa.Numeric(5, 4), nullable=False, server_default="0"),
        sa.Column("matched_skills", ARRAY(sa.Text()), nullable=False, server_default="{}"),
        sa.Column("missing_skills", ARRAY(sa.Text()), nullable=False, server_default="{}"),
        sa.Column("status", sa.String(50), nullable=False, server_default="suggested"),
        # suggested → contacted → confirmed → active → completed → rejected
        sa.Column("started_at", sa.Date(), nullable=True),
        sa.Column("ended_at", sa.Date(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_dispositions_assignment_id", "dispositions", ["assignment_id"])
    op.create_index("ix_dispositions_worker_id", "dispositions", ["worker_id"])


def downgrade() -> None:
    op.drop_table("dispositions")
    op.drop_table("temp_worker_availability")
    op.drop_table("work_assignments")
