"""Zeitarbeit-Modul models – Sprint 1.7."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class WorkAssignment(Base):
    """Kundenauftrag für Zeitarbeit-Einsatz."""

    __tablename__ = "work_assignments"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    recruiter_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    company_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="SET NULL"), nullable=True
    )
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("customers.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text(), nullable=True)
    required_skills: Mapped[list[str]] = mapped_column(ARRAY(Text()), nullable=False, default=list)
    location: Mapped[str | None] = mapped_column(String(255), nullable=True)
    shift: Mapped[str | None] = mapped_column(String(50), nullable=True)  # day / night / flexible
    hourly_rate: Mapped[Decimal | None] = mapped_column(Numeric(8, 2), nullable=True)
    start_date: Mapped[date | None] = mapped_column(Date(), nullable=True)
    end_date: Mapped[date | None] = mapped_column(Date(), nullable=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="incoming")
    slots: Mapped[int] = mapped_column(Integer(), nullable=False, default=1)
    max_duration_months: Mapped[int] = mapped_column(Integer(), nullable=False, default=18)
    notes: Mapped[str | None] = mapped_column(Text(), nullable=True)
    lat: Mapped[float | None] = mapped_column(Float(), nullable=True)
    lng: Mapped[float | None] = mapped_column(Float(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class TempWorkerAvailability(Base):
    """Verfügbarkeits-Profil eines Zeitarbeiters (1:1 zu User)."""

    __tablename__ = "temp_worker_availability"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True
    )

    is_in_pool: Mapped[bool] = mapped_column(Boolean(), nullable=False, default=False)
    available_from: Mapped[date | None] = mapped_column(Date(), nullable=True)
    available_until: Mapped[date | None] = mapped_column(Date(), nullable=True)
    preferred_shift: Mapped[str | None] = mapped_column(String(50), nullable=True)
    preferred_location: Mapped[str | None] = mapped_column(String(255), nullable=True)
    max_commute_km: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    total_placed_months: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), nullable=False, default=Decimal("0")
    )
    notes: Mapped[str | None] = mapped_column(Text(), nullable=True)
    lat: Mapped[float | None] = mapped_column(Float(), nullable=True)
    lng: Mapped[float | None] = mapped_column(Float(), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Disposition(Base):
    """Matching eines Zeitarbeiters mit einem Auftrag."""

    __tablename__ = "dispositions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    assignment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("work_assignments.id", ondelete="CASCADE"), nullable=False
    )
    worker_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )

    score: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False, default=Decimal("0"))
    matched_skills: Mapped[list[str]] = mapped_column(ARRAY(Text()), nullable=False, default=list)
    missing_skills: Mapped[list[str]] = mapped_column(ARRAY(Text()), nullable=False, default=list)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="suggested")
    started_at: Mapped[date | None] = mapped_column(Date(), nullable=True)
    ended_at: Mapped[date | None] = mapped_column(Date(), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
