"""Tenant-managed branding with versioned updates.

Revision ID: 046
Revises: 045
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "046"
down_revision = "045"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("customers", sa.Column("brand_name", sa.String(80), nullable=True))
    op.add_column(
        "customers", sa.Column("branding_version", sa.Integer(), nullable=False, server_default="1")
    )


def downgrade() -> None:
    op.drop_column("customers", "branding_version")
    op.drop_column("customers", "brand_name")
