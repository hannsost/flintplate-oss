"""Configured operating stations; their identity and competence group never change."""

from __future__ import annotations

import uuid

from pydantic import JsonValue
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.gastro.models import GastroBase


class OperatingStation(GastroBase):
    __tablename__ = "fp_operating_stations"
    __table_args__ = (
        UniqueConstraint("venue_id", "code", name="uq_fp_station_code"),
        Index("uq_fp_station_name", "venue_id", text("lower(name)"), unique=True),
        CheckConstraint("code ~ '^[a-z][a-z0-9_]{0,39}$'", name="ck_fp_station_code"),
        CheckConstraint(
            "kind IN ('kitchen','bar','service','activities')", name="ck_fp_station_kind"
        ),
        CheckConstraint(
            "version > 0 AND sort_order BETWEEN 0 AND 999", name="ck_fp_station_version"
        ),
        CheckConstraint("length(btrim(name)) BETWEEN 2 AND 80", name="ck_fp_station_name"),
    )
    venue_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("fp_venues.id"), index=True)
    code: Mapped[str] = mapped_column(String(40))
    name: Mapped[str] = mapped_column(String(80))
    kind: Mapped[str] = mapped_column(String(20))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    version: Mapped[int] = mapped_column(Integer, default=1)


class StationCommand(GastroBase):
    __tablename__ = "fp_station_commands"
    __table_args__ = (UniqueConstraint("venue_id", "request_key", name="uq_fp_station_command"),)
    venue_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("fp_venues.id"), index=True)
    request_key: Mapped[uuid.UUID] = mapped_column()
    request_hash: Mapped[str] = mapped_column(String(64))
    kind: Mapped[str] = mapped_column(String(20))
    actor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    result: Mapped[dict[str, JsonValue]] = mapped_column(JSONB)
