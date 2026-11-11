"""Planning snapshots and bilateral company collaboration.

Revision ID: 048
Revises: 047
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

from alembic import op

revision = "048"
down_revision = "047"
branch_labels = None
depends_on = None


def base_columns() -> list[sa.Column]:
    return [
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    ]


def upgrade() -> None:
    op.create_table(
        "mobility_plans",
        *base_columns(),
        sa.Column(
            "tenant_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("customers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "created_by", pg.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL")
        ),
        sa.Column("title", sa.String(120), nullable=False),
        sa.Column("inputs", pg.JSONB(), nullable=False),
        sa.Column("result", pg.JSONB(), nullable=False),
    )
    op.create_index("ix_mobility_plans_tenant_id", "mobility_plans", ["tenant_id"])
    op.create_table(
        "partnerships",
        *base_columns(),
        sa.Column(
            "initiator_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("customers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "recipient_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("customers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("pair_key", sa.String(73), nullable=False),
        sa.Column("purpose", sa.String(500), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
    )
    for field in ("initiator_id", "recipient_id"):
        op.create_index(f"ix_partnerships_{field}", "partnerships", [field])
    op.create_index(
        "uq_partnership_live_pair",
        "partnerships",
        ["pair_key"],
        unique=True,
        postgresql_where=sa.text("status IN ('pending', 'active')"),
    )
    op.create_table(
        "shared_demands",
        *base_columns(),
        sa.Column(
            "partnership_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("partnerships.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "owner_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("customers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.String(120), nullable=False),
        sa.Column("location", sa.String(120), nullable=False),
        sa.Column("required_skills", pg.ARRAY(sa.String(100)), nullable=False),
        sa.Column("starts_on", sa.Date(), nullable=False),
        sa.Column("headcount", sa.Integer(), nullable=False),
        sa.Column("offered_count", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
    )
    op.create_index("ix_shared_demands_partnership_id", "shared_demands", ["partnership_id"])
    op.create_table(
        "partner_events",
        *base_columns(),
        sa.Column(
            "partnership_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("partnerships.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "actor_id", pg.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL")
        ),
        sa.Column("action", sa.String(40), nullable=False),
        sa.Column("detail", sa.String(300), nullable=False),
    )
    op.create_index("ix_partner_events_partnership_id", "partner_events", ["partnership_id"])


def downgrade() -> None:
    for table in ("partner_events", "shared_demands", "partnerships", "mobility_plans"):
        op.drop_table(table)
