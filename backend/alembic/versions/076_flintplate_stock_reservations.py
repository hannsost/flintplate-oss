"""Exact lot/location stock holds, expiry and append-only release/consumption evidence."""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

from alembic import op

revision = "076"
down_revision = "075"
branch_labels = None
depends_on = None


def base() -> list[sa.Column[object]]:
    return [
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("venue_id", pg.UUID(as_uuid=True), sa.ForeignKey("fp_venues.id"), nullable=False),
        sa.Column("request_key", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("reason", sa.String(300), nullable=False),
        sa.Column("actor_id", pg.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "fp_stock_reservations",
        *base(),
        sa.Column("lot_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("location_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("quantity", sa.Numeric(18, 6), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("venue_id", "id", name="uq_fp_stock_reservation_scope"),
        sa.UniqueConstraint("venue_id", "request_key", name="uq_fp_stock_reservation_request"),
        sa.CheckConstraint("quantity > 0", name="ck_fp_stock_reservation_quantity"),
        sa.CheckConstraint("expires_at > created_at", name="ck_fp_stock_reservation_expiry"),
        sa.ForeignKeyConstraint(
            ["venue_id", "lot_id"],
            ["fp_stock_lots.venue_id", "fp_stock_lots.id"],
            name="fk_fp_stock_reservation_lot",
        ),
        sa.ForeignKeyConstraint(
            ["venue_id", "location_id"],
            ["fp_stock_locations.venue_id", "fp_stock_locations.id"],
            name="fk_fp_stock_reservation_location",
        ),
    )
    op.create_table(
        "fp_stock_reservation_closures",
        *base(),
        sa.Column("reservation_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("kind", sa.String(10), nullable=False),
        sa.Column("stock_operation_id", pg.UUID(as_uuid=True), nullable=True),
        sa.UniqueConstraint("venue_id", "request_key", name="uq_fp_reservation_close_request"),
        sa.UniqueConstraint("reservation_id", name="uq_fp_reservation_close_once"),
        sa.CheckConstraint(
            "(kind = 'release' AND stock_operation_id IS NULL) OR (kind = 'consume' AND stock_operation_id IS NOT NULL)",
            name="ck_fp_reservation_close_kind",
        ),
        sa.ForeignKeyConstraint(
            ["venue_id", "reservation_id"],
            ["fp_stock_reservations.venue_id", "fp_stock_reservations.id"],
            name="fk_fp_reservation_close_hold",
        ),
        sa.ForeignKeyConstraint(
            ["venue_id", "stock_operation_id"],
            ["fp_stock_operations.venue_id", "fp_stock_operations.id"],
            name="fk_fp_reservation_close_stock",
        ),
    )
    op.execute(
        """CREATE FUNCTION fp_stock_reservation_immutable() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'Stock reservation evidence is append-only'; END; $$"""
    )
    for table in ("fp_stock_reservations", "fp_stock_reservation_closures"):
        op.create_index(f"ix_{table}_venue_id", table, ["venue_id"])
        op.execute(
            f"CREATE TRIGGER {table}_immutable BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION fp_stock_reservation_immutable()"
        )
        op.execute(
            f"CREATE TRIGGER {table}_no_truncate BEFORE TRUNCATE ON {table} FOR EACH STATEMENT EXECUTE FUNCTION fp_stock_reservation_immutable()"
        )


def downgrade() -> None:
    op.drop_table("fp_stock_reservation_closures")
    op.drop_table("fp_stock_reservations")
    op.execute("DROP FUNCTION fp_stock_reservation_immutable()")
