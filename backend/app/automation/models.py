"""Versioned, tenant-owned process definitions and immutable execution snapshots."""

from __future__ import annotations

import uuid

from sqlalchemy import Boolean, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.timed_model import TimedUUIDBase


class ProcessTemplate(TimedUUIDBase):
    __tablename__ = "process_templates"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("customers.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(120))
    version: Mapped[int] = mapped_column(Integer, default=1)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    four_eyes: Mapped[bool] = mapped_column(Boolean, default=True)
    steps: Mapped[list[dict[str, object]]] = mapped_column(JSONB)


class ProcessRun(TimedUUIDBase):
    __tablename__ = "process_runs"
    __table_args__ = (UniqueConstraint("tenant_id", "request_key", name="uq_process_request"),)

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("customers.id", ondelete="CASCADE"), index=True
    )
    template_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("process_templates.id", ondelete="CASCADE")
    )
    job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("job_postings.id", ondelete="CASCADE"))
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    request_key: Mapped[uuid.UUID]
    template_version: Mapped[int] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(String(30), default="running")
    version: Mapped[int] = mapped_column(Integer, default=1)
    cursor: Mapped[int] = mapped_column(Integer, default=0)
    four_eyes: Mapped[bool] = mapped_column(Boolean)
    authorize_ai: Mapped[bool] = mapped_column(Boolean, default=False)
    source: Mapped[dict[str, str]] = mapped_column(JSONB)
    steps: Mapped[list[dict[str, object]]] = mapped_column(JSONB)
    results: Mapped[list[dict[str, object]]] = mapped_column(JSONB, default=list)


class ProcessEvent(TimedUUIDBase):
    __tablename__ = "process_events"

    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("process_runs.id", ondelete="CASCADE"), index=True
    )
    actor_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    action: Mapped[str] = mapped_column(String(30))
    step: Mapped[int] = mapped_column(Integer)
    note: Mapped[str] = mapped_column(String(2000), default="")
