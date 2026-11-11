"""Frozen purchasing tiers, natural rebates, delivery rules and supplier bonus evidence."""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

from alembic import op

revision = "077"
down_revision = "076a"
branch_labels = None
depends_on = None

TABLES = (
    "fp_supplier_order_terms",
    "fp_supplier_bonus_agreements",
    "fp_supplier_bonus_statements",
    "fp_supplier_bonus_documents",
    "fp_supplier_bonus_allocations",
)


def evidence() -> list[sa.Column[object]]:
    return [
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        # InventoryBase overrides created_at, but inherits this naive timestamp.
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("venue_id", pg.UUID(as_uuid=True), sa.ForeignKey("fp_venues.id"), nullable=False),
        sa.Column("request_key", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("reason", sa.String(300), nullable=False),
        sa.Column("actor_id", pg.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
    ]


def scope_fk(column: str, table: str, name: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["venue_id", column], [f"{table}.venue_id", f"{table}.id"], name=name
    )


def invoice_guard(*, with_timestamp: bool) -> None:
    # Both 077 and its predecessor 076a allow TimestampMixin.onupdate.
    allowed = "'status','version','decided_by','decision_reason','approval_snapshot','updated_at'"
    if with_timestamp:
        allowed += ",'decided_at'"
    op.execute(
        f"""CREATE OR REPLACE FUNCTION fp_guard_purchase_invoice() RETURNS trigger LANGUAGE plpgsql AS $$
      BEGIN
        IF OLD.status <> 'draft' OR NEW.version <> OLD.version + 1 OR
          (to_jsonb(NEW) - ARRAY[{allowed}]) IS DISTINCT FROM
          (to_jsonb(OLD) - ARRAY[{allowed}]) THEN
          RAISE EXCEPTION 'FlintPlate purchase invoice is immutable after its decision';
        END IF;
        RETURN NEW;
      END $$"""
    )


def upgrade() -> None:
    op.create_table(
        "fp_supplier_order_terms",
        *evidence(),
        sa.Column("supplier_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("effective_on", sa.Date(), nullable=False),
        sa.Column("rules", pg.JSONB(), nullable=False),
        sa.UniqueConstraint("venue_id", "id", name="uq_fp_supplier_terms_scope"),
        sa.UniqueConstraint("venue_id", "request_key", name="uq_fp_supplier_terms_request"),
        sa.UniqueConstraint("supplier_id", "version", name="uq_fp_supplier_terms_version"),
        sa.CheckConstraint("version > 0", name="ck_fp_supplier_terms_version"),
        scope_fk("supplier_id", "fp_suppliers", "fk_fp_supplier_terms_supplier"),
    )
    op.create_table(
        "fp_supplier_bonus_agreements",
        *evidence(),
        sa.Column("supplier_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("reference", sa.String(120), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("source_basis", sa.String(60), nullable=False),
        sa.Column("rate_bps", sa.Integer(), nullable=False),
        sa.Column("threshold_cents", sa.BigInteger(), nullable=False),
        sa.Column("mode", sa.String(30), nullable=False),
        sa.UniqueConstraint("venue_id", "id", name="uq_fp_supplier_bonus_agreement_scope"),
        sa.UniqueConstraint(
            "venue_id", "request_key", name="uq_fp_supplier_bonus_agreement_request"
        ),
        sa.UniqueConstraint(
            "venue_id", "supplier_id", "reference", name="uq_fp_supplier_bonus_agreement_reference"
        ),
        sa.CheckConstraint("period_end >= period_start", name="ck_fp_supplier_bonus_period"),
        sa.CheckConstraint(
            "rate_bps BETWEEN 1 AND 10000 AND threshold_cents >= 0",
            name="ck_fp_supplier_bonus_rate",
        ),
        sa.CheckConstraint(
            "mode IN ('whole_base_at_threshold','excess_only')", name="ck_fp_supplier_bonus_mode"
        ),
        sa.CheckConstraint(
            "source_basis = 'own_approved_invoice_net_before_credits'",
            name="ck_fp_supplier_bonus_basis",
        ),
        scope_fk("supplier_id", "fp_suppliers", "fk_fp_supplier_bonus_supplier"),
    )
    op.create_table(
        "fp_supplier_bonus_statements",
        *evidence(),
        sa.Column("agreement_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("delta_cents", sa.BigInteger(), nullable=False),
        sa.Column("snapshot", pg.JSONB(), nullable=False),
        sa.UniqueConstraint("venue_id", "id", name="uq_fp_supplier_bonus_statement_scope"),
        sa.UniqueConstraint(
            "venue_id", "request_key", name="uq_fp_supplier_bonus_statement_request"
        ),
        sa.UniqueConstraint(
            "agreement_id", "sequence", name="uq_fp_supplier_bonus_statement_sequence"
        ),
        sa.CheckConstraint(
            "sequence > 0 AND delta_cents >= 0", name="ck_fp_supplier_bonus_statement_value"
        ),
        scope_fk(
            "agreement_id",
            "fp_supplier_bonus_agreements",
            "fk_fp_supplier_bonus_statement_agreement",
        ),
    )
    op.create_table(
        "fp_supplier_bonus_documents",
        *evidence(),
        sa.Column("supplier_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("reference", sa.String(120), nullable=False),
        sa.Column("issued_on", sa.Date(), nullable=False),
        sa.Column("net_cents", sa.BigInteger(), nullable=False),
        sa.Column("tax_cents", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.UniqueConstraint("venue_id", "id", name="uq_fp_supplier_bonus_document_scope"),
        sa.UniqueConstraint(
            "venue_id", "request_key", name="uq_fp_supplier_bonus_document_request"
        ),
        sa.UniqueConstraint(
            "venue_id", "supplier_id", "reference", name="uq_fp_supplier_bonus_document_reference"
        ),
        sa.CheckConstraint(
            "net_cents > 0 AND tax_cents >= 0", name="ck_fp_supplier_bonus_document_value"
        ),
        scope_fk("supplier_id", "fp_suppliers", "fk_fp_supplier_bonus_document_supplier"),
    )
    op.create_table(
        "fp_supplier_bonus_allocations",
        *evidence(),
        sa.Column("document_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("agreement_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("amount_cents", sa.BigInteger(), nullable=False),
        sa.UniqueConstraint(
            "venue_id", "request_key", name="uq_fp_supplier_bonus_allocation_request"
        ),
        sa.CheckConstraint("amount_cents > 0", name="ck_fp_supplier_bonus_allocation_value"),
        scope_fk(
            "document_id", "fp_supplier_bonus_documents", "fk_fp_supplier_bonus_allocation_document"
        ),
        scope_fk(
            "agreement_id",
            "fp_supplier_bonus_agreements",
            "fk_fp_supplier_bonus_allocation_agreement",
        ),
    )
    for table, extra in (
        (TABLES[0], ("supplier_id",)),
        (TABLES[1], ("supplier_id",)),
        (TABLES[2], ("agreement_id",)),
        (TABLES[3], ("supplier_id",)),
        (TABLES[4], ("document_id", "agreement_id")),
    ):
        for column in ("venue_id", *extra):
            op.create_index(f"ix_{table}_{column}", table, [column])
        op.execute(
            f"CREATE TRIGGER {table}_immutable BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION fp_reject_purchase_mutation()"
        )
        op.execute(
            f"CREATE TRIGGER {table}_no_truncate BEFORE TRUNCATE ON {table} FOR EACH STATEMENT EXECUTE FUNCTION fp_reject_purchase_mutation()"
        )
    op.add_column(
        "fp_supplier_prices",
        sa.Column("conditions", pg.JSONB(), nullable=False, server_default="{}"),
    )
    op.add_column(
        "fp_purchase_order_lines",
        sa.Column("conditions_snapshot", pg.JSONB(), nullable=False, server_default="{}"),
    )
    op.add_column(
        "fp_purchase_order_lines",
        sa.Column("ordered_bonus_quantity", sa.Numeric(18, 6), nullable=False, server_default="0"),
    )
    op.create_check_constraint(
        "ck_fp_purchase_line_bonus",
        "fp_purchase_order_lines",
        "ordered_bonus_quantity >= 0 AND ordered_quantity = packs * pack_quantity + ordered_bonus_quantity",
    )
    op.add_column(
        "fp_purchase_orders", sa.Column("supplier_terms_id", pg.UUID(as_uuid=True), nullable=True)
    )
    op.add_column(
        "fp_purchase_orders",
        sa.Column("supplier_terms_snapshot", pg.JSONB(), nullable=False, server_default="{}"),
    )
    op.add_column("fp_purchase_orders", sa.Column("earliest_delivery_on", sa.Date(), nullable=True))
    op.create_foreign_key(
        "fk_fp_purchase_order_supplier_terms",
        "fp_purchase_orders",
        "fp_supplier_order_terms",
        ["venue_id", "supplier_terms_id"],
        ["venue_id", "id"],
    )
    for field in ("accepted_bonus_quantity", "rejected_bonus_quantity"):
        op.add_column(
            "fp_purchase_receipts",
            sa.Column(field, sa.Numeric(18, 6), nullable=False, server_default="0"),
        )
    op.create_check_constraint(
        "ck_fp_purchase_receipt_bonus",
        "fp_purchase_receipts",
        "accepted_bonus_quantity BETWEEN 0 AND accepted_quantity AND rejected_bonus_quantity BETWEEN 0 AND rejected_quantity",
    )
    op.add_column(
        "fp_purchase_invoices", sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True)
    )
    invoice_guard(with_timestamp=True)


def downgrade() -> None:
    populated = " OR ".join(f"EXISTS (SELECT 1 FROM {table})" for table in TABLES)
    op.execute(f"""DO $$ BEGIN
      IF {populated}
        OR EXISTS (SELECT 1 FROM fp_supplier_prices WHERE conditions <> '{{}}'::jsonb)
        OR EXISTS (SELECT 1 FROM fp_purchase_order_lines WHERE ordered_bonus_quantity <> 0 OR conditions_snapshot <> '{{}}'::jsonb)
        OR EXISTS (SELECT 1 FROM fp_purchase_receipts WHERE accepted_bonus_quantity <> 0 OR rejected_bonus_quantity <> 0)
        OR EXISTS (SELECT 1 FROM fp_purchase_invoices WHERE decided_at IS NOT NULL)
      THEN RAISE EXCEPTION '077 downgrade would erase purchasing terms or bonus evidence'; END IF;
      END $$""")
    invoice_guard(with_timestamp=False)
    op.drop_column("fp_purchase_invoices", "decided_at")
    op.drop_constraint("ck_fp_purchase_receipt_bonus", "fp_purchase_receipts", type_="check")
    for field in ("accepted_bonus_quantity", "rejected_bonus_quantity"):
        op.drop_column("fp_purchase_receipts", field)
    op.drop_constraint(
        "fk_fp_purchase_order_supplier_terms", "fp_purchase_orders", type_="foreignkey"
    )
    for field in ("earliest_delivery_on", "supplier_terms_snapshot", "supplier_terms_id"):
        op.drop_column("fp_purchase_orders", field)
    op.drop_constraint("ck_fp_purchase_line_bonus", "fp_purchase_order_lines", type_="check")
    op.drop_column("fp_purchase_order_lines", "ordered_bonus_quantity")
    op.drop_column("fp_purchase_order_lines", "conditions_snapshot")
    op.drop_column("fp_supplier_prices", "conditions")
    for table in reversed(TABLES):
        op.drop_table(table)
