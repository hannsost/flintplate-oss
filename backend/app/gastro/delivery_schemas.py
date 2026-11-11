"""Full replacement statements and their evidenced remaining incoming quantity."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import Field, model_validator

from app.gastro.inventory_schemas import BookingInput, InventoryRead, Quantity


class DeliveryInput(BookingInput):
    line_id: uuid.UUID
    expected_version: int = Field(ge=0)
    status: Literal["confirmed", "cancelled"] = "confirmed"
    expected_on: date
    paid_quantity: Quantity
    bonus_quantity: Quantity = Decimal(0)
    reference: str = Field(min_length=3, max_length=120)

    @model_validator(mode="after")
    def quantities(self) -> DeliveryInput:
        if (self.paid_quantity + self.bonus_quantity > 0) != (self.status == "confirmed"):
            raise ValueError(
                "Bestätigung benötigt eine Menge; Absage benötigt null verbleibende Menge."
            )
        return self


class DeliveryRead(InventoryRead):
    line_id: uuid.UUID
    previous_id: uuid.UUID | None
    version: int
    status: str
    expected_on: date
    paid_quantity: Decimal
    bonus_quantity: Decimal
    reference: str
    reason: str
    order_id: uuid.UUID
    supplier_id: uuid.UUID
    owner_id: uuid.UUID
    item_id: uuid.UUID
    unit: str
    current: bool
    remaining_paid_quantity: Decimal
    remaining_bonus_quantity: Decimal
    remaining_physical_quantity: Decimal
    rejected_quantity: Decimal
    reliable_for_planning: bool
    conflicts: list[str]
