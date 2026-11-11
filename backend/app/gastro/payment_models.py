"""Immutable group receipt and its original-order cash evidence."""

from __future__ import annotations

import uuid

from pydantic import JsonValue
from sqlalchemy import CheckConstraint, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.gastro.models import GastroBase


class PaymentGroup(GastroBase):
    __tablename__ = "fp_payment_groups"
    __table_args__ = (
        UniqueConstraint("venue_id", "request_key", name="uq_fp_payment_group_request"),
        CheckConstraint(
            "receipt_amount_cents>=0 AND new_tip_cents>=0 AND amount_cents=receipt_amount_cents+new_tip_cents AND amount_cents>0 AND received_cents>=amount_cents AND change_cents=received_cents-amount_cents",
            name="ck_fp_payment_group_amounts",
        ),
    )
    venue_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("fp_venues.id"), index=True)
    session_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("fp_cash_sessions.id"), index=True)
    actor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    payer_tab_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("fp_guest_tabs.id"), nullable=True
    )
    payer_label: Mapped[str] = mapped_column(String(80), default="")
    currency: Mapped[str] = mapped_column(String(3))
    receipt_amount_cents: Mapped[int] = mapped_column(Integer)
    new_tip_cents: Mapped[int] = mapped_column(Integer)
    amount_cents: Mapped[int] = mapped_column(Integer)
    received_cents: Mapped[int] = mapped_column(Integer)
    change_cents: Mapped[int] = mapped_column(Integer)
    request_key: Mapped[uuid.UUID]
    request_hash: Mapped[str] = mapped_column(String(64))
    quote_hash: Mapped[str] = mapped_column(String(64))
    source_hash: Mapped[str] = mapped_column(String(64))
    source_snapshot: Mapped[list[dict[str, JsonValue]]] = mapped_column(JSONB)
    quote: Mapped[dict[str, JsonValue]] = mapped_column(JSONB)
    allocations: Mapped[list[dict[str, JsonValue]]] = mapped_column(JSONB)


class PaymentGroupEntry(GastroBase):
    __tablename__ = "fp_payment_group_entries"
    __table_args__ = (UniqueConstraint("group_id", "order_id", name="uq_fp_payment_group_order"),)
    venue_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("fp_venues.id"), index=True)
    group_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("fp_payment_groups.id"), index=True)
    order_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("fp_orders.id"))
    entry_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("fp_cash_entries.id"), unique=True)
