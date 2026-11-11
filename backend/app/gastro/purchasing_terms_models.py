"""Immutable supplier rules, bonus claims and received credit-document allocations."""

from __future__ import annotations

import uuid
from datetime import date

from pydantic import JsonValue
from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.gastro.purchasing_models import PurchasingBase


def scope_fk(column: str, table: str, name: str) -> ForeignKeyConstraint:
    return ForeignKeyConstraint(
        ["venue_id", column], [f"{table}.venue_id", f"{table}.id"], name=name
    )


class TermsEvidence(PurchasingBase):
    __abstract__ = True
    request_key: Mapped[uuid.UUID] = mapped_column()
    request_hash: Mapped[str] = mapped_column(String(64))
    reason: Mapped[str] = mapped_column(String(300))
    actor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))


class SupplierOrderTerms(TermsEvidence):
    __tablename__ = "fp_supplier_order_terms"
    __table_args__ = (
        UniqueConstraint("venue_id", "id", name="uq_fp_supplier_terms_scope"),
        UniqueConstraint("venue_id", "request_key", name="uq_fp_supplier_terms_request"),
        UniqueConstraint("supplier_id", "version", name="uq_fp_supplier_terms_version"),
        CheckConstraint("version > 0", name="ck_fp_supplier_terms_version"),
        scope_fk("supplier_id", "fp_suppliers", "fk_fp_supplier_terms_supplier"),
    )
    supplier_id: Mapped[uuid.UUID] = mapped_column(index=True)
    version: Mapped[int] = mapped_column(Integer)
    effective_on: Mapped[date] = mapped_column(Date)
    rules: Mapped[dict[str, JsonValue]] = mapped_column(JSONB)


class SupplierBonusAgreement(TermsEvidence):
    __tablename__ = "fp_supplier_bonus_agreements"
    __table_args__ = (
        UniqueConstraint("venue_id", "id", name="uq_fp_supplier_bonus_agreement_scope"),
        UniqueConstraint("venue_id", "request_key", name="uq_fp_supplier_bonus_agreement_request"),
        UniqueConstraint(
            "venue_id", "supplier_id", "reference", name="uq_fp_supplier_bonus_agreement_reference"
        ),
        CheckConstraint("period_end >= period_start", name="ck_fp_supplier_bonus_period"),
        CheckConstraint(
            "rate_bps BETWEEN 1 AND 10000 AND threshold_cents >= 0",
            name="ck_fp_supplier_bonus_rate",
        ),
        CheckConstraint(
            "mode IN ('whole_base_at_threshold','excess_only')", name="ck_fp_supplier_bonus_mode"
        ),
        CheckConstraint(
            "source_basis = 'own_approved_invoice_net_before_credits'",
            name="ck_fp_supplier_bonus_basis",
        ),
        scope_fk("supplier_id", "fp_suppliers", "fk_fp_supplier_bonus_supplier"),
    )
    supplier_id: Mapped[uuid.UUID] = mapped_column(index=True)
    reference: Mapped[str] = mapped_column(String(120))
    period_start: Mapped[date] = mapped_column(Date)
    period_end: Mapped[date] = mapped_column(Date)
    currency: Mapped[str] = mapped_column(String(3))
    source_basis: Mapped[str] = mapped_column(String(60))
    rate_bps: Mapped[int] = mapped_column(Integer)
    threshold_cents: Mapped[int] = mapped_column(BigInteger)
    mode: Mapped[str] = mapped_column(String(30))


class SupplierBonusStatement(TermsEvidence):
    __tablename__ = "fp_supplier_bonus_statements"
    __table_args__ = (
        UniqueConstraint("venue_id", "id", name="uq_fp_supplier_bonus_statement_scope"),
        UniqueConstraint("venue_id", "request_key", name="uq_fp_supplier_bonus_statement_request"),
        UniqueConstraint(
            "agreement_id", "sequence", name="uq_fp_supplier_bonus_statement_sequence"
        ),
        CheckConstraint(
            "sequence > 0 AND delta_cents >= 0", name="ck_fp_supplier_bonus_statement_value"
        ),
        scope_fk(
            "agreement_id",
            "fp_supplier_bonus_agreements",
            "fk_fp_supplier_bonus_statement_agreement",
        ),
    )
    agreement_id: Mapped[uuid.UUID] = mapped_column(index=True)
    sequence: Mapped[int] = mapped_column(Integer)
    delta_cents: Mapped[int] = mapped_column(BigInteger)
    snapshot: Mapped[dict[str, JsonValue]] = mapped_column(JSONB)


class SupplierBonusDocument(TermsEvidence):
    __tablename__ = "fp_supplier_bonus_documents"
    __table_args__ = (
        UniqueConstraint("venue_id", "id", name="uq_fp_supplier_bonus_document_scope"),
        UniqueConstraint("venue_id", "request_key", name="uq_fp_supplier_bonus_document_request"),
        UniqueConstraint(
            "venue_id", "supplier_id", "reference", name="uq_fp_supplier_bonus_document_reference"
        ),
        CheckConstraint(
            "net_cents > 0 AND tax_cents >= 0", name="ck_fp_supplier_bonus_document_value"
        ),
        scope_fk("supplier_id", "fp_suppliers", "fk_fp_supplier_bonus_document_supplier"),
    )
    supplier_id: Mapped[uuid.UUID] = mapped_column(index=True)
    reference: Mapped[str] = mapped_column(String(120))
    issued_on: Mapped[date] = mapped_column(Date)
    net_cents: Mapped[int] = mapped_column(BigInteger)
    tax_cents: Mapped[int] = mapped_column(BigInteger)
    currency: Mapped[str] = mapped_column(String(3))


class SupplierBonusAllocation(TermsEvidence):
    __tablename__ = "fp_supplier_bonus_allocations"
    __table_args__ = (
        UniqueConstraint("venue_id", "id", name="uq_fp_bonus_allocation_scope"),
        UniqueConstraint("venue_id", "request_key", name="uq_fp_supplier_bonus_allocation_request"),
        CheckConstraint("amount_cents > 0", name="ck_fp_supplier_bonus_allocation_value"),
        scope_fk(
            "document_id", "fp_supplier_bonus_documents", "fk_fp_supplier_bonus_allocation_document"
        ),
        scope_fk(
            "agreement_id",
            "fp_supplier_bonus_agreements",
            "fk_fp_supplier_bonus_allocation_agreement",
        ),
        ForeignKeyConstraint(
            ["venue_id", "document_id", "document_revision_id"],
            [
                "fp_supplier_bonus_document_revisions.venue_id",
                "fp_supplier_bonus_document_revisions.document_id",
                "fp_supplier_bonus_document_revisions.id",
            ],
            name="fk_fp_bonus_allocation_document_revision",
        ),
    )
    document_id: Mapped[uuid.UUID] = mapped_column(index=True)
    document_revision_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    agreement_id: Mapped[uuid.UUID] = mapped_column(index=True)
    amount_cents: Mapped[int] = mapped_column(BigInteger)
