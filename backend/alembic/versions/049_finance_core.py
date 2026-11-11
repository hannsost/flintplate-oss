"""Separate invoice issuers, finance grants, reviewed invoices and format evidence."""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

from alembic import op

revision = "049"
down_revision = "048"
branch_labels = None
depends_on = None


def base() -> list[sa.Column]:
    return [
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    ]


def fk(name: str, target: str, nullable: bool = False, delete: str = "RESTRICT") -> sa.Column:
    return sa.Column(
        name, pg.UUID(as_uuid=True), sa.ForeignKey(target, ondelete=delete), nullable=nullable
    )


def upgrade() -> None:
    op.create_table(
        "finance_legal_entities",
        *base(),
        fk("tenant_id", "customers.id"),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("data", pg.JSONB(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
    )
    op.create_index("ix_finance_legal_entities_tenant_id", "finance_legal_entities", ["tenant_id"])
    op.create_table(
        "finance_grants",
        *base(),
        fk("entity_id", "finance_legal_entities.id"),
        fk("user_id", "users.id", delete="CASCADE"),
        sa.Column("permissions", pg.JSONB(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.UniqueConstraint("entity_id", "user_id", name="uq_finance_grant"),
    )
    op.create_table(
        "finance_invoices",
        *base(),
        fk("tenant_id", "customers.id"),
        fk("entity_id", "finance_legal_entities.id"),
        sa.Column("entity_version", sa.Integer(), nullable=False),
        sa.Column("request_key", pg.UUID(), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False, server_default="invoice"),
        fk("original_id", "finance_invoices.id", nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("number", sa.String(60)),
        sa.Column("issue_date", sa.Date(), nullable=False),
        sa.Column("buyer_name", sa.String(200), nullable=False),
        sa.Column("service_reference", sa.String(120), nullable=False),
        sa.Column("payload", pg.JSONB(), nullable=False),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column("total", sa.Numeric(18, 2), nullable=False),
        fk("prepared_by", "users.id", True, "SET NULL"),
        fk("approved_by", "users.id", True, "SET NULL"),
        sa.Column("artifact", sa.LargeBinary()),
        sa.Column("artifact_hash", sa.String(64)),
        sa.Column("validation", pg.JSONB()),
        sa.Column("validation_report", sa.LargeBinary()),
        sa.UniqueConstraint("tenant_id", "request_key", name="uq_finance_request"),
        sa.UniqueConstraint("entity_id", "number", name="uq_finance_number"),
        sa.UniqueConstraint("original_id", name="uq_finance_full_credit"),
    )
    for key in ("tenant_id", "entity_id"):
        op.create_index(f"ix_finance_invoices_{key}", "finance_invoices", [key])
    op.create_table(
        "finance_invoice_sequences",
        *base(),
        fk("entity_id", "finance_legal_entities.id"),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("next_number", sa.Integer(), nullable=False, server_default="1"),
        sa.UniqueConstraint("entity_id", "year", name="uq_finance_sequence"),
    )
    op.create_table(
        "finance_billed_services",
        *base(),
        fk("entity_id", "finance_legal_entities.id"),
        sa.Column("reference", sa.String(120), nullable=False),
        fk("invoice_id", "finance_invoices.id"),
        sa.UniqueConstraint("entity_id", "reference", name="uq_finance_service"),
    )
    op.create_table(
        "finance_events",
        *base(),
        fk("entity_id", "finance_legal_entities.id"),
        fk("invoice_id", "finance_invoices.id", True),
        fk("actor_id", "users.id", True, "SET NULL"),
        sa.Column("action", sa.String(40), nullable=False),
        sa.Column("note", sa.Text(), nullable=False),
    )
    for key in ("entity_id", "invoice_id"):
        op.create_index(f"ix_finance_events_{key}", "finance_events", [key])


def downgrade() -> None:
    for name in (
        "finance_events",
        "finance_billed_services",
        "finance_invoice_sequences",
        "finance_invoices",
        "finance_grants",
        "finance_legal_entities",
    ):
        op.drop_table(name)
