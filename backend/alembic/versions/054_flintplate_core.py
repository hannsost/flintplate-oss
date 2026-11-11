"""FlintPlate tenant-scoped hospitality aggregates and integration journal."""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

from alembic import op

revision = "054"
down_revision = "053"
branch_labels = None
depends_on = None


def uid(
    name: str, target: str | None = None, nullable: bool = False, unique: bool = False
) -> sa.Column:
    args = [sa.ForeignKey(target)] if target else []
    return sa.Column(name, pg.UUID(as_uuid=True), *args, nullable=nullable, unique=unique)


def s(name: str, length: int, nullable: bool = False) -> sa.Column:
    return sa.Column(name, sa.String(length), nullable=nullable)


def i(name: str, nullable: bool = False) -> sa.Column:
    return sa.Column(name, sa.Integer(), nullable=nullable)


def dt(name: str, nullable: bool = False) -> sa.Column:
    return sa.Column(name, sa.DateTime(timezone=True), nullable=nullable)


def table(name: str, *columns: sa.SchemaItem) -> None:
    op.create_table(
        name,
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        *columns,
    )
    op.create_index(f"ix_{name}_id", name, ["id"])


def index(name: str, *columns: str) -> None:
    for column in columns:
        op.create_index(f"ix_{name}_{column}", name, [column])


def upgrade() -> None:
    table(
        "fp_venues",
        uid("tenant_id", "customers.id"),
        s("name", 120),
        s("timezone", 80),
        s("currency", 3),
    )
    index("fp_venues", "tenant_id")
    table(
        "fp_memberships",
        uid("venue_id", "fp_venues.id"),
        uid("user_id", "users.id"),
        s("role", 20),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.UniqueConstraint("venue_id", "user_id", name="uq_fp_member"),
    )
    index("fp_memberships", "venue_id", "user_id")
    table(
        "fp_tables",
        uid("venue_id", "fp_venues.id"),
        s("name", 40),
        s("area", 80),
        i("seats"),
        i("x"),
        i("y"),
        i("version"),
        sa.UniqueConstraint("venue_id", "name", name="uq_fp_table_name"),
        sa.CheckConstraint("seats > 0", name="ck_fp_table_seats"),
    )
    index("fp_tables", "venue_id")
    table(
        "fp_menu_items",
        uid("venue_id", "fp_venues.id"),
        s("sku", 60),
        sa.Column("draft", pg.JSONB(), nullable=False),
        sa.Column("published", pg.JSONB()),
        i("version"),
        i("published_version", True),
        sa.UniqueConstraint("venue_id", "sku", name="uq_fp_menu_sku"),
    )
    index("fp_menu_items", "venue_id")
    table(
        "fp_devices",
        uid("venue_id", "fp_venues.id"),
        s("name", 120),
        s("kind", 30),
        sa.Column("token_digest", sa.String(64), nullable=False, unique=True),
        sa.Column("scopes", pg.JSONB(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        dt("expires_at"),
        dt("last_seen_at", True),
    )
    index("fp_devices", "venue_id")
    table(
        "fp_orders",
        uid("venue_id", "fp_venues.id"),
        uid("table_id", "fp_tables.id", True),
        uid("actor_id", "users.id", True),
        uid("device_id", "fp_devices.id", True),
        uid("request_key"),
        s("request_hash", 64),
        s("number", 20),
        s("status", 20),
        sa.Column("lines", pg.JSONB(), nullable=False),
        i("total_cents"),
        s("currency", 3),
        i("guests"),
        s("note", 500),
        i("version"),
        sa.Column("pos_requested", sa.Boolean(), nullable=False),
        s("payment_reference", 160, True),
        dt("paid_at", True),
        sa.UniqueConstraint("venue_id", "request_key", name="uq_fp_order_request"),
        sa.CheckConstraint("total_cents >= 0", name="ck_fp_order_total"),
    )
    index("fp_orders", "venue_id", "table_id", "status")
    table(
        "fp_reservations",
        uid("venue_id", "fp_venues.id"),
        uid("table_id", "fp_tables.id"),
        s("guest_name", 120),
        i("guests"),
        dt("starts_at"),
        dt("ends_at"),
        s("status", 20),
        i("version"),
        sa.CheckConstraint("ends_at > starts_at", name="ck_fp_reservation_time"),
    )
    index("fp_reservations", "venue_id", "table_id", "starts_at")
    table(
        "fp_shifts",
        uid("venue_id", "fp_venues.id"),
        uid("worker_id", "users.id"),
        uid("assignment_id", "worker_assignments.id", unique=True),
        dt("starts_at"),
        dt("ends_at"),
        i("break_minutes"),
        s("station", 80),
        s("status", 20),
        i("version"),
        sa.CheckConstraint("ends_at > starts_at", name="ck_fp_shift_time"),
    )
    index("fp_shifts", "venue_id", "worker_id", "starts_at")
    table(
        "fp_events",
        sa.Column("sequence", sa.BigInteger(), sa.Identity(), unique=True, nullable=False),
        uid("venue_id", "fp_venues.id"),
        s("kind", 80),
        uid("aggregate_id"),
        uid("actor_id", "users.id", True),
        uid("device_id", "fp_devices.id", True),
        sa.Column("payload", pg.JSONB(), nullable=False),
    )
    index("fp_events", "venue_id")
    table(
        "fp_device_receipts",
        uid("device_id", "fp_devices.id"),
        uid("request_key"),
        s("request_hash", 64),
        uid("order_id", "fp_orders.id"),
        sa.UniqueConstraint("device_id", "request_key", name="uq_fp_receipt_request"),
    )
    index("fp_device_receipts", "device_id")
    table(
        "fp_fireflint_links",
        uid("venue_id", "fp_venues.id", unique=True),
        uid("org_id"),
        uid("content_id"),
        s("type_key", 80),
        i("expected_revision"),
        i("version"),
        s("status", 30),
        dt("last_synced_at", True),
        s("last_error", 300, True),
    )


def downgrade() -> None:
    for name in (
        "fp_fireflint_links",
        "fp_device_receipts",
        "fp_events",
        "fp_shifts",
        "fp_reservations",
        "fp_orders",
        "fp_devices",
        "fp_menu_items",
        "fp_tables",
        "fp_memberships",
        "fp_venues",
    ):
        op.drop_table(name)
