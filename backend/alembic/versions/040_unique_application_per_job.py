"""Prevent duplicate candidate applications for the same job."""

from __future__ import annotations

from alembic import op

revision = "040"
down_revision = "039"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_unique_constraint("uq_applications_user_job", "applications", ["user_id", "job_id"])


def downgrade() -> None:
    op.drop_constraint("uq_applications_user_job", "applications", type_="unique")
