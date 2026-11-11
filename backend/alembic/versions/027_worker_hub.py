"""027 worker_hub – WorkerSettings

Revision ID: 027
Revises: 026
Create Date: 2026-03-27
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

from alembic import op

revision = "027"
down_revision = "026"
branch_labels = None
depends_on = None

_DEFAULT_MODULES = (
    '{"timetracking": true, "schedule": true, "messages": true, '
    '"documents": true, "absences": true, "equipment": true, '
    '"tasks": true, "payroll": true, "tickets": true, "profile_selfservice": true}'
)


def upgrade() -> None:
    op.create_table(
        "worker_settings",
        sa.Column(
            "id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")
        ),
        sa.Column(
            "user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
            index=True,
        ),
        sa.Column(
            "tenant_id",
            UUID(as_uuid=True),
            sa.ForeignKey("customers.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        # fulltime | parttime | minijob | temp
        sa.Column("employment_type", sa.String(20), nullable=False, server_default="temp"),
        sa.Column("max_weekly_hours", sa.Integer, nullable=True),
        sa.Column("hourly_rate", sa.Numeric(8, 2), nullable=True),
        sa.Column("active_modules", JSONB, nullable=False, server_default=_DEFAULT_MODULES),
        sa.Column("internal_note", sa.Text, nullable=True),
        sa.Column(
            "assigned_manager_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("activated_at", sa.TIMESTAMP(timezone=True), nullable=True),
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


def downgrade() -> None:
    op.drop_table("worker_settings")
