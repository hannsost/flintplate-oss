"""Partner contracts, consignment recognition, monthly statements and loan custody."""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

from alembic import op

revision = "073"
down_revision = "072"
branch_labels = None
depends_on = None

TABLES = (
    "fp_partner_contracts",
    "fp_partner_terms",
    "fp_partner_postings",
    "fp_partner_events",
    "fp_partner_settlements",
    "fp_loan_accounts",
    "fp_loan_entries",
)


def base() -> list[sa.Column[object]]:
    return [
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("venue_id", pg.UUID(as_uuid=True), sa.ForeignKey("fp_venues.id"), nullable=False),
    ]


def uid(name: str, *, nullable: bool = False) -> sa.Column[object]:
    return sa.Column(name, pg.UUID(as_uuid=True), nullable=nullable)


def actor() -> sa.Column[object]:
    return sa.Column("actor_id", pg.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False)


def request() -> list[sa.Column[object]]:
    return [uid("request_key"), sa.Column("request_hash", sa.String(64), nullable=False)]


def scope(column: str, table: str, name: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["venue_id", column], [f"{table}.venue_id", f"{table}.id"], name=name
    )


def upgrade() -> None:
    for table, name in (
        ("fp_menu_items", "uq_fp_partner_menu_scope"),
        ("fp_orders", "uq_fp_partner_order_scope"),
        ("fp_cash_entries", "uq_fp_partner_cash_scope"),
    ):
        op.create_unique_constraint(name, table, ["venue_id", "id"])
    op.drop_constraint("ck_fp_stock_operation_kind", "fp_stock_operations", type_="check")
    op.create_check_constraint(
        "ck_fp_stock_operation_kind",
        "fp_stock_operations",
        "kind IN ('receipt','transfer','waste','count','quarantine','production','consume','return')",
    )
    op.create_table(
        "fp_partner_contracts",
        *base(),
        uid("owner_id"),
        uid("item_id"),
        uid("menu_item_id"),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        *request(),
        actor(),
        sa.UniqueConstraint("venue_id", "id", name="uq_fp_partner_contract_scope"),
        sa.UniqueConstraint("venue_id", "menu_item_id", name="uq_fp_partner_contract_menu"),
        sa.UniqueConstraint("venue_id", "request_key", name="uq_fp_partner_contract_request"),
        scope("owner_id", "fp_stock_owners", "fk_fp_partner_contract_owner"),
        scope("item_id", "fp_stock_items", "fk_fp_partner_contract_item"),
        scope("menu_item_id", "fp_menu_items", "fk_fp_partner_contract_menu"),
    )
    op.create_table(
        "fp_partner_terms",
        *base(),
        uid("contract_id"),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("effective_on", sa.Date(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("stock_per_sale", sa.Numeric(18, 6), nullable=False),
        sa.Column("rules", pg.JSONB(), nullable=False),
        *request(),
        actor(),
        sa.UniqueConstraint("venue_id", "id", name="uq_fp_partner_terms_scope"),
        sa.UniqueConstraint("contract_id", "version", name="uq_fp_partner_terms_version"),
        sa.UniqueConstraint("contract_id", "effective_on", name="uq_fp_partner_terms_date"),
        sa.UniqueConstraint("venue_id", "request_key", name="uq_fp_partner_terms_request"),
        sa.CheckConstraint(
            "version > 0 AND stock_per_sale > 0", name="ck_fp_partner_terms_quantity"
        ),
        sa.CheckConstraint("EXTRACT(DAY FROM effective_on) = 1", name="ck_fp_partner_terms_month"),
        scope("contract_id", "fp_partner_contracts", "fk_fp_partner_terms_contract"),
    )
    op.create_table(
        "fp_partner_postings",
        *base(),
        uid("contract_id"),
        sa.Column("kind", sa.String(20), nullable=False),
        *request(),
        sa.Column("reason", sa.String(300), nullable=False),
        actor(),
        sa.UniqueConstraint("venue_id", "id", name="uq_fp_partner_posting_scope"),
        sa.UniqueConstraint("venue_id", "request_key", name="uq_fp_partner_posting_request"),
        scope("contract_id", "fp_partner_contracts", "fk_fp_partner_posting_contract"),
    )
    op.create_table(
        "fp_partner_events",
        *base(),
        uid("contract_id"),
        uid("terms_id"),
        uid("posting_id"),
        uid("original_id", nullable=True),
        uid("stock_operation_id", nullable=True),
        uid("order_id", nullable=True),
        uid("cash_entry_id", nullable=True),
        uid("line_id", nullable=True),
        sa.Column("unit", sa.Integer(), nullable=True),
        sa.Column("kind", sa.String(12), nullable=False),
        sa.Column("occurred_on", sa.Date(), nullable=False),
        sa.Column("source_month", sa.Date(), nullable=False),
        sa.Column("posting_month", sa.Date(), nullable=False),
        sa.Column("physical_quantity", sa.Numeric(18, 6), nullable=False),
        sa.Column("gross_cents", sa.BigInteger(), nullable=False),
        sa.Column("net_cents", sa.BigInteger(), nullable=False),
        sa.Column("unit_fee_cents", sa.BigInteger(), nullable=False),
        sa.Column("loss_cents", sa.BigInteger(), nullable=False),
        sa.Column("evidence", pg.JSONB(), nullable=False),
        sa.UniqueConstraint("venue_id", "id", name="uq_fp_partner_event_scope"),
        sa.CheckConstraint(
            "kind IN ('sale','refund','return','waste')", name="ck_fp_partner_event_kind"
        ),
        sa.CheckConstraint(
            "physical_quantity >= 0 AND loss_cents >= 0", name="ck_fp_partner_event_quantity"
        ),
        sa.CheckConstraint(
            "posting_month >= source_month AND EXTRACT(DAY FROM posting_month) = 1 AND EXTRACT(DAY FROM source_month) = 1",
            name="ck_fp_partner_event_month",
        ),
        scope("contract_id", "fp_partner_contracts", "fk_fp_partner_event_contract"),
        scope("terms_id", "fp_partner_terms", "fk_fp_partner_event_terms"),
        scope("posting_id", "fp_partner_postings", "fk_fp_partner_event_posting"),
        scope("original_id", "fp_partner_events", "fk_fp_partner_event_original"),
        scope("stock_operation_id", "fp_stock_operations", "fk_fp_partner_event_stock"),
        scope("order_id", "fp_orders", "fk_fp_partner_event_order"),
        scope("cash_entry_id", "fp_cash_entries", "fk_fp_partner_event_cash"),
    )
    op.create_index(
        "uq_fp_partner_sale_unit",
        "fp_partner_events",
        ["venue_id", "order_id", "line_id", "unit"],
        unique=True,
        postgresql_where=sa.text("kind = 'sale'"),
    )
    op.create_index(
        "uq_fp_partner_refund_unit",
        "fp_partner_events",
        ["venue_id", "cash_entry_id", "line_id", "unit"],
        unique=True,
        postgresql_where=sa.text("kind = 'refund'"),
    )
    op.create_index(
        "uq_fp_partner_loss_operation",
        "fp_partner_events",
        ["venue_id", "stock_operation_id"],
        unique=True,
        postgresql_where=sa.text("kind IN ('waste','return')"),
    )
    op.create_table(
        "fp_partner_settlements",
        *base(),
        uid("contract_id"),
        sa.Column("month", sa.Date(), nullable=False),
        sa.Column("payable_to_partner_cents", sa.BigInteger(), nullable=False),
        sa.Column("snapshot", pg.JSONB(), nullable=False),
        *request(),
        sa.Column("reason", sa.String(300), nullable=False),
        actor(),
        sa.UniqueConstraint("venue_id", "id", name="uq_fp_partner_settlement_scope"),
        sa.UniqueConstraint("contract_id", "month", name="uq_fp_partner_settlement_month"),
        sa.UniqueConstraint("venue_id", "request_key", name="uq_fp_partner_settlement_request"),
        sa.CheckConstraint("EXTRACT(DAY FROM month) = 1", name="ck_fp_partner_settlement_month"),
        scope("contract_id", "fp_partner_contracts", "fk_fp_partner_settlement_contract"),
    )
    op.create_table(
        "fp_loan_accounts",
        *base(),
        uid("owner_id"),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("reference", sa.String(120), nullable=False),
        sa.Column("serialized", sa.Boolean(), nullable=False),
        sa.Column("deposit_per_unit_cents", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.UniqueConstraint("venue_id", "id", name="uq_fp_loan_account_scope"),
        sa.UniqueConstraint(
            "venue_id", "owner_id", "reference", name="uq_fp_loan_account_reference"
        ),
        sa.CheckConstraint("deposit_per_unit_cents >= 0", name="ck_fp_loan_account_deposit"),
        scope("owner_id", "fp_stock_owners", "fk_fp_loan_account_owner"),
    )
    op.create_table(
        "fp_loan_entries",
        *base(),
        uid("account_id"),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("amount_cents", sa.Integer(), nullable=False),
        uid("cash_entry_id", nullable=True),
        sa.Column("external_reference", sa.String(160), nullable=False),
        *request(),
        sa.Column("reason", sa.String(300), nullable=False),
        actor(),
        sa.UniqueConstraint("venue_id", "request_key", name="uq_fp_loan_entry_request"),
        sa.UniqueConstraint("venue_id", "cash_entry_id", name="uq_fp_loan_entry_cash"),
        sa.CheckConstraint(
            "kind IN ('received','returned','broken','deposit_paid','deposit_refunded','deposit_forfeited')",
            name="ck_fp_loan_entry_kind",
        ),
        sa.CheckConstraint("quantity >= 0 AND amount_cents >= 0", name="ck_fp_loan_entry_amount"),
        scope("account_id", "fp_loan_accounts", "fk_fp_loan_entry_account"),
        scope("cash_entry_id", "fp_cash_entries", "fk_fp_loan_entry_cash"),
    )
    op.create_index(
        "uq_fp_loan_entry_reference",
        "fp_loan_entries",
        ["venue_id", "external_reference"],
        unique=True,
        postgresql_where=sa.text("external_reference <> ''"),
    )
    op.execute(
        """CREATE FUNCTION fp_partner_immutable() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'Partner contracts and journals are append-only'; END; $$"""
    )
    for table in TABLES:
        op.create_index(f"ix_{table}_venue_id", table, ["venue_id"])
        op.execute(
            f"CREATE TRIGGER {table}_immutable BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION fp_partner_immutable()"
        )
        op.execute(
            f"CREATE TRIGGER {table}_no_truncate BEFORE TRUNCATE ON {table} FOR EACH STATEMENT EXECUTE FUNCTION fp_partner_immutable()"
        )
    op.create_index("ix_fp_partner_events_contract_id", "fp_partner_events", ["contract_id"])


def downgrade() -> None:
    op.execute(
        """DO $$ BEGIN IF EXISTS (SELECT 1 FROM fp_stock_operations WHERE kind = 'return') THEN RAISE EXCEPTION 'Cannot downgrade while partner return postings exist'; END IF; END; $$"""
    )
    for table in reversed(TABLES):
        op.drop_table(table)
    op.execute("DROP FUNCTION fp_partner_immutable()")
    # A destructive downgrade cannot relabel an immutable owner-return ledger entry.
    op.drop_constraint("ck_fp_stock_operation_kind", "fp_stock_operations", type_="check")
    op.create_check_constraint(
        "ck_fp_stock_operation_kind",
        "fp_stock_operations",
        "kind IN ('receipt','transfer','waste','count','quarantine','production','consume')",
    )
    for table, name in (
        ("fp_cash_entries", "uq_fp_partner_cash_scope"),
        ("fp_orders", "uq_fp_partner_order_scope"),
        ("fp_menu_items", "uq_fp_partner_menu_scope"),
    ):
        op.drop_constraint(name, table, type_="unique")
