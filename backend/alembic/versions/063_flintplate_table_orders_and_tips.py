"""Guest orders to a table, tips on an order, and recorded tip distributions."""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

from alembic import op

revision = "063"
down_revision = "062"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "fp_venues",
        sa.Column("guest_table_orders", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "fp_venues",
        sa.Column("guest_open_tables", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "fp_venues",
        sa.Column("tip_mode", sa.String(20), nullable=False, server_default="pool_hours"),
    )
    op.add_column(
        "fp_venues", sa.Column("tip_kitchen_bps", sa.Integer(), nullable=False, server_default="0")
    )
    op.create_check_constraint(
        "ck_fp_venue_tips",
        "fp_venues",
        "tip_mode IN ('pool_hours','direct') AND tip_kitchen_bps BETWEEN 0 AND 10000",
    )
    op.create_table(
        "fp_tip_runs",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("venue_id", pg.UUID(as_uuid=True), sa.ForeignKey("fp_venues.id"), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("mode", sa.String(20), nullable=False),
        sa.Column("kitchen_bps", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_cents", sa.Integer(), nullable=False),
        sa.Column("orders", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("actor_id", pg.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("note", sa.String(300), nullable=False, server_default=""),
        sa.UniqueConstraint("venue_id", "period_start", "period_end", name="uq_fp_tip_period"),
        sa.CheckConstraint("period_end >= period_start", name="ck_fp_tip_period"),
        sa.CheckConstraint("total_cents >= 0", name="ck_fp_tip_total"),
    )
    op.create_index("ix_fp_tip_runs_venue_id", "fp_tip_runs", ["venue_id"])
    op.create_table(
        "fp_tip_shares",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("run_id", pg.UUID(as_uuid=True), sa.ForeignKey("fp_tip_runs.id"), nullable=False),
        sa.Column("worker_id", pg.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("pool", sa.String(20), nullable=False),
        sa.Column("minutes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("share_cents", sa.Integer(), nullable=False),
        sa.Column("reason", sa.String(200), nullable=False, server_default=""),
        sa.UniqueConstraint("run_id", "worker_id", name="uq_fp_tip_share"),
        sa.CheckConstraint("share_cents >= 0", name="ck_fp_tip_share"),
    )
    op.create_index("ix_fp_tip_shares_run_id", "fp_tip_shares", ["run_id"])
    op.add_column(
        "fp_orders", sa.Column("tip_cents", sa.Integer(), nullable=False, server_default="0")
    )
    op.add_column(
        "fp_orders",
        sa.Column(
            "tip_recipient_id", pg.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True
        ),
    )
    # Set once a distribution is confirmed, so the same tip is never shared twice.
    op.add_column(
        "fp_orders",
        sa.Column(
            "tip_run_id", pg.UUID(as_uuid=True), sa.ForeignKey("fp_tip_runs.id"), nullable=True
        ),
    )
    op.create_check_constraint("ck_fp_order_tip", "fp_orders", "tip_cents >= 0")


def downgrade() -> None:
    op.drop_constraint("ck_fp_order_tip", "fp_orders", type_="check")
    op.drop_column("fp_orders", "tip_run_id")
    op.drop_column("fp_orders", "tip_recipient_id")
    op.drop_column("fp_orders", "tip_cents")
    op.drop_index("ix_fp_tip_shares_run_id", table_name="fp_tip_shares")
    op.drop_table("fp_tip_shares")
    op.drop_index("ix_fp_tip_runs_venue_id", table_name="fp_tip_runs")
    op.drop_table("fp_tip_runs")
    op.drop_constraint("ck_fp_venue_tips", "fp_venues", type_="check")
    op.drop_column("fp_venues", "tip_kitchen_bps")
    op.drop_column("fp_venues", "tip_mode")
    op.drop_column("fp_venues", "guest_open_tables")
    op.drop_column("fp_venues", "guest_table_orders")
