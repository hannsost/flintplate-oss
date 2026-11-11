"""Stable line identity, independent fulfillment/payment and repeatable table operations."""

from __future__ import annotations

import uuid

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

from alembic import op

revision = "069"
down_revision = "068"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "fp_orders",
        sa.Column("fulfillment_status", sa.String(20), nullable=False, server_default="sent"),
    )
    op.add_column(
        "fp_orders",
        sa.Column("payment_status", sa.String(20), nullable=False, server_default="open"),
    )
    op.execute(
        "UPDATE fp_orders SET fulfillment_status = CASE WHEN status = 'settled' THEN 'served' ELSE status END, payment_status = CASE WHEN paid_at IS NOT NULL THEN 'paid' WHEN pos_requested THEN 'requested' ELSE 'open' END"
    )
    table = sa.table(
        "fp_orders",
        sa.column("id", pg.UUID(as_uuid=True)),
        sa.column("lines", pg.JSONB()),
        sa.column("fulfillment_status", sa.String()),
    )
    connection = op.get_bind()
    for row in connection.execute(
        sa.select(table.c.id, table.c.lines, table.c.fulfillment_status)
    ).mappings():
        lines = [
            {
                **line,
                "line_id": line.get("line_id") or str(uuid.uuid5(row["id"], f"line:{index}")),
                "course": line.get("course", 1),
                "preparation_status": line.get("preparation_status", row["fulfillment_status"]),
            }
            for index, line in enumerate(row["lines"])
        ]
        connection.execute(table.update().where(table.c.id == row["id"]).values(lines=lines))
    op.create_table(
        "fp_order_operations",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("venue_id", pg.UUID(as_uuid=True), sa.ForeignKey("fp_venues.id"), nullable=False),
        sa.Column("order_id", pg.UUID(as_uuid=True), sa.ForeignKey("fp_orders.id"), nullable=False),
        sa.Column("request_key", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("kind", sa.String(64), nullable=False),
        sa.UniqueConstraint("venue_id", "request_key", name="uq_fp_order_operation"),
    )
    op.create_index("ix_fp_order_operations_venue_id", "fp_order_operations", ["venue_id"])
    op.create_index("ix_fp_order_operations_order_id", "fp_order_operations", ["order_id"])


def downgrade() -> None:
    op.drop_table("fp_order_operations")
    op.drop_column("fp_orders", "payment_status")
    op.drop_column("fp_orders", "fulfillment_status")
    # Extra line JSON keys are additive; preserving them keeps historic line IDs stable.
