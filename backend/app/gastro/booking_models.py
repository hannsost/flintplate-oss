"""Reservation groups, explicit waiting guests and replayable service commands."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import JsonValue
from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.gastro.models import GastroBase


class ReservationMeta(GastroBase):
    __tablename__ = "fp_reservation_meta"
    reservation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("fp_reservations.id"), unique=True, index=True
    )
    source: Mapped[str] = mapped_column(String(20), default="reservation")
    note: Mapped[str] = mapped_column(String(500), default="")
    checked_in_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ReservationResource(GastroBase):
    __tablename__ = "fp_reservation_resources"
    __table_args__ = (
        UniqueConstraint("reservation_id", "table_id", name="uq_fp_reservation_resource"),
        UniqueConstraint("reservation_id", "position", name="uq_fp_reservation_position"),
        CheckConstraint("position BETWEEN 0 AND 7", name="ck_fp_reservation_position"),
    )
    reservation_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("fp_reservations.id"), index=True)
    table_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("fp_tables.id"), index=True)
    position: Mapped[int] = mapped_column(Integer)


class WaitlistEntry(GastroBase):
    __tablename__ = "fp_waitlist_entries"
    __table_args__ = (
        CheckConstraint("guests BETWEEN 1 AND 100", name="ck_fp_waitlist_guests"),
        CheckConstraint("status IN ('waiting','seated','cancelled')", name="ck_fp_waitlist_status"),
        CheckConstraint(
            "(status = 'seated') = (reservation_id IS NOT NULL)", name="ck_fp_waitlist_seated"
        ),
    )
    venue_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("fp_venues.id"), index=True)
    guest_name: Mapped[str] = mapped_column(String(120))
    guests: Mapped[int] = mapped_column(Integer)
    note: Mapped[str] = mapped_column(String(500), default="")
    status: Mapped[str] = mapped_column(String(20), default="waiting")
    version: Mapped[int] = mapped_column(Integer, default=1)
    reservation_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("fp_reservations.id"), nullable=True, unique=True
    )
    actor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ReservationCommand(GastroBase):
    __tablename__ = "fp_reservation_commands"
    __table_args__ = (
        UniqueConstraint("venue_id", "request_key", name="uq_fp_reservation_command"),
    )
    venue_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("fp_venues.id"), index=True)
    request_key: Mapped[uuid.UUID] = mapped_column()
    request_hash: Mapped[str] = mapped_column(String(64))
    kind: Mapped[str] = mapped_column(String(40))
    result: Mapped[dict[str, JsonValue]] = mapped_column(JSONB)
    actor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
