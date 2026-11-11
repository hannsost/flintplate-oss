"""Team chat per venue: channels, messages with an expiry, and read marks."""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

from alembic import op

revision = "066"
down_revision = "065"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "fp_venues",
        sa.Column("chat_retention_days", sa.Integer(), nullable=False, server_default="90"),
    )
    op.create_check_constraint(
        "ck_fp_venue_chat_retention", "fp_venues", "chat_retention_days BETWEEN 7 AND 730"
    )
    op.create_table(
        "fp_chat_channels",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("venue_id", pg.UUID(as_uuid=True), sa.ForeignKey("fp_venues.id"), nullable=False),
        sa.Column("name", sa.String(60), nullable=False),
        sa.Column("topic", sa.String(200), nullable=False, server_default=""),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.UniqueConstraint("venue_id", "name", name="uq_fp_channel_name"),
    )
    op.create_index("ix_fp_chat_channels_venue_id", "fp_chat_channels", ["venue_id"])
    op.create_table(
        "fp_chat_messages",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "channel_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("fp_chat_channels.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("venue_id", pg.UUID(as_uuid=True), sa.ForeignKey("fp_venues.id"), nullable=False),
        sa.Column("author_id", pg.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("text", sa.String(2000), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sequence", sa.BigInteger(), sa.Identity(), nullable=False, unique=True),
    )
    op.create_index("ix_fp_chat_messages_channel_id", "fp_chat_messages", ["channel_id"])
    op.create_index("ix_fp_chat_messages_expires_at", "fp_chat_messages", ["expires_at"])
    op.create_table(
        "fp_chat_reads",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "channel_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("fp_chat_channels.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("user_id", pg.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("last_read_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_read_sequence", sa.BigInteger(), nullable=False, server_default="0"),
        sa.UniqueConstraint("channel_id", "user_id", name="uq_fp_chat_read"),
    )


def downgrade() -> None:
    op.drop_table("fp_chat_reads")
    op.drop_index("ix_fp_chat_messages_expires_at", table_name="fp_chat_messages")
    op.drop_index("ix_fp_chat_messages_channel_id", table_name="fp_chat_messages")
    op.drop_table("fp_chat_messages")
    op.drop_index("ix_fp_chat_channels_venue_id", table_name="fp_chat_channels")
    op.drop_table("fp_chat_channels")
    op.drop_constraint("ck_fp_venue_chat_retention", "fp_venues", type_="check")
    op.drop_column("fp_venues", "chat_retention_days")
