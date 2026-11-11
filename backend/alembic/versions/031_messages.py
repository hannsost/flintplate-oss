"""031 messages – Team-Inbox messaging

Revision ID: 031
Revises: 030
Create Date: 2026-03-27
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op

revision = "031"
down_revision = "030"
branch_labels = None
depends_on = None

# open | in_progress | resolved
THREAD_STATUS = ("open", "in_progress", "resolved")


def upgrade() -> None:
    # ── message_threads ───────────────────────────────────────────────────────
    op.create_table(
        "message_threads",
        sa.Column(
            "id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")
        ),
        sa.Column(
            "tenant_id",
            UUID(as_uuid=True),
            sa.ForeignKey("customers.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "worker_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        # Which team handles this thread (nullable = unassigned / all-tenant)
        sa.Column(
            "assigned_team_id",
            UUID(as_uuid=True),
            sa.ForeignKey("teams.id", ondelete="SET NULL"),
            nullable=True,
        ),
        # Which HR person claimed it
        sa.Column(
            "claimed_by",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("subject", sa.String(255), nullable=False),
        # open | in_progress | resolved
        sa.Column("status", sa.String(20), nullable=False, server_default="open"),
        sa.Column("last_message_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("unread_hr", sa.Integer, nullable=False, server_default="0"),
        sa.Column("unread_worker", sa.Integer, nullable=False, server_default="0"),
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
    op.create_index("ix_message_threads_worker", "message_threads", ["worker_id", "status"])
    op.create_index("ix_message_threads_tenant", "message_threads", ["tenant_id", "status"])

    # ── messages ──────────────────────────────────────────────────────────────
    op.create_table(
        "messages",
        sa.Column(
            "id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")
        ),
        sa.Column(
            "thread_id",
            UUID(as_uuid=True),
            sa.ForeignKey("message_threads.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "sender_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("body", sa.Text, nullable=False),
        # True = internal HR note, invisible to worker
        sa.Column("is_internal_note", sa.Boolean, nullable=False, server_default="false"),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_messages_thread", "messages", ["thread_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_messages_thread", "messages")
    op.drop_table("messages")
    op.drop_index("ix_message_threads_tenant", "message_threads")
    op.drop_index("ix_message_threads_worker", "message_threads")
    op.drop_table("message_threads")
