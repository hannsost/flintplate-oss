"""Versioned named arrangements; historical snapshots never own live tables."""

from __future__ import annotations

import uuid

from pydantic import JsonValue
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.gastro.models import GastroBase


class FloorLayoutProfile(GastroBase):
    __tablename__ = "fp_floor_layout_profiles"
    __table_args__ = (
        UniqueConstraint("venue_id", "id", name="uq_fp_floor_layout_profile_scope"),
        Index(
            "uq_fp_floor_layout_profile_name",
            "venue_id",
            text("lower(name)"),
            unique=True,
            postgresql_where=text("NOT archived"),
        ),
        CheckConstraint(
            "version > 0 AND length(btrim(name)) BETWEEN 2 AND 80",
            name="ck_fp_floor_layout_profile_state",
        ),
    )
    venue_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("fp_venues.id"), index=True)
    name: Mapped[str] = mapped_column(String(80))
    # Historical scope, intentionally not an FK preventing later room deletion.
    # Save validates venue ownership; preview/apply detect missing rooms/tables.
    room_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    archived: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")


class FloorLayoutRevision(GastroBase):
    __tablename__ = "fp_floor_layout_revisions"
    __table_args__ = (
        UniqueConstraint("venue_id", "profile_id", "id", name="uq_fp_floor_layout_revision_scope"),
        UniqueConstraint("profile_id", "version", name="uq_fp_floor_layout_revision_version"),
        ForeignKeyConstraint(
            ["venue_id", "profile_id"],
            ["fp_floor_layout_profiles.venue_id", "fp_floor_layout_profiles.id"],
            name="fk_fp_floor_layout_revision_profile",
        ),
        ForeignKeyConstraint(
            ["venue_id", "profile_id", "previous_id"],
            [
                "fp_floor_layout_revisions.venue_id",
                "fp_floor_layout_revisions.profile_id",
                "fp_floor_layout_revisions.id",
            ],
            name="fk_fp_floor_layout_revision_previous",
        ),
        CheckConstraint(
            "(version = 1 AND previous_id IS NULL) OR (version > 1 AND previous_id IS NOT NULL)",
            name="ck_fp_floor_layout_revision_previous",
        ),
        CheckConstraint(
            "jsonb_typeof(placements) = 'array' AND jsonb_array_length(placements) BETWEEN 1 AND 500",
            name="ck_fp_floor_layout_revision_placements",
        ),
    )
    venue_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("fp_venues.id"), index=True)
    profile_id: Mapped[uuid.UUID] = mapped_column(index=True)
    previous_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    version: Mapped[int] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(String(80))
    room_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    archived: Mapped[bool] = mapped_column(Boolean)
    placements: Mapped[list[dict[str, JsonValue]]] = mapped_column(JSONB)
    actor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))


class FloorLayoutCommand(GastroBase):
    __tablename__ = "fp_floor_layout_commands"
    __table_args__ = (
        UniqueConstraint("venue_id", "request_key", name="uq_fp_floor_layout_command_request"),
        CheckConstraint(
            "kind IN ('position','save','apply','archive')", name="ck_fp_floor_layout_command_kind"
        ),
    )
    venue_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("fp_venues.id"), index=True)
    request_key: Mapped[uuid.UUID] = mapped_column()
    request_hash: Mapped[str] = mapped_column(String(64))
    kind: Mapped[str] = mapped_column(String(12))
    actor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    result: Mapped[dict[str, JsonValue]] = mapped_column(JSONB)
