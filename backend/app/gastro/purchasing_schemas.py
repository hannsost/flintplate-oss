from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import Field, JsonValue, model_validator

from app.gastro.inventory_schemas import (
    BookingInput,
    InventoryInput,
    InventoryRead,
    PositiveQuantity,
    Quantity,
    Unit,
)
from app.gastro.purchasing_terms_schemas import ProductConditions, SupplierTermsRead


class SupplierInput(InventoryInput):
    name: str = Field(min_length=2, max_length=120)
    reference: str = Field(default="", max_length=120)
    contact: str = Field(default="", max_length=200)


class SupplierRead(SupplierInput, InventoryRead):
    pass


class PriceTerms(InventoryInput):
    conditions: ProductConditions = Field(default_factory=ProductConditions)
    effective_on: date
    pack_price_cents: int = Field(ge=0, le=100000000)
    tax_rate_bps: int = Field(ge=0, le=10000)

    @model_validator(mode="after")
    def valid_base_price(self) -> PriceTerms:
        if (
            self.conditions.tiers
            and self.conditions.tiers[0].pack_price_cents > self.pack_price_cents
        ):
            raise ValueError("Staffelpreis darf den Basispreis nicht übersteigen.")
        return self


class CatalogInput(PriceTerms):
    supplier_id: uuid.UUID
    item_id: uuid.UUID
    supplier_sku: str = Field(min_length=1, max_length=80)
    pack_name: str = Field(min_length=1, max_length=80)
    pack_quantity: PositiveQuantity


class PriceInput(PriceTerms):
    product_id: uuid.UUID
    expected_version: int = Field(ge=1)


class PriceRead(PriceTerms, InventoryRead):
    product_id: uuid.UUID
    version: int


class CatalogRead(InventoryRead):
    supplier_id: uuid.UUID
    item_id: uuid.UUID
    supplier_sku: str
    pack_name: str
    pack_quantity: Decimal
    version: int
    current_price: PriceRead | None
    prices: list[PriceRead]


class OrderLineInput(InventoryInput):
    product_id: uuid.UUID
    price_id: uuid.UUID
    packs: int = Field(ge=1, le=1000000)


class PurchaseOrderInput(BookingInput):
    supplier_terms_id: uuid.UUID | None = None
    supplier_id: uuid.UUID
    owner_id: uuid.UUID
    location_id: uuid.UUID
    expected_on: date | None = None
    lines: list[OrderLineInput] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def distinct_products(self) -> PurchaseOrderInput:
        if len({line.product_id for line in self.lines}) != len(self.lines):
            raise ValueError("Jeden Lieferartikel nur einmal aufnehmen.")
        return self


class OrderStateInput(InventoryInput):
    version: int = Field(ge=1)
    status: Literal["ordered", "closed", "cancelled"]
    reason: str = Field(min_length=3, max_length=300)


class PurchaseLineRead(InventoryRead):
    product_id: uuid.UUID
    item_id: uuid.UUID
    price_id: uuid.UUID
    item_name: str
    unit: Unit
    supplier_sku: str
    pack_name: str
    pack_quantity: Decimal
    packs: int
    ordered_quantity: Decimal
    ordered_bonus_quantity: Decimal
    received_bonus_quantity: Decimal
    remaining_bonus_quantity: Decimal
    billable_received_quantity: Decimal
    conditions_snapshot: ProductConditions
    received_quantity: Decimal
    rejected_quantity: Decimal
    remaining_quantity: Decimal
    pack_price_cents: int
    tax_rate_bps: int
    net_cents: int


