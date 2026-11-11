"""ORM model for worker absences (Sprint 4.6)."""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import UUID, Boolean, Date, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base_model import UUIDBase

ABSENCE_TYPES = ("vacation", "sick", "unpaid", "special", "other")
ABSENCE_STATUSES = ("pending", "approved", "rejected", "cancelled")


def calc_working_days(start: date, end: date) -> int:
    """Count Mon–Fri days between start and end inclusive."""
    total = 0
    current = start
    from datetime import timedelta

    while current <= end:
        if current.weekday() < 5:  # Mon=0 … Fri=4
            total += 1
        current += timedelta(days=1)
    return total


class Absence(UUIDBase):
    __tablename__ = "absences"

    worker_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("customers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    absence_type: Mapped[str] = mapped_column(String(30), nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    working_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    worker_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(nullable=True)
    reviewer_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    certificate_uploaded: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
