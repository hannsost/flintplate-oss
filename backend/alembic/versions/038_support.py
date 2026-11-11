"""038 support – Support sessions + config tables

Revision ID: 038
Revises: 037
Create Date: 2026-03-31
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op

revision = "038"
down_revision = "037"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "support_configs",
        sa.Column(
            "id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")
        ),
        sa.Column(
            "tenant_id",
            UUID(as_uuid=True),
            sa.ForeignKey("customers.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("allow_video", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("allow_audio", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("allow_remote_control", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("allow_dom_viewing", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("billing_model", sa.String(20), nullable=False, server_default="'included'"),
        sa.Column("per_session_cents", sa.Integer(), nullable=True),
        sa.Column("per_minute_cents", sa.Integer(), nullable=True),
        sa.Column("included_minutes_per_month", sa.Integer(), nullable=True),
        sa.Column("widget_title", sa.String(100), nullable=False, server_default="'Live Support'"),
        sa.Column("widget_color", sa.String(20), nullable=False, server_default="'#2563eb'"),
        sa.Column("welcome_message", sa.Text(), nullable=True),
        sa.Column("mask_sensitive_fields", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("require_consent", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("data_retention_days", sa.Integer(), nullable=False, server_default="30"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    op.create_table(
        "support_sessions",
        sa.Column(
            "id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")
        ),
        sa.Column(
            "tenant_id",
            UUID(as_uuid=True),
            sa.ForeignKey("customers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "requester_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "agent_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("status", sa.String(20), nullable=False, server_default="'pending'"),
        sa.Column("subject", sa.String(255), nullable=False),
        # DSGVO consent
        sa.Column("consent_given", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("consent_given_at", sa.DateTime(timezone=True), nullable=True),
        # Timing
        sa.Column(
            "requested_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_seconds", sa.Integer(), nullable=True),
        # Session capabilities
        sa.Column("video_enabled", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("audio_enabled", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("remote_control_enabled", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("dom_viewing_enabled", sa.Boolean(), nullable=False, server_default="false"),
        # Billing
        sa.Column("billing_model", sa.String(20), nullable=False, server_default="'included'"),
        sa.Column("billed_amount_cents", sa.Integer(), nullable=True),
        sa.Column("billed_at", sa.DateTime(timezone=True), nullable=True),
        # Notes (agent-only, NOT exposed to customer)
        sa.Column("agent_notes", sa.Text(), nullable=True),
        # Public summary (visible to customer)
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("end_reason", sa.String(50), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_support_sessions_tenant", "support_sessions", ["tenant_id", "status"])
    op.create_index("ix_support_sessions_requester", "support_sessions", ["requester_id"])
    op.create_index("ix_support_sessions_agent", "support_sessions", ["agent_id"])


def downgrade() -> None:
    op.drop_table("support_sessions")
    op.drop_table("support_configs")
