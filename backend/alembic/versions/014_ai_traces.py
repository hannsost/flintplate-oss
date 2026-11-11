"""AI trace log for observability

Revision ID: 014
Revises: 013
Create Date: 2026-03-23
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

from alembic import op

revision = "014"
down_revision = "013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ai_traces",
        sa.Column(
            "id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")
        ),
        sa.Column(
            "user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "trace_type", sa.String(80), nullable=False
        ),  # cv_parse / cover_letter / job_match / interview_prep / gap_analysis
        sa.Column("model", sa.String(80), nullable=True),  # gpt-4o-mini etc.
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("prompt_tokens", sa.Integer(), nullable=True),
        sa.Column("completion_tokens", sa.Integer(), nullable=True),
        sa.Column("total_tokens", sa.Integer(), nullable=True),
        sa.Column("success", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("error_msg", sa.Text(), nullable=True),
        sa.Column("meta", JSONB(), nullable=True),  # arbitrary context
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_ai_traces_user_id", "ai_traces", ["user_id"])
    op.create_index("ix_ai_traces_trace_type", "ai_traces", ["trace_type"])
    op.create_index("ix_ai_traces_created_at", "ai_traces", ["created_at"])


def downgrade() -> None:
    op.drop_table("ai_traces")
