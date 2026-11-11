"""022 stripe billing – Stripe customer/subscription IDs on customers table

Revision ID: 022
Revises: 021
Create Date: 2026-03-26
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "022"
down_revision = "021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "customers",
        sa.Column("stripe_customer_id", sa.String(100), nullable=True, unique=True),
    )
    op.add_column(
        "customers",
        sa.Column("stripe_subscription_id", sa.String(100), nullable=True, unique=True),
    )
    op.create_index(
        "ix_customers_stripe_customer_id", "customers", ["stripe_customer_id"], unique=True
    )


def downgrade() -> None:
    op.drop_index("ix_customers_stripe_customer_id", table_name="customers")
    op.drop_column("customers", "stripe_subscription_id")
    op.drop_column("customers", "stripe_customer_id")
