"""Floors, activities, mobile guests and auditable benefits."""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

from alembic import op

revision = "055"
down_revision = "054"
branch_labels = None
depends_on = None


def uid(
    name: str, target: str | None = None, nullable: bool = False, unique: bool = False
) -> sa.Column:
    return sa.Column(
        name,
        pg.UUID(as_uuid=True),
        *([sa.ForeignKey(target)] if target else []),
        nullable=nullable,
        unique=unique,
    )


def string(name: str, length: int) -> sa.Column:
    return sa.Column(name, sa.String(length), nullable=False)


def integer(name: str) -> sa.Column:
    return sa.Column(name, sa.Integer(), nullable=False)


def dt(name: str, nullable: bool = False) -> sa.Column:
    return sa.Column(name, sa.DateTime(timezone=True), nullable=nullable)


def table(name: str, *columns: sa.SchemaItem) -> None:
    op.create_table(
        name,
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        dt("created_at"),
        dt("updated_at"),
        *columns,
    )
    op.create_index(f"ix_{name}_id", name, ["id"])
    for column in ("created_at", "updated_at"):
        op.alter_column(name, column, server_default=sa.func.now())


def upgrade() -> None:
    op.add_column(
        "fp_venues",
        sa.Column("guest_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    table(
        "fp_floors",
        uid("venue_id", "fp_venues.id"),
        string("name", 80),
        integer("level"),
        sa.UniqueConstraint("venue_id", "name", name="uq_fp_floor_name"),
    )
    table(
        "fp_rooms",
        uid("venue_id", "fp_venues.id"),
        uid("floor_id", "fp_floors.id"),
        string("name", 80),
        sa.UniqueConstraint("floor_id", "name", name="uq_fp_room_name"),
    )
    table(
        "fp_guest_accounts",
        uid("venue_id", "fp_venues.id"),
        uid("user_id", "users.id"),
        integer("points"),
        sa.UniqueConstraint("venue_id", "user_id", name="uq_fp_guest_account"),
        sa.CheckConstraint("points >= 0", name="ck_fp_guest_points"),
    )
    op.add_column("fp_tables", uid("room_id", "fp_rooms.id", True))
    for name, kind, default in (
        ("kind", sa.String(20), "table"),
        ("hourly_rate_cents", sa.Integer(), "0"),
        ("billing_minutes", sa.Integer(), "15"),
        ("tax_rate_bps", sa.Integer(), "1900"),
    ):
        op.add_column("fp_tables", sa.Column(name, kind, nullable=False, server_default=default))
    op.add_column("fp_orders", uid("customer_id", "fp_guest_accounts.id", True))
    op.add_column("fp_reservations", uid("customer_id", "fp_guest_accounts.id", True))
    for name, kind, default in (
        ("fulfillment", sa.String(20), "dine_in"),
        ("subtotal_cents", sa.Integer(), "0"),
        ("discount_cents", sa.Integer(), "0"),
        ("discount_reason", sa.String(160), ""),
        ("voucher_cents", sa.Integer(), "0"),
    ):
        op.add_column("fp_orders", sa.Column(name, kind, nullable=False, server_default=default))
    op.execute("UPDATE fp_orders SET subtotal_cents = total_cents")
    table(
        "fp_usage_sessions",
        uid("venue_id", "fp_venues.id"),
        uid("table_id", "fp_tables.id"),
        dt("starts_at"),
        dt("ends_at", True),
        dt("reserved_until"),
        integer("hourly_rate_cents"),
        integer("billing_minutes"),
        integer("tax_rate_bps"),
        uid("request_key", unique=True),
        string("request_hash", 64),
        uid("order_id", "fp_orders.id", True),
        string("guest_name", 120),
    )
    op.create_index(
        "uq_fp_active_usage",
        "fp_usage_sessions",
        ["table_id"],
        unique=True,
        postgresql_where=sa.text("ends_at IS NULL"),
    )
    table(
        "fp_loyalty_entries",
        uid("account_id", "fp_guest_accounts.id"),
        uid("order_id", "fp_orders.id", unique=True),
        integer("points"),
        string("reason", 120),
    )
    table(
        "fp_vouchers",
        uid("venue_id", "fp_venues.id"),
        sa.Column("code_digest", sa.String(64), nullable=False, unique=True),
        string("label", 80),
        integer("initial_cents"),
        integer("balance_cents"),
        dt("expires_at"),
        string("reference", 160),
        uid("request_key", unique=True),
        sa.CheckConstraint("balance_cents >= 0", name="ck_fp_voucher_balance"),
    )
    table(
        "fp_voucher_entries",
        uid("venue_id", "fp_venues.id"),
        uid("voucher_id", "fp_vouchers.id"),
        uid("order_id", "fp_orders.id", True),
        integer("amount_cents"),
        uid("request_key"),
        string("request_hash", 64),
        string("kind", 20),
        uid("actor_id", "users.id"),
        sa.UniqueConstraint("venue_id", "request_key", name="uq_fp_voucher_request"),
    )
    table(
        "fp_support_tickets",
        uid("venue_id", "fp_venues.id"),
        uid("actor_id", "users.id"),
        string("category", 30),
        string("subject", 160),
        string("description", 3000),
        string("status", 20),
    )
    for name, columns in {
        "fp_floors": ["venue_id"],
        "fp_rooms": ["venue_id", "floor_id"],
        "fp_guest_accounts": ["venue_id", "user_id"],
        "fp_usage_sessions": ["venue_id", "table_id"],
        "fp_loyalty_entries": ["account_id"],
        "fp_vouchers": ["venue_id"],
        "fp_voucher_entries": ["venue_id", "voucher_id"],
        "fp_support_tickets": ["venue_id"],
    }.items():
        for column in columns:
            op.create_index(f"ix_{name}_{column}", name, [column])


def downgrade() -> None:
    for name in (
        "fp_support_tickets",
        "fp_voucher_entries",
        "fp_vouchers",
        "fp_loyalty_entries",
        "fp_usage_sessions",
    ):
        op.drop_table(name)
    for name in (
        "fulfillment",
        "subtotal_cents",
        "discount_cents",
        "discount_reason",
        "voucher_cents",
        "customer_id",
    ):
        op.drop_column("fp_orders", name)
    op.drop_column("fp_reservations", "customer_id")
    for name in ("room_id", "kind", "hourly_rate_cents", "billing_minutes", "tax_rate_bps"):
        op.drop_column("fp_tables", name)
    for name in ("fp_guest_accounts", "fp_rooms", "fp_floors"):
        op.drop_table(name)
    op.drop_column("fp_venues", "guest_enabled")
