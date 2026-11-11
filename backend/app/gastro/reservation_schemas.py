from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import Field

from app.gastro.inventory_schemas import BookingInput, InventoryRead, PositiveQuantity


class ReservationInput(BookingInput):
    lot_id: uuid.UUID
    location_id: uuid.UUID
    quantity: PositiveQuantity
    duration_minutes: int = Field(ge=1, le=525600)


class ReservationCloseInput(BookingInput):
    kind: Literal["release", "consume"]
    usage_reference: str = Field(default="", max_length=120)


class ScopedReservationCloseInput(ReservationCloseInput):
    reservation_id: uuid.UUID


ReservationStatus = Literal["active", "undercovered", "expired", "released", "consumed"]


class ReservationRead(InventoryRead):
    lot_id: uuid.UUID
    location_id: uuid.UUID
    quantity: Decimal
    expires_at: datetime
    actor_id: uuid.UUID
    reason: str
    status: ReservationStatus
    covered_quantity: Decimal
    shortfall_quantity: Decimal
    blocked: bool
    lot_expired: bool
    consumable: bool
    closure_id: uuid.UUID | None
    stock_operation_id: uuid.UUID | None
    closed_at: datetime | None
    closed_by: uuid.UUID | None
    closure_reason: str
