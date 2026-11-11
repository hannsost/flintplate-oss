"""023 job import runs – tracking table for crawl/import history

Revision ID: 023
Revises: 022
Create Date: 2026-03-26
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "023"
down_revision = "022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "job_import_runs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("source", sa.String(100), nullable=False),
        sa.Column("status", sa.String(50), nullable=False, default="running"),
        sa.Column("jobs_found", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("jobs_new", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_msg", sa.Text(), nullable=True),
        sa.Column(
            "started_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_job_import_runs_source", "job_import_runs", ["source"])
    op.create_index("ix_job_import_runs_started_at", "job_import_runs", ["started_at"])


def downgrade() -> None:
    op.drop_index("ix_job_import_runs_started_at", table_name="job_import_runs")
    op.drop_index("ix_job_import_runs_source", table_name="job_import_runs")
    op.drop_table("job_import_runs")
