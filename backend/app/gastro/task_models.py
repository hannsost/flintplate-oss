"""Append-only evidence for a human task; the task itself is the current revision."""

from __future__ import annotations

import uuid

from pydantic import JsonValue
from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.gastro.models import GastroBase


class TaskCommand(GastroBase):
    __tablename__ = "fp_task_commands"
    __table_args__ = (
        UniqueConstraint("venue_id", "request_key", name="uq_fp_task_command_key"),
        UniqueConstraint("task_id", "version", name="uq_fp_task_command_version"),
        ForeignKeyConstraint(["venue_id", "task_id"], ["tasks.venue_id", "tasks.id"]),
        CheckConstraint("version > 0", name="ck_fp_task_command_version"),
        CheckConstraint(
            "kind IN ('create','start','done','cancel','reopen','reassign','edit')",
            name="ck_fp_task_command_kind",
        ),
    )
    venue_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("fp_venues.id"), index=True)
    task_id: Mapped[uuid.UUID] = mapped_column(index=True)
    version: Mapped[int] = mapped_column(Integer)
    request_key: Mapped[uuid.UUID] = mapped_column()
    request_hash: Mapped[str] = mapped_column(String(64))
    actor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    actor_name: Mapped[str] = mapped_column(String(255))
    kind: Mapped[str] = mapped_column(String(16))
    note: Mapped[str] = mapped_column(String(1000))
    before: Mapped[dict[str, JsonValue] | None] = mapped_column(
        JSONB(none_as_null=True), nullable=True
    )
    after: Mapped[dict[str, JsonValue]] = mapped_column(JSONB)
