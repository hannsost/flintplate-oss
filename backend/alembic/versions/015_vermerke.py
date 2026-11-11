"""Vermerke – operative Wissensschicht (PalmSCOUT MVP 2)

Revision ID: 015
Revises: 014
Create Date: 2026-03-23
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op

revision = "015"
down_revision = "014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "vermerke",
        sa.Column(
            "id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")
        ),
        sa.Column(
            "author_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "candidate_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "application_id",
            UUID(as_uuid=True),
            sa.ForeignKey("applications.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "assignment_id",
            UUID(as_uuid=True),
            sa.ForeignKey("work_assignments.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("type", sa.String(50), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("valid_until", sa.Date(), nullable=True),
        sa.Column("strength", sa.SmallInteger(), nullable=True),
        sa.Column("visibility", sa.String(20), nullable=False, server_default="internal"),
        sa.Column("source", sa.String(100), nullable=True, server_default="manual"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index("ix_vermerke_author_id", "vermerke", ["author_id"])
    op.create_index("ix_vermerke_candidate_id", "vermerke", ["candidate_id"])
    op.create_index("ix_vermerke_application_id", "vermerke", ["application_id"])
    op.create_index("ix_vermerke_assignment_id", "vermerke", ["assignment_id"])
    op.create_index("ix_vermerke_type", "vermerke", ["type"])
    op.create_index("ix_vermerke_visibility", "vermerke", ["visibility"])


def downgrade() -> None:
    op.drop_index("ix_vermerke_visibility", "vermerke")
    op.drop_index("ix_vermerke_type", "vermerke")
    op.drop_index("ix_vermerke_assignment_id", "vermerke")
    op.drop_index("ix_vermerke_application_id", "vermerke")
    op.drop_index("ix_vermerke_candidate_id", "vermerke")
    op.drop_index("ix_vermerke_author_id", "vermerke")
    op.drop_table("vermerke")
