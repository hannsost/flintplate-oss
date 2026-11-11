"""Visit context is separate from customers, original receipts and actual payers."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import JsonValue
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy import text as sa_text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.gastro.models import GastroBase


class ServiceCommand(GastroBase):
    __tablename__ = "fp_service_commands"
    __table_args__ = (
        UniqueConstraint("venue_id", "request_key", name="uq_fp_service_command_key"),
        UniqueConstraint("venue_id", "id", name="uq_fp_service_command_scope"),
    )
    venue_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("fp_venues.id"), index=True)
    request_key: Mapped[uuid.UUID]
    request_hash: Mapped[str] = mapped_column(String(64))
    actor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    kind: Mapped[str] = mapped_column(String(30))
    target_id: Mapped[uuid.UUID]
    reason: Mapped[str] = mapped_column(String(500), default="")
    snapshots: Mapped[list[dict[str, JsonValue]]] = mapped_column(JSONB)
    result: Mapped[dict[str, JsonValue]] = mapped_column(JSONB)


class ServiceSettings(GastroBase):
    __tablename__ = "fp_service_settings"
    __table_args__ = (
        UniqueConstraint("venue_id", name="uq_fp_service_settings_venue"),
        CheckConstraint(
            "version>0 AND workflow IN ('table','guest','counter','mixed') AND guest_label_mode IN ('number','name_or_number','seat_or_number')",
            name="ck_fp_service_settings",
        ),
    )
    venue_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("fp_venues.id"))
    workflow: Mapped[str] = mapped_column(String(20), default="table")
    guest_label_mode: Mapped[str] = mapped_column(String(24), default="number")
    version: Mapped[int] = mapped_column(Integer, default=1)
    last_command_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("fp_service_commands.id", deferrable=True, initially="DEFERRED")
    )


class ServiceVisit(GastroBase):
    __tablename__ = "fp_service_visits"
    __table_args__ = (
        UniqueConstraint("venue_id", "id", name="uq_fp_service_visit_scope"),
        UniqueConstraint("venue_id", "number", name="uq_fp_service_visit_number"),
        CheckConstraint("version>0", name="ck_fp_service_visit_version"),
    )
    venue_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("fp_venues.id"), index=True)
    reservation_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("fp_reservations.id"), nullable=True, unique=True
    )
    number: Mapped[str] = mapped_column(String(24))
    label: Mapped[str] = mapped_column(String(120), default="")
    version: Mapped[int] = mapped_column(Integer, default=1)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_command_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("fp_service_commands.id", deferrable=True, initially="DEFERRED")
    )


class GuestTab(GastroBase):
    __tablename__ = "fp_guest_tabs"
    __table_args__ = (
        UniqueConstraint("venue_id", "id", name="uq_fp_guest_tab_scope"),
        UniqueConstraint("visit_id", "kind", "number", name="uq_fp_guest_tab_number"),
        ForeignKeyConstraint(
            ["venue_id", "visit_id"], ["fp_service_visits.venue_id", "fp_service_visits.id"]
        ),
        Index(
            "uq_fp_guest_tab_shared",
            "visit_id",
            unique=True,
            postgresql_where=sa_text("kind='shared'"),
        ),
        CheckConstraint(
            "version>0 AND number>0 AND kind IN ('guest','shared') AND (kind!='shared' OR present=false)",
            name="ck_fp_guest_tab",
        ),
    )
    venue_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("fp_venues.id"), index=True)
    visit_id: Mapped[uuid.UUID] = mapped_column(index=True)
    kind: Mapped[str] = mapped_column(String(12))
    number: Mapped[int] = mapped_column(Integer)
    label: Mapped[str] = mapped_column(String(120), default="")
    current_table_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("fp_tables.id"), nullable=True
    )
    seat_label: Mapped[str] = mapped_column(String(30), default="")
    present: Mapped[bool] = mapped_column(Boolean, default=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    last_command_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("fp_service_commands.id", deferrable=True, initially="DEFERRED")
    )


class ServiceRound(GastroBase):
    __tablename__ = "fp_service_rounds"
    __table_args__ = (
        UniqueConstraint("venue_id", "id", name="uq_fp_service_round_scope"),
        UniqueConstraint("visit_id", "number", name="uq_fp_service_round_number"),
        ForeignKeyConstraint(
            ["venue_id", "visit_id"], ["fp_service_visits.venue_id", "fp_service_visits.id"]
        ),
    )
    venue_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("fp_venues.id"), index=True)
    visit_id: Mapped[uuid.UUID] = mapped_column(index=True)
    number: Mapped[int] = mapped_column(Integer)
    command_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("fp_service_commands.id", deferrable=True, initially="DEFERRED"), unique=True
    )
    expected_tab_ids: Mapped[list[str]] = mapped_column(JSONB)


class ServiceRoundChild(GastroBase):
    __tablename__ = "fp_service_round_children"
    __table_args__ = (
        UniqueConstraint("round_id", "guest_tab_id", name="uq_fp_service_round_tab"),
        ForeignKeyConstraint(
            ["venue_id", "round_id"], ["fp_service_rounds.venue_id", "fp_service_rounds.id"]
        ),
        ForeignKeyConstraint(
            ["venue_id", "guest_tab_id"], ["fp_guest_tabs.venue_id", "fp_guest_tabs.id"]
        ),
        ForeignKeyConstraint(["venue_id", "order_id"], ["fp_orders.venue_id", "fp_orders.id"]),
    )
    venue_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("fp_venues.id"), index=True)
    round_id: Mapped[uuid.UUID] = mapped_column(index=True)
    guest_tab_id: Mapped[uuid.UUID]
    order_id: Mapped[uuid.UUID] = mapped_column(unique=True, index=True)
    label_snapshot: Mapped[str] = mapped_column(String(160))


class ServiceUnitAssignment(GastroBase):
    __tablename__ = "fp_service_unit_assignments"
    __table_args__ = (
        UniqueConstraint(
            "order_id", "line_id", "unit", "version", name="uq_fp_service_assignment_revision"
        ),
        ForeignKeyConstraint(["venue_id", "order_id"], ["fp_orders.venue_id", "fp_orders.id"]),
        ForeignKeyConstraint(
            ["venue_id", "guest_tab_id"], ["fp_guest_tabs.venue_id", "fp_guest_tabs.id"]
        ),
        CheckConstraint(
            "unit>=0 AND version>0 AND ((cart_row_id IS NULL AND cart_unit IS NULL) OR (cart_row_id IS NOT NULL AND cart_unit>=0))",
            name="ck_fp_service_assignment",
        ),
    )
    venue_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("fp_venues.id"), index=True)
    order_id: Mapped[uuid.UUID] = mapped_column(index=True)
    line_id: Mapped[uuid.UUID]
    unit: Mapped[int] = mapped_column(Integer)
    guest_tab_id: Mapped[uuid.UUID]
    version: Mapped[int] = mapped_column(Integer)
    command_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("fp_service_commands.id", deferrable=True, initially="DEFERRED"), index=True
    )
    before_tab_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("fp_guest_tabs.id"), nullable=True
    )
    cart_row_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    cart_unit: Mapped[int | None] = mapped_column(Integer, nullable=True)
