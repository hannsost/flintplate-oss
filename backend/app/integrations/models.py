"""Encrypted provider credentials and single-use authorization requests."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base_model import UUIDBase


class WorkspaceConnection(UUIDBase):
    __tablename__ = "workspace_connections"
    __table_args__ = (UniqueConstraint("user_id", "provider", name="uq_connection_user_provider"),)

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("customers.id", ondelete="CASCADE"))
    provider: Mapped[str] = mapped_column(String(20))
    email: Mapped[str] = mapped_column(String(255))
    access_cipher: Mapped[str] = mapped_column(Text)
    refresh_cipher: Mapped[str] = mapped_column(Text)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AuthorizationRequest(UUIDBase):
    __tablename__ = "integration_authorizations"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("customers.id", ondelete="CASCADE"))
    provider: Mapped[str] = mapped_column(String(20))
    state_digest: Mapped[str] = mapped_column(String(64), unique=True)
    verifier_cipher: Mapped[str] = mapped_column(Text)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RecruitingMessage(UUIDBase):
    __tablename__ = "recruiting_messages"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("customers.id", ondelete="CASCADE"), index=True
    )
    person_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    author_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    recipient: Mapped[str] = mapped_column(String(255))
    subject: Mapped[str] = mapped_column(String(300))
    body: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="draft")
    provider: Mapped[str | None] = mapped_column(String(20))
    external_id: Mapped[str | None] = mapped_column(String(255))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CalendarDelivery(UUIDBase):
    __tablename__ = "calendar_deliveries"
    __table_args__ = (
        UniqueConstraint("connection_id", "schedule_id", name="uq_calendar_connection_schedule"),
    )

    connection_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspace_connections.id", ondelete="CASCADE")
    )
    schedule_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("interview_schedules.id", ondelete="CASCADE")
    )
    external_id: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(20), default="pending")
