"""Encrypted user connections, reviewed messages and interview booking."""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "044"
down_revision = "043"
branch_labels = None
depends_on = None


def identity() -> list[sa.Column]:  # Alembic accepts SQLAlchemy's generic column declarations.
    return [
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    ]


def upgrade() -> None:
    op.create_table(
        "workspace_connections",
        *identity(),
        sa.Column(
            "user_id", sa.UUID(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "tenant_id",
            sa.UUID(),
            sa.ForeignKey("customers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("provider", sa.String(20), nullable=False),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("access_cipher", sa.Text(), nullable=False),
        sa.Column("refresh_cipher", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("user_id", "provider", name="uq_connection_user_provider"),
    )
    op.create_table(
        "integration_authorizations",
        *identity(),
        sa.Column(
            "user_id", sa.UUID(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "tenant_id",
            sa.UUID(),
            sa.ForeignKey("customers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("provider", sa.String(20), nullable=False),
        sa.Column("state_digest", sa.String(64), unique=True, nullable=False),
        sa.Column("verifier_cipher", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True)),
    )
    op.create_table(
        "recruiting_messages",
        *identity(),
        sa.Column(
            "tenant_id",
            sa.UUID(),
            sa.ForeignKey("customers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "person_id", sa.UUID(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("author_id", sa.UUID(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("recipient", sa.String(255), nullable=False),
        sa.Column("subject", sa.String(300), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("provider", sa.String(20)),
        sa.Column("external_id", sa.String(255)),
        sa.Column("sent_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_recruiting_messages_tenant_id", "recruiting_messages", ["tenant_id"])
    op.create_index("ix_recruiting_messages_person_id", "recruiting_messages", ["person_id"])
    op.create_table(
        "interview_bookings",
        *identity(),
        sa.Column(
            "tenant_id",
            sa.UUID(),
            sa.ForeignKey("customers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "application_id",
            sa.UUID(),
            sa.ForeignKey("applications.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "owner_id", sa.UUID(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("token_digest", sa.String(64), unique=True, nullable=False),
        sa.Column("slots", postgresql.ARRAY(sa.DateTime(timezone=True)), nullable=False),
        sa.Column("duration_minutes", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("booked_at", sa.DateTime(timezone=True)),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column(
            "schedule_id", sa.UUID(), sa.ForeignKey("interview_schedules.id", ondelete="SET NULL")
        ),
    )
    op.add_column(
        "interview_schedules",
        sa.Column("duration_minutes", sa.Integer(), nullable=False, server_default="30"),
    )
    op.create_table(
        "calendar_deliveries",
        *identity(),
        sa.Column(
            "connection_id",
            sa.UUID(),
            sa.ForeignKey("workspace_connections.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "schedule_id",
            sa.UUID(),
            sa.ForeignKey("interview_schedules.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("external_id", sa.String(255)),
        sa.Column("status", sa.String(20), nullable=False),
        sa.UniqueConstraint("connection_id", "schedule_id", name="uq_calendar_connection_schedule"),
    )


def downgrade() -> None:
    op.drop_table("calendar_deliveries")
    op.drop_column("interview_schedules", "duration_minutes")
    op.drop_table("interview_bookings")
    op.drop_index("ix_recruiting_messages_person_id", table_name="recruiting_messages")
    op.drop_index("ix_recruiting_messages_tenant_id", table_name="recruiting_messages")
    op.drop_table("recruiting_messages")
    op.drop_table("integration_authorizations")
    op.drop_table("workspace_connections")
