"""Supplier pack catalogs, purchasing, partial receipts and checked supplier invoices."""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

from alembic import op

revision = "071"
down_revision = "070"
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


def scope_fk(column: str, table: str, name: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["venue_id", column], [f"{table}.venue_id", f"{table}.id"], name=name
    )


def upgrade() -> None:
    op.create_table(
        "fp_suppliers",
        *base_columns(),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("reference", sa.String(120), nullable=False, server_default=""),
        sa.Column("contact", sa.String(200), nullable=False, server_default=""),
        sa.UniqueConstraint("venue_id", "id", name="uq_fp_supplier_scope"),
        sa.UniqueConstraint("venue_id", "name", name="uq_fp_supplier_name"),
    )
    op.create_table(
        "fp_supplier_products",
        *base_columns(),
        sa.Column("supplier_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("item_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("supplier_sku", sa.String(80), nullable=False),
        sa.Column("pack_name", sa.String(80), nullable=False),
        sa.Column("pack_quantity", sa.Numeric(18, 6), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.UniqueConstraint("venue_id", "id", name="uq_fp_supplier_product_scope"),
        sa.UniqueConstraint(
            "venue_id", "supplier_id", "supplier_sku", name="uq_fp_supplier_product_sku"
        ),
        sa.CheckConstraint("pack_quantity > 0", name="ck_fp_supplier_pack_quantity"),
        scope_fk("supplier_id", "fp_suppliers", "fk_fp_supplier_product_supplier"),
        scope_fk("item_id", "fp_stock_items", "fk_fp_supplier_product_item"),
    )
    op.create_table(
        "fp_supplier_prices",
        *base_columns(),
        sa.Column("product_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("effective_on", sa.Date(), nullable=False),
        sa.Column("pack_price_cents", sa.Integer(), nullable=False),
        sa.Column("tax_rate_bps", sa.Integer(), nullable=False),
        sa.Column("actor_id", pg.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.UniqueConstraint("venue_id", "id", name="uq_fp_supplier_price_scope"),
        sa.UniqueConstraint("product_id", "version", name="uq_fp_supplier_price_version"),
        sa.CheckConstraint("pack_price_cents >= 0", name="ck_fp_supplier_price_amount"),
        sa.CheckConstraint("tax_rate_bps BETWEEN 0 AND 10000", name="ck_fp_supplier_price_tax"),
        scope_fk("product_id", "fp_supplier_products", "fk_fp_supplier_price_product"),
    )
    op.create_table(
        "fp_purchase_orders",
        *base_columns(),
        sa.Column("supplier_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("owner_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("location_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("number", sa.String(24), nullable=False),
        sa.Column("status", sa.String(12), nullable=False, server_default="draft"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("request_key", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("expected_on", sa.Date(), nullable=True),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("note", sa.String(300), nullable=False),
        sa.Column("actor_id", pg.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.UniqueConstraint("venue_id", "id", name="uq_fp_purchase_order_scope"),
        sa.UniqueConstraint("venue_id", "request_key", name="uq_fp_purchase_order_request"),
        sa.UniqueConstraint("venue_id", "number", name="uq_fp_purchase_order_number"),
        sa.CheckConstraint(
            "status IN ('draft','ordered','partial','received','closed','cancelled')",
            name="ck_fp_purchase_order_status",
        ),
        scope_fk("supplier_id", "fp_suppliers", "fk_fp_purchase_order_supplier"),
        scope_fk("owner_id", "fp_stock_owners", "fk_fp_purchase_order_owner"),
        scope_fk("location_id", "fp_stock_locations", "fk_fp_purchase_order_location"),
    )
    op.create_table(
        "fp_purchase_order_lines",
        *base_columns(),
        sa.Column("order_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("product_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("item_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("price_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("item_name", sa.String(120), nullable=False),
        sa.Column("unit", sa.String(10), nullable=False),
        sa.Column("supplier_sku", sa.String(80), nullable=False),
        sa.Column("pack_name", sa.String(80), nullable=False),
        sa.Column("pack_quantity", sa.Numeric(18, 6), nullable=False),
        sa.Column("packs", sa.Integer(), nullable=False),
        sa.Column("ordered_quantity", sa.Numeric(18, 6), nullable=False),
        sa.Column("pack_price_cents", sa.Integer(), nullable=False),
        sa.Column("tax_rate_bps", sa.Integer(), nullable=False),
        sa.UniqueConstraint("venue_id", "id", name="uq_fp_purchase_line_scope"),
        sa.UniqueConstraint("order_id", "product_id", name="uq_fp_purchase_line_product"),
        sa.CheckConstraint(
            "packs > 0 AND ordered_quantity > 0 AND pack_quantity > 0",
            name="ck_fp_purchase_line_quantity",
        ),
        sa.CheckConstraint(
            "pack_price_cents >= 0 AND tax_rate_bps BETWEEN 0 AND 10000",
            name="ck_fp_purchase_line_price",
        ),
        scope_fk("order_id", "fp_purchase_orders", "fk_fp_purchase_line_order"),
        scope_fk("product_id", "fp_supplier_products", "fk_fp_purchase_line_product"),
        scope_fk("item_id", "fp_stock_items", "fk_fp_purchase_line_item"),
        scope_fk("price_id", "fp_supplier_prices", "fk_fp_purchase_line_price"),
    )
    op.create_table(
        "fp_purchase_receipts",
        *base_columns(),
        sa.Column("line_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("stock_operation_id", pg.UUID(as_uuid=True), nullable=True, unique=True),
        sa.Column("request_key", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("accepted_quantity", sa.Numeric(18, 6), nullable=False),
        sa.Column("rejected_quantity", sa.Numeric(18, 6), nullable=False),
        sa.Column("reference", sa.String(120), nullable=False),
        sa.Column("rejection_reason", sa.String(300), nullable=False),
        sa.Column("details", pg.JSONB(), nullable=False),
        sa.Column("actor_id", pg.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.UniqueConstraint("venue_id", "request_key", name="uq_fp_purchase_receipt_request"),
        sa.CheckConstraint(
            "accepted_quantity >= 0 AND rejected_quantity >= 0 AND accepted_quantity + rejected_quantity > 0",
            name="ck_fp_purchase_receipt_quantity",
        ),
        sa.CheckConstraint(
            "(accepted_quantity > 0 AND stock_operation_id IS NOT NULL) OR (accepted_quantity = 0 AND stock_operation_id IS NULL)",
            name="ck_fp_purchase_receipt_posting",
        ),
        scope_fk("line_id", "fp_purchase_order_lines", "fk_fp_purchase_receipt_line"),
        scope_fk("stock_operation_id", "fp_stock_operations", "fk_fp_purchase_receipt_operation"),
    )
    op.create_table(
        "fp_purchase_invoices",
        *base_columns(),
        sa.Column("supplier_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("number", sa.String(80), nullable=False),
        sa.Column("issued_on", sa.Date(), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("status", sa.String(12), nullable=False, server_default="draft"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("request_key", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("actor_id", pg.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("decided_by", pg.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("decision_reason", sa.String(300), nullable=False, server_default=""),
        sa.Column("approval_snapshot", pg.JSONB(), nullable=True),
        sa.UniqueConstraint("venue_id", "id", name="uq_fp_purchase_invoice_scope"),
        sa.UniqueConstraint("venue_id", "request_key", name="uq_fp_purchase_invoice_request"),
        sa.CheckConstraint(
            "status IN ('draft','approved','rejected')", name="ck_fp_purchase_invoice_status"
        ),
        scope_fk("supplier_id", "fp_suppliers", "fk_fp_purchase_invoice_supplier"),
    )
    op.create_index(
        "uq_fp_purchase_invoice_number",
        "fp_purchase_invoices",
        ["venue_id", "supplier_id", "number"],
        unique=True,
        postgresql_where=sa.text("status <> 'rejected'"),
    )
    op.create_table(
        "fp_purchase_invoice_lines",
        *base_columns(),
        sa.Column("invoice_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("purchase_line_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("quantity", sa.Numeric(18, 6), nullable=False),
        sa.Column("net_cents", sa.Integer(), nullable=False),
        sa.Column("tax_rate_bps", sa.Integer(), nullable=False),
        sa.UniqueConstraint("invoice_id", "purchase_line_id", name="uq_fp_purchase_invoice_line"),
        sa.CheckConstraint(
            "quantity > 0 AND net_cents >= 0 AND tax_rate_bps BETWEEN 0 AND 10000",
            name="ck_fp_purchase_invoice_line_value",
        ),
        scope_fk("invoice_id", "fp_purchase_invoices", "fk_fp_purchase_invoice_line_invoice"),
        scope_fk(
            "purchase_line_id", "fp_purchase_order_lines", "fk_fp_purchase_invoice_line_order"
        ),
    )
    for table in (
        "suppliers",
        "supplier_products",
        "supplier_prices",
        "purchase_orders",
        "purchase_order_lines",
        "purchase_receipts",
        "purchase_invoices",
        "purchase_invoice_lines",
    ):
        name = f"fp_{table}"
        op.create_index(f"ix_{name}_venue_id", name, ["venue_id"])
    for table, column in (
        ("purchase_order_lines", "order_id"),
        ("purchase_receipts", "line_id"),
        ("purchase_invoice_lines", "invoice_id"),
    ):
        op.create_index(f"ix_fp_{table}_{column}", f"fp_{table}", [column])
    op.execute(
        """CREATE FUNCTION fp_reject_purchase_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
      BEGIN RAISE EXCEPTION 'FlintPlate purchasing evidence is append-only'; END $$"""
    )
    for table in (
        "supplier_prices",
        "purchase_order_lines",
        "purchase_receipts",
        "purchase_invoice_lines",
    ):
        name = f"fp_{table}"
        op.execute(
            f"CREATE TRIGGER {name}_immutable BEFORE UPDATE OR DELETE ON {name} FOR EACH ROW EXECUTE FUNCTION fp_reject_purchase_mutation()"
        )
        op.execute(
            f"CREATE TRIGGER {name}_no_truncate BEFORE TRUNCATE ON {name} FOR EACH STATEMENT EXECUTE FUNCTION fp_reject_purchase_mutation()"
        )
    op.execute("""CREATE FUNCTION fp_guard_purchase_order() RETURNS trigger LANGUAGE plpgsql AS $$
      BEGIN
        IF (to_jsonb(NEW) - 'status' - 'version') IS DISTINCT FROM
           (to_jsonb(OLD) - 'status' - 'version') OR NEW.version <> OLD.version + 1 THEN
          RAISE EXCEPTION 'FlintPlate purchase terms are immutable';
        END IF;
        RETURN NEW;
      END $$""")
    op.execute(
        "CREATE TRIGGER fp_purchase_orders_guard BEFORE UPDATE ON fp_purchase_orders FOR EACH ROW EXECUTE FUNCTION fp_guard_purchase_order()"
    )
    op.execute("""CREATE FUNCTION fp_guard_purchase_invoice() RETURNS trigger LANGUAGE plpgsql AS $$
      BEGIN
        IF OLD.status <> 'draft' OR NEW.version <> OLD.version + 1 OR
          (to_jsonb(NEW) - ARRAY['status','version','decided_by','decision_reason','approval_snapshot']) IS DISTINCT FROM
          (to_jsonb(OLD) - ARRAY['status','version','decided_by','decision_reason','approval_snapshot']) THEN
          RAISE EXCEPTION 'FlintPlate purchase invoice is immutable after its decision';
        END IF;
        RETURN NEW;
      END $$""")
    op.execute(
        "CREATE TRIGGER fp_purchase_invoices_guard BEFORE UPDATE ON fp_purchase_invoices FOR EACH ROW EXECUTE FUNCTION fp_guard_purchase_invoice()"
    )
    for table in ("purchase_orders", "purchase_invoices"):
        name = f"fp_{table}"
        op.execute(
            f"CREATE TRIGGER {name}_no_delete BEFORE DELETE ON {name} FOR EACH ROW EXECUTE FUNCTION fp_reject_purchase_mutation()"
        )
        op.execute(
            f"CREATE TRIGGER {name}_no_truncate BEFORE TRUNCATE ON {name} FOR EACH STATEMENT EXECUTE FUNCTION fp_reject_purchase_mutation()"
        )
    op.execute(
        """CREATE FUNCTION fp_guard_purchase_line_insert() RETURNS trigger LANGUAGE plpgsql AS $$
      DECLARE parent_status text;
      BEGIN
        IF TG_TABLE_NAME = 'fp_purchase_order_lines' THEN
          SELECT status INTO parent_status FROM fp_purchase_orders WHERE id = NEW.order_id AND venue_id = NEW.venue_id;
        ELSE
          SELECT status INTO parent_status FROM fp_purchase_invoices WHERE id = NEW.invoice_id AND venue_id = NEW.venue_id;
        END IF;
        IF parent_status IS DISTINCT FROM 'draft' THEN
          RAISE EXCEPTION 'FlintPlate commercial lines can only be added to a draft';
        END IF;
        RETURN NEW;
      END $$"""
    )
    for table in ("purchase_order_lines", "purchase_invoice_lines"):
        op.execute(
            f"CREATE TRIGGER fp_{table}_insert_guard BEFORE INSERT ON fp_{table} FOR EACH ROW EXECUTE FUNCTION fp_guard_purchase_line_insert()"
        )


def downgrade() -> None:
    for table in ("purchase_order_lines", "purchase_invoice_lines"):
        op.execute(f"DROP TRIGGER fp_{table}_insert_guard ON fp_{table}")
    op.execute("DROP FUNCTION fp_guard_purchase_line_insert()")
    for table in ("purchase_orders", "purchase_invoices"):
        op.execute(f"DROP TRIGGER fp_{table}_guard ON fp_{table}")
        op.execute(f"DROP TRIGGER fp_{table}_no_delete ON fp_{table}")
        op.execute(f"DROP TRIGGER fp_{table}_no_truncate ON fp_{table}")
    op.execute("DROP FUNCTION fp_guard_purchase_order()")
    op.execute("DROP FUNCTION fp_guard_purchase_invoice()")
    for table in (
        "supplier_prices",
        "purchase_order_lines",
        "purchase_receipts",
        "purchase_invoice_lines",
    ):
        op.execute(f"DROP TRIGGER fp_{table}_immutable ON fp_{table}")
        op.execute(f"DROP TRIGGER fp_{table}_no_truncate ON fp_{table}")
    op.execute("DROP FUNCTION fp_reject_purchase_mutation()")
    for table in (
        "purchase_invoice_lines",
        "purchase_invoices",
        "purchase_receipts",
        "purchase_order_lines",
        "purchase_orders",
        "supplier_prices",
        "supplier_products",
        "suppliers",
    ):
        op.drop_table(f"fp_{table}")
