"""Decimal quantities are serialized as strings to retain their exact value."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, JsonValue, model_validator


def normalized(value: Decimal) -> Decimal:
    return value.normalize()


Quantity = Annotated[
    Decimal, Field(ge=0, le=999999999, max_digits=18, decimal_places=6), AfterValidator(normalized)
]
PositiveQuantity = Annotated[
    Decimal, Field(gt=0, le=999999999, max_digits=18, decimal_places=6), AfterValidator(normalized)
]
Unit = Literal["kg", "l", "piece"]
OperationKind = Literal[
    "receipt", "transfer", "waste", "count", "quarantine", "production", "consume", "return"
]


class InventoryInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ItemInput(InventoryInput):
    sku: str = Field(min_length=1, max_length=60, pattern=r"^[A-Za-z0-9._-]+$")
    name: str = Field(min_length=2, max_length=120)
    unit: Unit
    requires_expiry: bool = False
    minimum_quantity: Quantity = Decimal(0)

    @model_validator(mode="after")
    def whole_pieces(self) -> ItemInput:
        if self.unit == "piece" and self.minimum_quantity % 1:
            raise ValueError("Stückartikel benötigen eine ganze Mindestmenge.")
        return self


class OwnerInput(InventoryInput):
    name: str = Field(min_length=2, max_length=120)
    kind: Literal["own", "partner"]
    reference: str = Field(default="", max_length=120)


class LocationInput(InventoryInput):
    name: str = Field(min_length=2, max_length=120)


class InventoryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    created_at: datetime


class ItemRead(ItemInput, InventoryRead):
    pass


class OwnerRead(OwnerInput, InventoryRead):
    pass


class LocationRead(LocationInput, InventoryRead):
    pass


class LotRead(InventoryRead):
    item_id: uuid.UUID
    owner_id: uuid.UUID
    code: str
    expires_on: date | None
    blocked: bool
    version: int


class BookingInput(InventoryInput):
    request_key: uuid.UUID
    reason: str = Field(min_length=3, max_length=300)


class ReceiptInput(BookingInput):
    item_id: uuid.UUID
    owner_id: uuid.UUID
    location_id: uuid.UUID
    lot_code: str = Field(min_length=1, max_length=100)
    expires_on: date | None = None
    blocked: bool = False
    quantity: PositiveQuantity
    reference: str = Field(min_length=1, max_length=120)


class TransferInput(BookingInput):
    lot_id: uuid.UUID
    source_location_id: uuid.UUID
    destination_location_id: uuid.UUID
    quantity: PositiveQuantity

    @model_validator(mode="after")
    def distinct_locations(self) -> TransferInput:
        if self.source_location_id == self.destination_location_id:
            raise ValueError("Quelle und Ziel müssen verschiedene Lagerorte sein.")
        return self


class WasteInput(BookingInput):
    lot_id: uuid.UUID
    location_id: uuid.UUID
    quantity: PositiveQuantity


class CountInput(BookingInput):
    lot_id: uuid.UUID
    location_id: uuid.UUID
    counted_quantity: Quantity
    expected_quantity: Quantity


class QuarantineInput(BookingInput):
    blocked: bool
    version: int = Field(ge=1)


class LotQuarantineInput(QuarantineInput):
    lot_id: uuid.UUID


class MovementRead(InventoryRead):
    lot_id: uuid.UUID
    location_id: uuid.UUID
    quantity: Decimal


class OperationRead(InventoryRead):
    sequence: int
    request_key: uuid.UUID
    kind: OperationKind
    actor_id: uuid.UUID
    reason: str
    details: dict[str, JsonValue]
    movements: list[MovementRead]


class BalanceRead(BaseModel):
    lot_id: uuid.UUID
    item_id: uuid.UUID
    owner_id: uuid.UUID
    location_id: uuid.UUID
    quantity: Decimal
    expires_on: date | None
    expired: bool
    blocked: bool
    available_quantity: Decimal
    reserved_quantity: Decimal
    reservation_shortfall_quantity: Decimal


class InventorySnapshot(BaseModel):
    business_date: date
    items: list[ItemRead]
    owners: list[OwnerRead]
    locations: list[LocationRead]
    lots: list[LotRead]
    balances: list[BalanceRead]
