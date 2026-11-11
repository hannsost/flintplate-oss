"""Support module models – sessions and per-tenant configuration."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class SupportConfig(Base):
    """Per-tenant support configuration."""

    __tablename__ = "support_configs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("customers.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )

    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    allow_video: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    allow_audio: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    allow_remote_control: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    allow_dom_viewing: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # Billing: included | per_session | per_minute | prepaid
    billing_model: Mapped[str] = mapped_column(String(20), nullable=False, default="included")
    per_session_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)
    per_minute_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)
    included_minutes_per_month: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Branding
    widget_title: Mapped[str] = mapped_column(String(100), nullable=False, default="Live Support")
    widget_color: Mapped[str] = mapped_column(String(20), nullable=False, default="#2563eb")
    welcome_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Privacy
    mask_sensitive_fields: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    require_consent: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    data_retention_days: Mapped[int] = mapped_column(Integer, nullable=False, default=30)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class SupportSession(Base):
    """A single support session between a recruiter (requester) and a support agent."""

    __tablename__ = "support_sessions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("customers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    requester_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    agent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )

    # pending | active | ended | cancelled | rejected | timeout
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    subject: Mapped[str] = mapped_column(String(255), nullable=False)

    # DSGVO consent
    consent_given: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    consent_given_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Timing
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Session capabilities (agreed at session start)
    video_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    audio_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    remote_control_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    dom_viewing_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # Billing
    billing_model: Mapped[str] = mapped_column(String(20), nullable=False, default="included")
    billed_amount_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)
    billed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Agent-only notes – NEVER exposed to requester
    agent_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Public summary visible to requester
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    end_reason: Mapped[str | None] = mapped_column(String(50), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