class PurchaseReceiptInput(BookingInput):
    confirmation_id: uuid.UUID | None = None
    unconfirmed_delivery_reason: str = Field(default="", max_length=300)
    line_id: uuid.UUID
    accepted_quantity: Quantity
    rejected_quantity: Quantity = Decimal(0)
    accepted_bonus_quantity: Quantity = Decimal(0)
    rejected_bonus_quantity: Quantity = Decimal(0)
    rejection_reason: str = Field(default="", max_length=300)
    location_id: uuid.UUID
    lot_code: str = Field(min_length=1, max_length=100)
    expires_on: date | None = None
    blocked: bool = False
    reference: str = Field(min_length=1, max_length=120)

    @model_validator(mode="after")
    def actual_delivery(self) -> PurchaseReceiptInput:
        if (
            self.accepted_bonus_quantity > self.accepted_quantity
            or self.rejected_bonus_quantity > self.rejected_quantity
        ):
            raise ValueError("Der Gratisanteil muss in der jeweiligen Gesamtmenge enthalten sein.")
        if self.accepted_quantity + self.rejected_quantity <= 0:
            raise ValueError("Mindestens eine angenommene oder abgelehnte Menge ist erforderlich.")
        if self.rejected_quantity and len(self.rejection_reason.strip()) < 3:
            raise ValueError("Die abgelehnte Menge benötigt eine Begründung.")
        return self


class PurchaseReceiptRead(InventoryRead):
    confirmation_id: uuid.UUID | None
    accepted_bonus_quantity: Decimal
    rejected_bonus_quantity: Decimal
    line_id: uuid.UUID
    stock_operation_id: uuid.UUID | None
    request_key: uuid.UUID
    accepted_quantity: Decimal
    rejected_quantity: Decimal
    reference: str
    rejection_reason: str
    details: dict[str, JsonValue]


class PurchaseOrderRead(InventoryRead):
    supplier_terms_id: uuid.UUID | None
    supplier_terms_snapshot: dict[str, JsonValue]
    earliest_delivery_on: date | None
    shortfall_to_minimum_net_cents: int
    supplier_id: uuid.UUID
    owner_id: uuid.UUID
    location_id: uuid.UUID
    number: str
    status: str
    version: int
    request_key: uuid.UUID
    expected_on: date | None
    currency: str
    note: str
    lines: list[PurchaseLineRead]
    receipts: list[PurchaseReceiptRead]
    net_cents: int
    tax_cents: int
    total_cents: int


class InvoiceLineInput(InventoryInput):
    purchase_line_id: uuid.UUID
    quantity: PositiveQuantity
    net_cents: int = Field(ge=0, le=100000000)
    tax_rate_bps: int = Field(ge=0, le=10000)


class InvoiceInput(BookingInput):
    supplier_id: uuid.UUID
    number: str = Field(min_length=1, max_length=80)
    issued_on: date
    lines: list[InvoiceLineInput] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def distinct_lines(self) -> InvoiceInput:
        if len({line.purchase_line_id for line in self.lines}) != len(self.lines):
            raise ValueError("Jede Bestellposition nur einmal abrechnen.")
        return self


class InvoiceDecision(InventoryInput):
    version: int = Field(ge=1)
    status: Literal["approved", "rejected"]
    reason: str = Field(min_length=3, max_length=300)


class InvoiceLineCheck(InvoiceLineInput):
    received_bonus_quantity: Decimal = Decimal(0)
    item_name: str
    unit: Unit
    expected_net_cents: int
    received_quantity: Decimal
    already_invoiced_quantity: Decimal
    differences: list[str]


class InvoiceCheck(InventoryInput):
    matched: bool
    lines: list[InvoiceLineCheck]
    net_cents: int
    tax_cents: int
    total_cents: int


class PurchaseInvoiceRead(InventoryRead):
    supplier_id: uuid.UUID
    number: str
    issued_on: date
    currency: str
    status: str
    version: int
    decision_reason: str
    check: InvoiceCheck


class PurchasingSnapshot(InventoryInput):
    supplier_terms: list[SupplierTermsRead]
    business_date: date
    suppliers: list[SupplierRead]
    catalog: list[CatalogRead]
    orders: list[PurchaseOrderRead]
    invoices: list[PurchaseInvoiceRead]
