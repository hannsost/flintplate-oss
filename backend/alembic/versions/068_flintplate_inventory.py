"""Exact physical stock by owner, lot and location with an immutable posting ledger."""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

from alembic import op

revision = "068"
down_revision = "067"
branch_labels = None
depends_on = None


def base_columns() -> list[sa.Column[object]]:
    return [
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("venue_id", pg.UUID(as_uuid=True), sa.ForeignKey("fp_venues.id"), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "fp_stock_items",
        *base_columns(),
        sa.Column("sku", sa.String(60), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("unit", sa.String(10), nullable=False),
        sa.Column("requires_expiry", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("minimum_quantity", sa.Numeric(18, 6), nullable=False, server_default="0"),
        sa.UniqueConstraint("venue_id", "id", name="uq_fp_stock_item_scope"),
        sa.UniqueConstraint("venue_id", "sku", name="uq_fp_stock_item_sku"),
        sa.CheckConstraint("unit IN ('kg', 'l', 'piece')", name="ck_fp_stock_item_unit"),
        sa.CheckConstraint("minimum_quantity >= 0", name="ck_fp_stock_item_minimum"),
    )
    op.create_table(
        "fp_stock_owners",
        *base_columns(),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("kind", sa.String(12), nullable=False),
        sa.Column("reference", sa.String(120), nullable=False, server_default=""),
        sa.UniqueConstraint("venue_id", "id", name="uq_fp_stock_owner_scope"),
        sa.UniqueConstraint("venue_id", "name", name="uq_fp_stock_owner_name"),
        sa.CheckConstraint("kind IN ('own', 'partner')", name="ck_fp_stock_owner_kind"),
    )
    op.create_table(
        "fp_stock_locations",
        *base_columns(),
        sa.Column("name", sa.String(120), nullable=False),
        sa.UniqueConstraint("venue_id", "id", name="uq_fp_stock_location_scope"),
        sa.UniqueConstraint("venue_id", "name", name="uq_fp_stock_location_name"),
    )
    op.create_table(
        "fp_stock_lots",
        *base_columns(),
        sa.Column("item_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("owner_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("code", sa.String(100), nullable=False),
        sa.Column("expires_on", sa.Date(), nullable=True),
        sa.Column("blocked", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.UniqueConstraint("venue_id", "id", name="uq_fp_stock_lot_scope"),
        sa.CheckConstraint("version > 0", name="ck_fp_stock_lot_version"),
        sa.UniqueConstraint("venue_id", "item_id", "owner_id", "code", name="uq_fp_stock_lot_code"),
        sa.ForeignKeyConstraint(
            ["venue_id", "item_id"],
            ["fp_stock_items.venue_id", "fp_stock_items.id"],
            name="fk_fp_stock_lot_item",
        ),
        sa.ForeignKeyConstraint(
            ["venue_id", "owner_id"],
            ["fp_stock_owners.venue_id", "fp_stock_owners.id"],
            name="fk_fp_stock_lot_owner",
        ),
    )
    op.create_table(
        "fp_stock_operations",
        *base_columns(),
        sa.Column("sequence", sa.BigInteger(), sa.Identity(), nullable=False, unique=True),
        sa.Column("request_key", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("kind", sa.String(12), nullable=False),
        sa.Column("actor_id", pg.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("reason", sa.String(300), nullable=False),
        sa.Column("details", pg.JSONB(), nullable=False),
        sa.UniqueConstraint("venue_id", "id", name="uq_fp_stock_operation_scope"),
        sa.UniqueConstraint("venue_id", "request_key", name="uq_fp_stock_operation_request"),
        sa.CheckConstraint(
            "kind IN ('receipt', 'transfer', 'waste', 'count', 'quarantine', 'production', 'consume')",
            name="ck_fp_stock_operation_kind",
        ),
    )
    op.create_table(
        "fp_stock_movements",
        *base_columns(),
        sa.Column("operation_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("lot_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("location_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("quantity", sa.Numeric(18, 6), nullable=False),
        sa.UniqueConstraint(
            "operation_id", "lot_id", "location_id", name="uq_fp_stock_movement_location"
        ),
        sa.CheckConstraint("quantity <> 0", name="ck_fp_stock_movement_quantity"),
        sa.ForeignKeyConstraint(
            ["venue_id", "operation_id"],
            ["fp_stock_operations.venue_id", "fp_stock_operations.id"],
            name="fk_fp_stock_movement_operation",
        ),
        sa.ForeignKeyConstraint(
            ["venue_id", "lot_id"],
            ["fp_stock_lots.venue_id", "fp_stock_lots.id"],
            name="fk_fp_stock_movement_lot",
        ),
        sa.ForeignKeyConstraint(
            ["venue_id", "location_id"],
            ["fp_stock_locations.venue_id", "fp_stock_locations.id"],
            name="fk_fp_stock_movement_location",
        ),
    )
    for table in ("items", "owners", "locations", "lots", "operations", "movements"):
        name = f"fp_stock_{table}"
        op.create_index(f"ix_{name}_venue_id", name, ["venue_id"])
    op.create_index("ix_fp_stock_movements_operation_id", "fp_stock_movements", ["operation_id"])
    op.create_index("ix_fp_stock_movements_lot_id", "fp_stock_movements", ["lot_id"])
    op.execute("""CREATE FUNCTION fp_reject_stock_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          RAISE EXCEPTION 'FlintPlate stock ledger is append-only; post a compensating operation';
        END $$""")
    for table in ("lots", "operations", "movements"):
        name = f"fp_stock_{table}"
        change = "DELETE" if table == "lots" else "UPDATE OR DELETE"
        op.execute(
            f"CREATE TRIGGER {name}_immutable BEFORE {change} ON {name} "
            "FOR EACH ROW EXECUTE FUNCTION fp_reject_stock_mutation()"
        )
        op.execute(
            f"CREATE TRIGGER {name}_no_truncate BEFORE TRUNCATE ON {name} "
            "FOR EACH STATEMENT EXECUTE FUNCTION fp_reject_stock_mutation()"
        )
    op.execute("""CREATE FUNCTION fp_guard_stock_lot_update() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF (to_jsonb(NEW) - 'blocked' - 'version') IS DISTINCT FROM
             (to_jsonb(OLD) - 'blocked' - 'version') OR NEW.version <> OLD.version + 1 THEN
            RAISE EXCEPTION 'FlintPlate lot identity is immutable; only versioned quarantine changes are allowed';
          END IF;
          RETURN NEW;
        END $$""")
    op.execute(
        "CREATE TRIGGER fp_stock_lots_guard BEFORE UPDATE ON fp_stock_lots "
        "FOR EACH ROW EXECUTE FUNCTION fp_guard_stock_lot_update()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER fp_stock_lots_guard ON fp_stock_lots")
    op.execute("DROP FUNCTION fp_guard_stock_lot_update()")
    for table in ("movements", "operations", "lots"):
        name = f"fp_stock_{table}"
        op.execute(f"DROP TRIGGER {name}_no_truncate ON {name}")
        op.execute(f"DROP TRIGGER {name}_immutable ON {name}")
    op.execute("DROP FUNCTION fp_reject_stock_mutation()")
    for table in ("movements", "operations", "lots", "locations", "owners", "items"):
        op.drop_table(f"fp_stock_{table}")
