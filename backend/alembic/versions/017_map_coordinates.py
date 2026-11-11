"""Map View – lat/lng coordinates for assignments and pool workers

Revision ID: 017
Revises: 016
Create Date: 2026-03-24
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "017"
down_revision = "016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("work_assignments", sa.Column("lat", sa.Float(), nullable=True))
    op.add_column("work_assignments", sa.Column("lng", sa.Float(), nullable=True))
    op.add_column("temp_worker_availability", sa.Column("lat", sa.Float(), nullable=True))
    op.add_column("temp_worker_availability", sa.Column("lng", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("temp_worker_availability", "lng")
    op.drop_column("temp_worker_availability", "lat")
    op.drop_column("work_assignments", "lng")
    op.drop_column("work_assignments", "lat")
