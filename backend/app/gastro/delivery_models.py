"""Versioned supplier statements, separate from received physical stock."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    Date,
    ForeignKeyConstraint,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.gastro.purchasing_terms_models import TermsEvidence, scope_fk


class DeliveryConfirmation(TermsEvidence):
    __tablename__ = "fp_delivery_confirmations"
    __table_args__ = (
        UniqueConstraint("venue_id", "id", name="uq_fp_delivery_scope"),
        UniqueConstraint("venue_id", "request_key", name="uq_fp_delivery_request"),
        UniqueConstraint("line_id", "version", name="uq_fp_delivery_version"),
        CheckConstraint(
            "version > 0 AND paid_quantity >= 0 AND bonus_quantity >= 0",
            name="ck_fp_delivery_quantity",
        ),
        CheckConstraint(
            "(status = 'confirmed' AND paid_quantity + bonus_quantity > 0) OR (status = 'cancelled' AND paid_quantity + bonus_quantity = 0)",
            name="ck_fp_delivery_status",
        ),
        scope_fk("line_id", "fp_purchase_order_lines", "fk_fp_delivery_line"),
        ForeignKeyConstraint(
            ["venue_id", "previous_id"],
            ["fp_delivery_confirmations.venue_id", "fp_delivery_confirmations.id"],
            name="fk_fp_delivery_previous",
        ),
    )
    line_id: Mapped[uuid.UUID] = mapped_column(index=True)
    previous_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(12))
    expected_on: Mapped[date] = mapped_column(Date)
    paid_quantity: Mapped[Decimal] = mapped_column(Numeric(18, 6))
    bonus_quantity: Mapped[Decimal] = mapped_column(Numeric(18, 6))
    reference: Mapped[str] = mapped_column(String(120))
