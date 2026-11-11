"""Till sessions and append-only confirmed tenders and compensating refunds."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import JsonValue
from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.gastro.models import GastroBase


class CashRegister(GastroBase):
    __tablename__ = "fp_cash_registers"
    __table_args__ = (UniqueConstraint("venue_id", "name", name="uq_fp_cash_register_name"),)
    venue_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("fp_venues.id"), index=True)
    name: Mapped[str] = mapped_column(String(80))


class CashSession(GastroBase):
    __tablename__ = "fp_cash_sessions"
    __table_args__ = (
        Index(
            "uq_fp_cash_session_active",
            "register_id",
            unique=True,
            postgresql_where=text("status IN ('open', 'counted')"),
        ),
        UniqueConstraint("venue_id", "request_key", name="uq_fp_cash_session_request"),
    )
    venue_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("fp_venues.id"), index=True)
    register_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("fp_cash_registers.id"), index=True)
    operator_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    request_key: Mapped[uuid.UUID] = mapped_column()
    request_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(20), default="open")
    version: Mapped[int] = mapped_column(Integer, default=1)
    counted_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)
    expected_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)
    difference_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)
    count_request_key: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    count_request_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    count_reason: Mapped[str] = mapped_column(String(300), default="")
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    closed_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)


class CashEntry(GastroBase):
    """Positive receipts / negative refunds, or signed physical drawer movement."""

    __tablename__ = "fp_cash_entries"
    __table_args__ = (
        UniqueConstraint("venue_id", "id", name="uq_fp_partner_cash_scope"),
        UniqueConstraint("venue_id", "request_key", name="uq_fp_cash_entry_request"),
        UniqueConstraint("venue_id", "external_reference", name="uq_fp_cash_external_reference"),
    )
    venue_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("fp_venues.id"), index=True)
    session_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("fp_cash_sessions.id"), nullable=True, index=True
    )
    order_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("fp_orders.id"), nullable=True, index=True
    )
    original_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("fp_cash_entries.id"), nullable=True, index=True
    )
    kind: Mapped[str] = mapped_column(String(20))
    method: Mapped[str] = mapped_column(String(20))
    amount_cents: Mapped[int] = mapped_column(Integer)
    received_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)
    change_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)
    currency: Mapped[str] = mapped_column(String(3), default="EUR")
    allocations: Mapped[list[dict[str, JsonValue]]] = mapped_column(JSONB, default=list)
    payer: Mapped[str] = mapped_column(String(80), default="")
    reason: Mapped[str] = mapped_column(String(300), default="")
    actor_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    device_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("fp_devices.id"), nullable=True)
    external_reference: Mapped[str | None] = mapped_column(String(160), nullable=True)
    request_key: Mapped[uuid.UUID] = mapped_column()
    request_hash: Mapped[str] = mapped_column(String(64))
    points_delta: Mapped[int] = mapped_column(Integer, default=0)
