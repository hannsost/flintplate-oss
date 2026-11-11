"""Versioned process definitions, bounded runs and review history.

Revision ID: 047
Revises: 046
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

from alembic import op

revision = "047"
down_revision = "046"
branch_labels = None
depends_on = None


def base_columns() -> list[sa.Column]:
    return [
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    ]


def upgrade() -> None:
    op.create_table(
        "process_templates",
        *base_columns(),
        sa.Column(
            "tenant_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("customers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("four_eyes", sa.Boolean(), nullable=False),
        sa.Column("steps", pg.JSONB(), nullable=False),
    )
    op.create_index("ix_process_templates_tenant_id", "process_templates", ["tenant_id"])
    op.create_table(
        "process_runs",
        *base_columns(),
        sa.Column(
            "tenant_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("customers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "template_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("process_templates.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "job_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("job_postings.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "created_by", pg.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL")
        ),
        sa.Column("request_key", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("template_version", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("cursor", sa.Integer(), nullable=False),
        sa.Column("four_eyes", sa.Boolean(), nullable=False),
        sa.Column("authorize_ai", sa.Boolean(), nullable=False),
        sa.Column("source", pg.JSONB(), nullable=False),
        sa.Column("steps", pg.JSONB(), nullable=False),
        sa.Column("results", pg.JSONB(), nullable=False),
        sa.UniqueConstraint("tenant_id", "request_key", name="uq_process_request"),
    )
    op.create_index("ix_process_runs_tenant_id", "process_runs", ["tenant_id"])
    op.create_table(
        "process_events",
        *base_columns(),
        sa.Column(
            "run_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("process_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "actor_id", pg.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL")
        ),
        sa.Column("action", sa.String(30), nullable=False),
        sa.Column("step", sa.Integer(), nullable=False),
        sa.Column("note", sa.String(2000), nullable=False),
    )
    op.create_index("ix_process_events_run_id", "process_events", ["run_id"])


def downgrade() -> None:
    op.drop_table("process_events")
    op.drop_table("process_runs")
    op.drop_table("process_templates")
