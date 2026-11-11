"""Complete the inherited ORM timestamps in the installed inventory family."""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "076a"
down_revision = "076"
branch_labels = None
depends_on = None

# InventoryBase inherits TimestampMixin.updated_at. The original migrations
# supplied created_at explicitly but omitted this second inherited column.
# Do not rewrite those applied migrations or alter existing business evidence.
TABLES = (
    "fp_haccp_records",
    "fp_hygiene_plan_checks",
    "fp_hygiene_plan_versions",
    "fp_loan_accounts",
    "fp_loan_entries",
    "fp_partner_contracts",
    "fp_partner_events",
    "fp_partner_postings",
    "fp_partner_settlements",
    "fp_partner_terms",
    "fp_prep_runs",
    "fp_purchase_invoice_lines",
    "fp_purchase_invoices",
    "fp_purchase_order_lines",
    "fp_purchase_orders",
    "fp_purchase_receipts",
    "fp_recipe_versions",
    "fp_stock_items",
    "fp_stock_locations",
    "fp_stock_lots",
    "fp_stock_movements",
    "fp_stock_operations",
    "fp_stock_owners",
    "fp_stock_reservation_closures",
    "fp_stock_reservations",
    "fp_supplier_prices",
    "fp_supplier_products",
    "fp_suppliers",
)


def _guards(*, timestamps: bool) -> None:
    # Preserve business immutability while allowing TimestampMixin.onupdate.
    # A downgrade restores the original comparison before removing the column.
    definitions = (
        (
            "fp_guard_stock_lot_update",
            "'blocked','version'",
            "",
            "FlintPlate lot identity is immutable; only versioned quarantine changes are allowed",
        ),
        (
            "fp_guard_purchase_order",
            "'status','version'",
            "",
            "FlintPlate purchase terms are immutable",
        ),
        (
            "fp_guard_purchase_invoice",
            "'status','version','decided_by','decision_reason','approval_snapshot'",
            "OLD.status <> 'draft' OR ",
            "FlintPlate purchase invoice is immutable after its decision",
        ),
    )
    for name, fields, condition, message in definitions:
        if timestamps:
            fields += ",'updated_at'"
        op.execute(f"""CREATE OR REPLACE FUNCTION {name}() RETURNS trigger LANGUAGE plpgsql AS $$
          BEGIN
            IF {condition}NEW.version <> OLD.version + 1 OR
              (to_jsonb(NEW) - ARRAY[{fields}]) IS DISTINCT FROM
              (to_jsonb(OLD) - ARRAY[{fields}]) THEN
              RAISE EXCEPTION '{message}';
            END IF;
            RETURN NEW;
          END $$""")


def upgrade() -> None:
    for table in TABLES:
        op.add_column(
            table,
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        )
    _guards(timestamps=True)


def downgrade() -> None:
    _guards(timestamps=False)
    for table in reversed(TABLES):
        op.drop_column(table, "updated_at")
