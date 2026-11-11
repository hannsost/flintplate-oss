"""Bind financial approval to the reviewed permission version."""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "050"
down_revision = "049"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "finance_invoices", sa.Column("approved_grant_version", sa.Integer(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("finance_invoices", "approved_grant_version")
