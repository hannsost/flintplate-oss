"""Explicit job publication, optimistic versions and decision history.

Existing jobs become drafts: the old schema contains no publication consent.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "051"
down_revision = "050"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "job_postings",
        sa.Column("publication_status", sa.String(20), nullable=False, server_default="draft"),
    )
    op.add_column(
        "job_postings", sa.Column("version", sa.Integer(), nullable=False, server_default="1")
    )
    for name in ("published_at", "expires_at", "archived_at"):
        op.add_column("job_postings", sa.Column(name, sa.DateTime(timezone=True)))
    # An orphaned recruiter posting must never be treated as a reviewed import.
    op.execute(
        "UPDATE job_postings SET source = 'recruiter' WHERE owner_id IS NOT NULL OR tenant_id IS NOT NULL"
    )
    op.create_check_constraint(
        "ck_job_publication_status",
        "job_postings",
        "publication_status IN ('draft', 'published', 'archived')",
    )
    op.create_check_constraint("ck_job_version", "job_postings", "version > 0")
    op.create_check_constraint(
        "ck_job_publication_dates",
        "job_postings",
        "publication_status != 'published' OR (published_at IS NOT NULL AND expires_at IS NOT NULL AND expires_at > published_at)",
    )
    op.create_index(
        "ix_job_publication_window",
        "job_postings",
        ["publication_status", "expires_at", "tenant_id"],
    )
    op.create_table(
        "job_publication_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "job_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("job_postings.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "actor_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(30), nullable=False),
        sa.Column("note", sa.String(1000)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("job_id", "version", name="uq_job_publication_version"),
    )
    op.create_index("ix_job_publication_events_job_id", "job_publication_events", ["job_id"])


def downgrade() -> None:
    op.drop_table("job_publication_events")
    op.drop_index("ix_job_publication_window", table_name="job_postings")
    for name in ("ck_job_publication_dates", "ck_job_version", "ck_job_publication_status"):
        op.drop_constraint(name, "job_postings", type_="check")
    for name in ("archived_at", "expires_at", "published_at", "version", "publication_status"):
        op.drop_column("job_postings", name)
