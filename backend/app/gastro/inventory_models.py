"""Physical stock, its owner and the append-only quantity ledger."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import JsonValue
from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Identity,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base_model import UUIDBase


class InventoryBase(UUIDBase):
    __abstract__ = True
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=func.now(), server_default=func.now()
    )


class StockItem(InventoryBase):
    __tablename__ = "fp_stock_items"
    __table_args__ = (
        UniqueConstraint("venue_id", "id", name="uq_fp_stock_item_scope"),
        UniqueConstraint("venue_id", "sku", name="uq_fp_stock_item_sku"),
        CheckConstraint("unit IN ('kg', 'l', 'piece')", name="ck_fp_stock_item_unit"),
        CheckConstraint("minimum_quantity >= 0", name="ck_fp_stock_item_minimum"),
    )
    venue_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("fp_venues.id"), index=True)
    sku: Mapped[str] = mapped_column(String(60))
    name: Mapped[str] = mapped_column(String(120))
    unit: Mapped[str] = mapped_column(String(10))
    requires_expiry: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    minimum_quantity: Mapped[Decimal] = mapped_column(
        Numeric(18, 6), default=Decimal(0), server_default="0"
    )


class StockOwner(InventoryBase):
    __tablename__ = "fp_stock_owners"
    __table_args__ = (
        UniqueConstraint("venue_id", "id", name="uq_fp_stock_owner_scope"),
        UniqueConstraint("venue_id", "name", name="uq_fp_stock_owner_name"),
        CheckConstraint("kind IN ('own', 'partner')", name="ck_fp_stock_owner_kind"),
    )
    venue_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("fp_venues.id"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    kind: Mapped[str] = mapped_column(String(12))
    reference: Mapped[str] = mapped_column(String(120), default="", server_default="")


class StockLocation(InventoryBase):
    __tablename__ = "fp_stock_locations"
    __table_args__ = (
        UniqueConstraint("venue_id", "id", name="uq_fp_stock_location_scope"),
        UniqueConstraint("venue_id", "name", name="uq_fp_stock_location_name"),
    )
    venue_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("fp_venues.id"), index=True)
    name: Mapped[str] = mapped_column(String(120))


class StockLot(InventoryBase):
    """A supplier lot of one item held for one immutable owner."""

    __tablename__ = "fp_stock_lots"
    __table_args__ = (
        UniqueConstraint("venue_id", "id", name="uq_fp_stock_lot_scope"),
        CheckConstraint("version > 0", name="ck_fp_stock_lot_version"),
        UniqueConstraint("venue_id", "item_id", "owner_id", "code", name="uq_fp_stock_lot_code"),
        ForeignKeyConstraint(
            ["venue_id", "item_id"],
            ["fp_stock_items.venue_id", "fp_stock_items.id"],
            name="fk_fp_stock_lot_item",
        ),
        ForeignKeyConstraint(
            ["venue_id", "owner_id"],
            ["fp_stock_owners.venue_id", "fp_stock_owners.id"],
            name="fk_fp_stock_lot_owner",
        ),
    )
    venue_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("fp_venues.id"), index=True)
    item_id: Mapped[uuid.UUID] = mapped_column()
    owner_id: Mapped[uuid.UUID] = mapped_column()
    code: Mapped[str] = mapped_column(String(100))
    expires_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    blocked: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")


class StockOperation(InventoryBase):
    """The request and its ledger entries form one committed business transaction."""

    __tablename__ = "fp_stock_operations"
    __table_args__ = (
        UniqueConstraint("venue_id", "id", name="uq_fp_stock_operation_scope"),
        UniqueConstraint("venue_id", "request_key", name="uq_fp_stock_operation_request"),
        CheckConstraint(
            "kind IN ('receipt', 'transfer', 'waste', 'count', 'quarantine', 'production', 'consume', 'return')",
            name="ck_fp_stock_operation_kind",
        ),
    )
    venue_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("fp_venues.id"), index=True)
    sequence: Mapped[int] = mapped_column(BigInteger, Identity(), unique=True)
    request_key: Mapped[uuid.UUID] = mapped_column()
    request_hash: Mapped[str] = mapped_column(String(64))
    kind: Mapped[str] = mapped_column(String(12))
    actor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    reason: Mapped[str] = mapped_column(String(300))
    details: Mapped[dict[str, JsonValue]] = mapped_column(JSONB)


class StockMovement(InventoryBase):
    """Signed base-unit quantity at one location; transfers have two opposite entries."""

    __tablename__ = "fp_stock_movements"
    __table_args__ = (
        UniqueConstraint(
            "operation_id", "lot_id", "location_id", name="uq_fp_stock_movement_location"
        ),
        CheckConstraint("quantity <> 0", name="ck_fp_stock_movement_quantity"),
        ForeignKeyConstraint(
            ["venue_id", "operation_id"],
            ["fp_stock_operations.venue_id", "fp_stock_operations.id"],
            name="fk_fp_stock_movement_operation",
        ),
        ForeignKeyConstraint(
            ["venue_id", "lot_id"],
            ["fp_stock_lots.venue_id", "fp_stock_lots.id"],
            name="fk_fp_stock_movement_lot",
        ),
        ForeignKeyConstraint(
            ["venue_id", "location_id"],
            ["fp_stock_locations.venue_id", "fp_stock_locations.id"],
            name="fk_fp_stock_movement_location",
        ),
    )
    venue_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("fp_venues.id"), index=True)
    operation_id: Mapped[uuid.UUID] = mapped_column(index=True)
    lot_id: Mapped[uuid.UUID] = mapped_column(index=True)
    location_id: Mapped[uuid.UUID] = mapped_column()
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 6))
