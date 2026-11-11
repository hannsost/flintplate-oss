"""Immutable stock holds and their explicit release or exact-once consumption."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.gastro.inventory_models import InventoryBase


class StockReservation(InventoryBase):
    __tablename__ = "fp_stock_reservations"
    __table_args__ = (
        UniqueConstraint("venue_id", "id", name="uq_fp_stock_reservation_scope"),
        UniqueConstraint("venue_id", "request_key", name="uq_fp_stock_reservation_request"),
        CheckConstraint("quantity > 0", name="ck_fp_stock_reservation_quantity"),
        CheckConstraint("expires_at > created_at", name="ck_fp_stock_reservation_expiry"),
        ForeignKeyConstraint(
            ["venue_id", "lot_id"],
            ["fp_stock_lots.venue_id", "fp_stock_lots.id"],
            name="fk_fp_stock_reservation_lot",
        ),
        ForeignKeyConstraint(
            ["venue_id", "location_id"],
            ["fp_stock_locations.venue_id", "fp_stock_locations.id"],
            name="fk_fp_stock_reservation_location",
        ),
    )
    venue_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("fp_venues.id"), index=True)
    lot_id: Mapped[uuid.UUID] = mapped_column()
    location_id: Mapped[uuid.UUID] = mapped_column()
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 6))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    request_key: Mapped[uuid.UUID] = mapped_column()
    request_hash: Mapped[str] = mapped_column(String(64))
    reason: Mapped[str] = mapped_column(String(300))
    actor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))


class StockReservationClose(InventoryBase):
    __tablename__ = "fp_stock_reservation_closures"
    __table_args__ = (
        UniqueConstraint("venue_id", "request_key", name="uq_fp_reservation_close_request"),
        UniqueConstraint("reservation_id", name="uq_fp_reservation_close_once"),
        CheckConstraint(
            "(kind = 'release' AND stock_operation_id IS NULL) OR (kind = 'consume' AND stock_operation_id IS NOT NULL)",
            name="ck_fp_reservation_close_kind",
        ),
        ForeignKeyConstraint(
            ["venue_id", "reservation_id"],
            ["fp_stock_reservations.venue_id", "fp_stock_reservations.id"],
            name="fk_fp_reservation_close_hold",
        ),
        ForeignKeyConstraint(
            ["venue_id", "stock_operation_id"],
            ["fp_stock_operations.venue_id", "fp_stock_operations.id"],
            name="fk_fp_reservation_close_stock",
        ),
    )
    venue_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("fp_venues.id"), index=True)
    reservation_id: Mapped[uuid.UUID] = mapped_column()
    kind: Mapped[str] = mapped_column(String(10))
    stock_operation_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    request_key: Mapped[uuid.UUID] = mapped_column()
    request_hash: Mapped[str] = mapped_column(String(64))
    reason: Mapped[str] = mapped_column(String(300))
    actor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
