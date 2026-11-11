"""024 custom_domain per tenant

Revision ID: 024
Revises: 023
Create Date: 2026-03-26
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "024"
down_revision = "023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "customers",
        sa.Column("custom_domain", sa.String(255), nullable=True),
    )
    op.add_column(
        "customers",
        sa.Column("primary_color", sa.String(7), nullable=True),  # hex, e.g. "#2563eb"
    )
    op.add_column(
        "customers",
        sa.Column("logo_url", sa.String(500), nullable=True),
    )
    op.create_index(
        "ix_customers_custom_domain",
        "customers",
        ["custom_domain"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_customers_custom_domain", table_name="customers")
    op.drop_column("customers", "logo_url")
    op.drop_column("customers", "primary_color")
    op.drop_column("customers", "custom_domain")
