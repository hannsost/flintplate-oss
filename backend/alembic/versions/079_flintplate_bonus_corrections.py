"""Immutable counter-documents and versioned supplier bonus document corrections."""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

from alembic import op

revision = "079"
down_revision = "078"
branch_labels = None
depends_on = None


def evidence() -> list[sa.Column[object]]:
    return [
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
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


def revision_fk(column: str, name: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["venue_id", "document_id", column],
        [
            "fp_supplier_bonus_document_revisions.venue_id",
            "fp_supplier_bonus_document_revisions.document_id",
            "fp_supplier_bonus_document_revisions.id",
        ],
        name=name,
    )


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_fp_bonus_allocation_scope", "fp_supplier_bonus_allocations", ["venue_id", "id"]
    )
    op.create_table(
        "fp_supplier_bonus_document_revisions",
        *evidence(),
        sa.Column("document_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("previous_revision_id", pg.UUID(as_uuid=True), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(12), nullable=False),
        sa.Column("issued_on", sa.Date(), nullable=False),
        sa.Column("net_cents", sa.BigInteger(), nullable=False),
        sa.Column("tax_cents", sa.BigInteger(), nullable=False),
        sa.UniqueConstraint(
            "venue_id", "document_id", "id", name="uq_fp_bonus_document_revision_scope"
        ),
        sa.UniqueConstraint("document_id", "version", name="uq_fp_bonus_document_revision_version"),
        sa.UniqueConstraint(
            "venue_id", "request_key", name="uq_fp_bonus_document_revision_request"
        ),
        sa.CheckConstraint(
            "version >= 2 AND net_cents > 0 AND tax_cents >= 0",
            name="ck_fp_bonus_document_revision_value",
        ),
        sa.CheckConstraint(
            "kind IN ('corrected','void')", name="ck_fp_bonus_document_revision_kind"
        ),
        sa.CheckConstraint(
            "(version = 2 AND previous_revision_id IS NULL) OR (version > 2 AND previous_revision_id IS NOT NULL)",
            name="ck_fp_bonus_document_revision_previous",
        ),
        scope_fk(
            "document_id", "fp_supplier_bonus_documents", "fk_fp_bonus_document_revision_document"
        ),
        revision_fk("previous_revision_id", "fk_fp_bonus_document_revision_previous"),
    )
    op.add_column(
        "fp_supplier_bonus_allocations",
        sa.Column("document_revision_id", pg.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_fp_bonus_allocation_document_revision",
        "fp_supplier_bonus_allocations",
        "fp_supplier_bonus_document_revisions",
        ["venue_id", "document_id", "document_revision_id"],
        ["venue_id", "document_id", "id"],
    )
    op.create_table(
        "fp_supplier_bonus_allocation_reversals",
        *evidence(),
        sa.Column("allocation_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("document_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("document_revision_id", pg.UUID(as_uuid=True), nullable=True),
        sa.Column("agreement_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("amount_cents", sa.BigInteger(), nullable=False),
        sa.UniqueConstraint("allocation_id", name="uq_fp_bonus_allocation_reversal_original"),
        sa.UniqueConstraint(
            "venue_id", "request_key", name="uq_fp_bonus_allocation_reversal_request"
        ),
        sa.CheckConstraint("amount_cents > 0", name="ck_fp_bonus_allocation_reversal_amount"),
        scope_fk(
            "allocation_id",
            "fp_supplier_bonus_allocations",
            "fk_fp_bonus_allocation_reversal_original",
        ),
        scope_fk(
            "document_id", "fp_supplier_bonus_documents", "fk_fp_bonus_allocation_reversal_document"
        ),
        scope_fk(
            "agreement_id",
            "fp_supplier_bonus_agreements",
            "fk_fp_bonus_allocation_reversal_agreement",
        ),
        revision_fk("document_revision_id", "fk_fp_bonus_allocation_reversal_revision"),
    )
    for table, columns in (
        ("fp_supplier_bonus_document_revisions", ("venue_id", "document_id")),
        ("fp_supplier_bonus_allocation_reversals", ("venue_id", "document_id", "agreement_id")),
    ):
        for column in columns:
            op.create_index(f"ix_{table}_{column}", table, [column])
        op.execute(
            f"CREATE TRIGGER {table}_immutable BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION fp_reject_purchase_mutation()"
        )
        op.execute(
            f"CREATE TRIGGER {table}_no_truncate BEFORE TRUNCATE ON {table} FOR EACH STATEMENT EXECUTE FUNCTION fp_reject_purchase_mutation()"
        )


def downgrade() -> None:
    op.execute("""DO $$ BEGIN
      IF EXISTS (SELECT 1 FROM fp_supplier_bonus_document_revisions)
        OR EXISTS (SELECT 1 FROM fp_supplier_bonus_allocation_reversals)
        OR EXISTS (SELECT 1 FROM fp_supplier_bonus_allocations WHERE document_revision_id IS NOT NULL)
      THEN RAISE EXCEPTION '079 downgrade would erase bonus correction evidence'; END IF;
      END $$""")
    op.drop_table("fp_supplier_bonus_allocation_reversals")
    op.drop_constraint(
        "fk_fp_bonus_allocation_document_revision",
        "fp_supplier_bonus_allocations",
        type_="foreignkey",
    )
    op.drop_column("fp_supplier_bonus_allocations", "document_revision_id")
    op.drop_table("fp_supplier_bonus_document_revisions")
    op.drop_constraint(
        "uq_fp_bonus_allocation_scope", "fp_supplier_bonus_allocations", type_="unique"
    )
