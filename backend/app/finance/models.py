from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import (
    Date,
    ForeignKey,
    Integer,
    LargeBinary,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.timed_model import TimedUUIDBase


class LegalEntity(TimedUUIDBase):
    __tablename__ = "finance_legal_entities"
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID, ForeignKey("customers.id", ondelete="RESTRICT"), index=True
    )
    name: Mapped[str] = mapped_column(String(200))
    data: Mapped[dict[str, object]] = mapped_column(JSONB)
    version: Mapped[int] = mapped_column(Integer, default=1)


class FinanceGrant(TimedUUIDBase):
    __tablename__ = "finance_grants"
    __table_args__ = (UniqueConstraint("entity_id", "user_id", name="uq_finance_grant"),)
    entity_id: Mapped[uuid.UUID] = mapped_column(
        UUID, ForeignKey("finance_legal_entities.id", ondelete="RESTRICT")
    )
    user_id: Mapped[uuid.UUID] = mapped_column(UUID, ForeignKey("users.id", ondelete="CASCADE"))
    permissions: Mapped[list[str]] = mapped_column(JSONB)
    version: Mapped[int] = mapped_column(Integer, default=1)


class Invoice(TimedUUIDBase):
    __tablename__ = "finance_invoices"
    __table_args__ = (
        UniqueConstraint("tenant_id", "request_key", name="uq_finance_request"),
        UniqueConstraint("entity_id", "number", name="uq_finance_number"),
        UniqueConstraint("original_id", name="uq_finance_full_credit"),
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID, ForeignKey("customers.id", ondelete="RESTRICT"), index=True
    )
    entity_id: Mapped[uuid.UUID] = mapped_column(
        UUID, ForeignKey("finance_legal_entities.id", ondelete="RESTRICT"), index=True
    )
    entity_version: Mapped[int] = mapped_column(Integer)
    request_key: Mapped[uuid.UUID] = mapped_column(UUID)
    request_hash: Mapped[str] = mapped_column(String(64))
    kind: Mapped[str] = mapped_column(String(20), default="invoice")
    original_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID, ForeignKey("finance_invoices.id", ondelete="RESTRICT")
    )
    status: Mapped[str] = mapped_column(String(20), default="draft")
    version: Mapped[int] = mapped_column(Integer, default=1)
    number: Mapped[str | None] = mapped_column(String(60))
    issue_date: Mapped[date] = mapped_column(Date)
    buyer_name: Mapped[str] = mapped_column(String(200))
    service_reference: Mapped[str] = mapped_column(String(120))
    payload: Mapped[dict[str, object]] = mapped_column(JSONB)
    payload_hash: Mapped[str] = mapped_column(String(64))
    total: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    prepared_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID, ForeignKey("users.id", ondelete="SET NULL")
    )
    approved_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID, ForeignKey("users.id", ondelete="SET NULL")
    )
    approved_grant_version: Mapped[int | None] = mapped_column(Integer)
    artifact: Mapped[bytes | None] = mapped_column(LargeBinary)
    artifact_hash: Mapped[str | None] = mapped_column(String(64))
    validation: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    validation_report: Mapped[bytes | None] = mapped_column(LargeBinary)


class InvoiceSequence(TimedUUIDBase):
    __tablename__ = "finance_invoice_sequences"
    __table_args__ = (UniqueConstraint("entity_id", "year", name="uq_finance_sequence"),)
    entity_id: Mapped[uuid.UUID] = mapped_column(
        UUID, ForeignKey("finance_legal_entities.id", ondelete="RESTRICT")
    )
    year: Mapped[int] = mapped_column(Integer)
    next_number: Mapped[int] = mapped_column(Integer, default=1)


class BilledService(TimedUUIDBase):
    __tablename__ = "finance_billed_services"
    __table_args__ = (UniqueConstraint("entity_id", "reference", name="uq_finance_service"),)
    entity_id: Mapped[uuid.UUID] = mapped_column(
        UUID, ForeignKey("finance_legal_entities.id", ondelete="RESTRICT")
    )
    reference: Mapped[str] = mapped_column(String(120))
    invoice_id: Mapped[uuid.UUID] = mapped_column(
        UUID, ForeignKey("finance_invoices.id", ondelete="RESTRICT")
    )


class FinanceEvent(TimedUUIDBase):
    __tablename__ = "finance_events"
    entity_id: Mapped[uuid.UUID] = mapped_column(
        UUID, ForeignKey("finance_legal_entities.id", ondelete="RESTRICT"), index=True
    )
    invoice_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID, ForeignKey("finance_invoices.id", ondelete="RESTRICT"), index=True
    )
    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID, ForeignKey("users.id", ondelete="SET NULL")
    )
    action: Mapped[str] = mapped_column(String(40))
    note: Mapped[str] = mapped_column(Text, default="")
