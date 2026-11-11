"""Revisions and counter-documents preserve original supplier bonus evidence."""

from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    ForeignKeyConstraint,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.gastro.purchasing_terms_models import TermsEvidence, scope_fk


class SupplierBonusDocumentRevision(TermsEvidence):
    __tablename__ = "fp_supplier_bonus_document_revisions"
    __table_args__ = (
        UniqueConstraint(
            "venue_id", "document_id", "id", name="uq_fp_bonus_document_revision_scope"
        ),
        UniqueConstraint("document_id", "version", name="uq_fp_bonus_document_revision_version"),
        UniqueConstraint("venue_id", "request_key", name="uq_fp_bonus_document_revision_request"),
        CheckConstraint(
            "version >= 2 AND net_cents > 0 AND tax_cents >= 0",
            name="ck_fp_bonus_document_revision_value",
        ),
        CheckConstraint("kind IN ('corrected','void')", name="ck_fp_bonus_document_revision_kind"),
        CheckConstraint(
            "(version = 2 AND previous_revision_id IS NULL) OR (version > 2 AND previous_revision_id IS NOT NULL)",
            name="ck_fp_bonus_document_revision_previous",
        ),
        scope_fk(
            "document_id", "fp_supplier_bonus_documents", "fk_fp_bonus_document_revision_document"
        ),
        ForeignKeyConstraint(
            ["venue_id", "document_id", "previous_revision_id"],
            [
                "fp_supplier_bonus_document_revisions.venue_id",
                "fp_supplier_bonus_document_revisions.document_id",
                "fp_supplier_bonus_document_revisions.id",
            ],
            name="fk_fp_bonus_document_revision_previous",
        ),
    )
    document_id: Mapped[uuid.UUID] = mapped_column(index=True)
    previous_revision_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    version: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(12))
    issued_on: Mapped[date] = mapped_column(Date)
    net_cents: Mapped[int] = mapped_column(BigInteger)
    tax_cents: Mapped[int] = mapped_column(BigInteger)


class SupplierBonusAllocationReversal(TermsEvidence):
    __tablename__ = "fp_supplier_bonus_allocation_reversals"
    __table_args__ = (
        UniqueConstraint("allocation_id", name="uq_fp_bonus_allocation_reversal_original"),
        UniqueConstraint("venue_id", "request_key", name="uq_fp_bonus_allocation_reversal_request"),
        CheckConstraint("amount_cents > 0", name="ck_fp_bonus_allocation_reversal_amount"),
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
        ForeignKeyConstraint(
            ["venue_id", "document_id", "document_revision_id"],
            [
                "fp_supplier_bonus_document_revisions.venue_id",
                "fp_supplier_bonus_document_revisions.document_id",
                "fp_supplier_bonus_document_revisions.id",
            ],
            name="fk_fp_bonus_allocation_reversal_revision",
        ),
    )
    allocation_id: Mapped[uuid.UUID] = mapped_column()
    document_id: Mapped[uuid.UUID] = mapped_column(index=True)
    document_revision_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    agreement_id: Mapped[uuid.UUID] = mapped_column(index=True)
    amount_cents: Mapped[int] = mapped_column(BigInteger)
