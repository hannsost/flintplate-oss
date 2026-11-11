"""Versioned offers and onboarding tasks using the existing person identity."""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base_model import UUIDBase


class HiringOffer(UUIDBase):
    __tablename__ = "hiring_offers"
    __table_args__ = (
        Index(
            "uq_hiring_offer_active_application",
            "application_id",
            unique=True,
            postgresql_where=text("status NOT IN ('declined', 'withdrawn')"),
        ),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("customers.id", ondelete="CASCADE"), index=True
    )
    application_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE"), index=True
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    approver_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    title: Mapped[str] = mapped_column(String(300))
    terms: Mapped[str] = mapped_column(Text)
    start_date: Mapped[date] = mapped_column(Date)
    expires_on: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(20), default="draft")
    version: Mapped[int] = mapped_column(Integer, default=1)
    shared_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class OfferEvent(UUIDBase):
    __tablename__ = "offer_events"

    offer_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("hiring_offers.id", ondelete="CASCADE"), index=True
    )
    actor_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    status: Mapped[str] = mapped_column(String(20))
    version: Mapped[int] = mapped_column(Integer)
    note: Mapped[str | None] = mapped_column(String(2000))
    title: Mapped[str] = mapped_column(String(300))
    terms: Mapped[str] = mapped_column(Text)
    start_date: Mapped[date] = mapped_column(Date)
    expires_on: Mapped[date] = mapped_column(Date)


class OnboardingCase(UUIDBase):
    __tablename__ = "onboarding_cases"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("customers.id", ondelete="CASCADE"), index=True
    )
    offer_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("hiring_offers.id", ondelete="CASCADE"), unique=True
    )
    person_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    owner_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    start_date: Mapped[date] = mapped_column(Date)
    template: Mapped[str] = mapped_column(String(50))
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class OnboardingStep(UUIDBase):
    __tablename__ = "onboarding_steps"

    case_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("onboarding_cases.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(300))
    audience: Mapped[str] = mapped_column(String(20))
    assignee_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    due_on: Mapped[date] = mapped_column(Date)
    position: Mapped[int] = mapped_column(Integer)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
