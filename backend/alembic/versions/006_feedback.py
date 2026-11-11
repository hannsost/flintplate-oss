"""Feedback table + category enum

Revision ID: 006_feedback
Revises: 005_cover_letters
Create Date: 2026-03-22
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "006_feedback"
down_revision: str | None = "005_cover_letters"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE TYPE feedback_category AS ENUM ('bug', 'feature', 'general', 'ux')")
    op.execute("""
        CREATE TABLE feedback (
            id          UUID PRIMARY KEY NOT NULL DEFAULT gen_random_uuid(),
            user_id     UUID REFERENCES users(id) ON DELETE SET NULL,
            email       VARCHAR(255),
            category    feedback_category NOT NULL DEFAULT 'general',
            message     TEXT NOT NULL,
            page_url    VARCHAR(500),
            created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX feedback_user_id_idx ON feedback(user_id)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS feedback")
    op.execute("DROP TYPE IF EXISTS feedback_category")
