"""037 work_assignments_slots – Add slots + tenant_id to work_assignments

Revision ID: 037
Revises: 036
Create Date: 2026-03-28
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "037"
down_revision = "036"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "work_assignments", sa.Column("slots", sa.Integer(), nullable=False, server_default="1")
    )


def downgrade() -> None:
    op.drop_column("work_assignments", "slots")
