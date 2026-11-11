"""Companies table + recruiter role support

Revision ID: 009_companies_recruiter
Revises: 008_notifications
Create Date: 2026-03-23
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op

revision: str = "009_companies_recruiter"
down_revision: str | None = "008_notifications"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ── Companies ─────────────────────────────────────────────────────────────
    op.create_table(
        "companies",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("website", sa.String(500), nullable=True),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("location", sa.String(255), nullable=True),
        sa.Column("logo_url", sa.String(500), nullable=True),
        sa.Column(
            "created_by",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("companies_name_idx", "companies", ["name"])

    # ── Users: link recruiter → company ───────────────────────────────────────
    op.add_column(
        "users",
        sa.Column(
            "company_id",
            UUID(as_uuid=True),
            sa.ForeignKey("companies.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )

    # ── JobPostings: owner for recruiter-created postings ─────────────────────
    op.add_column(
        "job_postings",
        sa.Column(
            "owner_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index("job_postings_owner_idx", "job_postings", ["owner_id"])


def downgrade() -> None:
    op.drop_index("job_postings_owner_idx", table_name="job_postings")
    op.drop_column("job_postings", "owner_id")
    op.drop_column("users", "company_id")
    op.drop_index("companies_name_idx", table_name="companies")
    op.drop_table("companies")
