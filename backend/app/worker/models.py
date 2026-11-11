"""SQLAlchemy models for the Worker Hub (Phase 4)."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import UUID, Boolean, Date, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base_model import UUIDBase

# Canonical list of all worker-portal modules.
# HR can enable/disable each per worker.
ALL_MODULES: dict[str, bool] = {
    "timetracking": True,
    "schedule": True,
    "messages": True,
    "documents": True,
    "absences": True,
    "equipment": True,
    "tasks": True,
    "payroll": True,
    "tickets": True,
    "profile_selfservice": True,
}

EMPLOYMENT_TYPES = ("fulltime", "parttime", "minijob", "temp")


class WorkerSettings(UUIDBase):
    """Per-worker configuration, created and managed by HR / Disponent."""

    __tablename__ = "worker_settings"

    # 1:1 to users (unique)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
        index=True,
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("customers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # fulltime | parttime | minijob | temp
    employment_type: Mapped[str] = mapped_column(String(20), default="temp", nullable=False)
    max_weekly_hours: Mapped[int | None] = mapped_column(Integer, nullable=True)
    hourly_rate: Mapped[Decimal | None] = mapped_column(Numeric(8, 2), nullable=True)
    # {"timetracking": true, "schedule": true, ...}
    active_modules: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict(ALL_MODULES)
    )
    internal_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Recruiter/disponent responsible for this worker
    assigned_manager_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    assigned_team_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("teams.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    activated_at: Mapped[datetime | None] = mapped_column(nullable=True)

    # ── Profile self-service fields (worker-editable) ──────────────────────────
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    address_street: Mapped[str | None] = mapped_column(String(300), nullable=True)
    address_city: Mapped[str | None] = mapped_column(String(100), nullable=True)
    address_zip: Mapped[str | None] = mapped_column(String(20), nullable=True)
    address_country: Mapped[str | None] = mapped_column(String(100), nullable=True, default="DE")
    date_of_birth: Mapped[date | None] = mapped_column(Date, nullable=True)
    emergency_contact_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    emergency_contact_phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    iban: Mapped[str | None] = mapped_column(String(34), nullable=True)
    avatar_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
