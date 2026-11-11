"""Applications + history + status enum

Revision ID: 004_applications
Revises: 003_jobs
Create Date: 2026-03-22
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "004_applications"
down_revision: str | None = "003_jobs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

STATUSES = ["research", "applied", "screening", "interview", "offer", "rejected", "withdrawn"]


def upgrade() -> None:
    op.execute(
        "CREATE TYPE application_status AS ENUM ('research', 'applied', 'screening', 'interview', 'offer', 'rejected', 'withdrawn')"
    )

    op.execute("""
        CREATE TABLE applications (
            id          UUID PRIMARY KEY NOT NULL DEFAULT gen_random_uuid(),
            user_id     UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            job_id      UUID REFERENCES job_postings(id) ON DELETE SET NULL,
            company     VARCHAR(255) NOT NULL,
            position    VARCHAR(500) NOT NULL,
            job_url     VARCHAR(1000),
            notes       TEXT,
            status      application_status NOT NULL DEFAULT 'research',
            applied_at  TIMESTAMPTZ,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX applications_user_id_idx ON applications(user_id)")

    op.execute("""
        CREATE TABLE application_history (
            id              UUID PRIMARY KEY NOT NULL DEFAULT gen_random_uuid(),
            application_id  UUID NOT NULL REFERENCES applications(id) ON DELETE CASCADE,
            from_status     application_status,
            to_status       application_status NOT NULL,
            note            TEXT,
            changed_at      TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX application_history_app_idx ON application_history(application_id)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS application_history")
    op.execute("DROP TABLE IF EXISTS applications")
    op.execute("DROP TYPE IF EXISTS application_status")
