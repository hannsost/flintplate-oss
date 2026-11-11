"""An adapter's explicit reconciliation of a changed checkout, never a payment."""

from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.gastro.models import GastroBase


class CancellationCheckoutAck(GastroBase):
    __tablename__ = "fp_cancellation_checkout_acks"
    __table_args__ = (
        UniqueConstraint("venue_id", "request_key", name="uq_fp_cancellation_checkout_key"),
        UniqueConstraint("execution_id", name="uq_fp_cancellation_checkout_execution"),
    )
    venue_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("fp_venues.id"), index=True)
    order_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("fp_orders.id"), index=True)
    execution_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("fp_cancellation_executions.id"))
    device_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("fp_devices.id"))
    request_key: Mapped[uuid.UUID] = mapped_column()
    request_hash: Mapped[str] = mapped_column(String(64))
    reference: Mapped[str] = mapped_column(String(160))
    order_version: Mapped[int] = mapped_column(Integer)
    cancellation_version: Mapped[int] = mapped_column(Integer)
    remaining_cents: Mapped[int] = mapped_column(Integer)
    cancelled_cents: Mapped[int] = mapped_column(Integer)
