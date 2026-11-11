"""Immutable full-history revisions of explicitly evidenced calculation rates."""

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


class LabourRateRevision(GastroBase):
    __tablename__ = "fp_labour_rate_revisions"
    __table_args__ = (
        UniqueConstraint("venue_id", "worker_id", "id", name="uq_fp_labour_revision_scope"),
        UniqueConstraint("venue_id", "worker_id", "version", name="uq_fp_labour_revision_version"),
        UniqueConstraint("venue_id", "request_key", name="uq_fp_labour_revision_request"),
        ForeignKeyConstraint(
            ["venue_id", "worker_id", "previous_id"],
            [
                "fp_labour_rate_revisions.venue_id",
                "fp_labour_rate_revisions.worker_id",
                "fp_labour_rate_revisions.id",
            ],
            name="fk_fp_labour_revision_previous",
        ),
        CheckConstraint(
            "version > 0 AND ((version = 1) = (previous_id IS NULL))",
            name="ck_fp_labour_revision_version",
        ),
        CheckConstraint(
            "jsonb_typeof(periods) = 'array' AND jsonb_array_length(periods) <= 200",
            name="ck_fp_labour_revision_periods",
        ),
        CheckConstraint(
            "length(btrim(reason)) BETWEEN 3 AND 300 AND length(btrim(source_reference)) BETWEEN 3 AND 300",
            name="ck_fp_labour_revision_source",
        ),
    )
    venue_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("fp_venues.id"), index=True)
    worker_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    previous_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    version: Mapped[int] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String(3))
    request_key: Mapped[uuid.UUID] = mapped_column()
    request_hash: Mapped[str] = mapped_column(String(64))
    actor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    reason: Mapped[str] = mapped_column(String(300))
    source_reference: Mapped[str] = mapped_column(String(300))
    periods: Mapped[list[dict[str, JsonValue]]] = mapped_column(JSONB)
