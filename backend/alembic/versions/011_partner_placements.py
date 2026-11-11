"""Partner placements – commission tracking

Revision ID: 011
Revises: 010_interview_schedules
Create Date: 2026-03-23
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op

revision = "011"
down_revision = "010_interview_schedules"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "partner_placements",
        sa.Column(
            "id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")
        ),
        sa.Column(
            "job_id",
            UUID(as_uuid=True),
            sa.ForeignKey("job_postings.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "application_id",
            UUID(as_uuid=True),
            sa.ForeignKey("applications.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "recruiter_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("candidate_name", sa.String(255), nullable=True),
        sa.Column("position_title", sa.String(255), nullable=True),
        sa.Column("company_name", sa.String(255), nullable=True),
        sa.Column("commission_pct", sa.Numeric(5, 2), nullable=False, server_default="27.50"),
        sa.Column(
            "annual_salary", sa.Integer(), nullable=True
        ),  # estimated gross, for commission calc
        sa.Column("commission_eur", sa.Numeric(10, 2), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "placed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index("ix_partner_placements_recruiter_id", "partner_placements", ["recruiter_id"])
    op.create_index("ix_partner_placements_placed_at", "partner_placements", ["placed_at"])


def downgrade() -> None:
    op.drop_index("ix_partner_placements_placed_at", "partner_placements")
    op.drop_index("ix_partner_placements_recruiter_id", "partner_placements")
    op.drop_table("partner_placements")
