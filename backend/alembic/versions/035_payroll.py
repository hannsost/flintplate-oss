"""035 payroll – Worker pay stubs / Lohnabrechnung

Revision ID: 035
Revises: 034
Create Date: 2026-03-27
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op

revision = "035"
down_revision = "034"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "pay_stubs",
        sa.Column(
            "id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")
        ),
        sa.Column(
            "tenant_id",
            UUID(as_uuid=True),
            sa.ForeignKey("customers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "worker_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "created_by",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        # Period
        sa.Column("period_year", sa.Integer, nullable=False),
        sa.Column("period_month", sa.Integer, nullable=False),  # 1-12
        # Amounts (in EUR cents to avoid float precision)
        sa.Column("gross_cents", sa.Integer, nullable=False, server_default="0"),
        sa.Column("net_cents", sa.Integer, nullable=False, server_default="0"),
        sa.Column("tax_cents", sa.Integer, nullable=False, server_default="0"),
        sa.Column("social_security_cents", sa.Integer, nullable=False, server_default="0"),
        # Hours
        sa.Column("hours_worked", sa.Numeric(8, 2), nullable=True),
        sa.Column("overtime_hours", sa.Numeric(8, 2), nullable=True),
        # Document
        sa.Column("document_url", sa.String(1000), nullable=True),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column(
            "status", sa.String(20), nullable=False, server_default="draft"
        ),  # draft|published
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_pay_stubs_worker_id", "pay_stubs", ["worker_id"])
    op.create_index(
        "ix_pay_stubs_tenant_period", "pay_stubs", ["tenant_id", "period_year", "period_month"]
    )
    op.create_unique_constraint(
        "uq_pay_stubs_worker_period", "pay_stubs", ["worker_id", "period_year", "period_month"]
    )


def downgrade() -> None:
    op.drop_table("pay_stubs")
