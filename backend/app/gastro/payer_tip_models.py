"""Actual additive tips and their immutable distribution sources."""

from __future__ import annotations

import uuid

from pydantic import JsonValue
from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.gastro.models import GastroBase


class PayerTipEntry(GastroBase):
    __tablename__ = "fp_payer_tip_entries"
    __table_args__ = (
        UniqueConstraint("venue_id", "request_key", name="uq_fp_payer_tip_request"),
        Index(
            "uq_fp_payer_tip_group",
            "payment_group_id",
            unique=True,
            postgresql_where=text("kind='received'"),
        ),
        CheckConstraint(
            "(kind='received' AND amount_cents>0 AND original_id IS NULL) OR (kind='returned' AND amount_cents<0 AND original_id IS NOT NULL)",
            name="ck_fp_payer_tip_sign",
        ),
    )
    venue_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("fp_venues.id"), index=True)
    payment_group_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("fp_payment_groups.id"), index=True
    )
    session_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("fp_cash_sessions.id"), index=True)
    original_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("fp_payer_tip_entries.id"), nullable=True, index=True
    )
    kind: Mapped[str] = mapped_column(String(20))
    amount_cents: Mapped[int] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String(3))
    actor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    payer_tab_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("fp_guest_tabs.id"), nullable=True
    )
    payer_label: Mapped[str] = mapped_column(String(80), default="")
    recipient_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    request_key: Mapped[uuid.UUID]
    request_hash: Mapped[str] = mapped_column(String(64))
    reason: Mapped[str] = mapped_column(String(300), default="")


class TipRunSource(GastroBase):
    __tablename__ = "fp_tip_run_sources"
    __table_args__ = (
        CheckConstraint(
            "amount_cents>0 AND ((kind='order' AND order_id IS NOT NULL AND payer_tip_id IS NULL) OR (kind='payer_tip' AND order_id IS NULL AND payer_tip_id IS NOT NULL))",
            name="ck_fp_tip_run_source",
        ),
    )
    venue_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("fp_venues.id"), index=True)
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("fp_tip_runs.id"), index=True)
    kind: Mapped[str] = mapped_column(String(20))
    order_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("fp_orders.id"), unique=True, nullable=True
    )
    payer_tip_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("fp_payer_tip_entries.id"), unique=True, nullable=True
    )
    amount_cents: Mapped[int] = mapped_column(Integer)
    source_hash: Mapped[str] = mapped_column(String(64))
    source_snapshot: Mapped[dict[str, JsonValue]] = mapped_column(JSONB)
