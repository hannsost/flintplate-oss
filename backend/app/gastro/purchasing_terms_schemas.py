"""Explicit supplier conditions; decimal physical quantities stay separate from money."""

from __future__ import annotations

import uuid
from datetime import date, datetime, time
from decimal import Decimal
from typing import Literal

from pydantic import Field, model_validator

from app.gastro.inventory_schemas import BookingInput, InventoryInput, InventoryRead
from app.gastro.purchasing_bonus_schemas import (
    BonusAllocationReversalRead,
    BonusDocumentRevisionRead,
)


class PriceTier(InventoryInput):
    minimum_paid_packs: int = Field(ge=1, le=1000000)
    pack_price_cents: int = Field(ge=0, le=100000000)


class NaturalRebate(InventoryInput):
    buy_packs: int = Field(ge=1, le=1000000)
    free_packs: int = Field(ge=1, le=1000000)


class ProductConditions(InventoryInput):
    schema_version: Literal[1] = 1
    minimum_paid_packs: int = Field(default=1, ge=1, le=1000000)
    order_multiple: int = Field(default=1, ge=1, le=1000000)
    tier_mode: Literal["all_units"] = "all_units"
    tiers: list[PriceTier] = Field(default_factory=list, max_length=30)
    natural_rebate: NaturalRebate | None = None

    @model_validator(mode="after")
    def ordered_tiers(self) -> ProductConditions:
        boundaries = [tier.minimum_paid_packs for tier in self.tiers]
        if boundaries != sorted(set(boundaries)):
            raise ValueError("Staffelgrenzen müssen eindeutig und aufsteigend sein.")
        if any(
            left.pack_price_cents < right.pack_price_cents
            for left, right in zip(self.tiers, self.tiers[1:], strict=False)
        ):
            raise ValueError("Staffelpreise dürfen mit wachsender Menge nicht steigen.")
        if (
            (self.minimum_paid_packs + self.order_multiple - 1) // self.order_multiple
        ) * self.order_multiple > 1000000:
            raise ValueError("Mindestmenge und Vielfaches erlauben keine gültige Bestellung.")
        return self


class SupplierRules(InventoryInput):
    minimum_order_net_cents: int = Field(default=0, ge=0, le=1000000000)
    lead_time_calendar_days: int = Field(default=0, ge=0, le=365)
    delivery_weekdays: list[int] = Field(
        default_factory=lambda: list(range(7)), min_length=1, max_length=7
    )
    excluded_delivery_dates: list[date] = Field(default_factory=list, max_length=366)
    order_cutoff_local: time | None = None

    @model_validator(mode="after")
    def calendar(self) -> SupplierRules:
        if any(day not in range(7) for day in self.delivery_weekdays) or len(
            set(self.delivery_weekdays)
        ) != len(self.delivery_weekdays):
            raise ValueError("Liefertage müssen eindeutige Wochentage von 0 bis 6 sein.")
        if len(set(self.excluded_delivery_dates)) != len(self.excluded_delivery_dates):
            raise ValueError("Ausgeschlossene Liefertage dürfen nicht doppelt vorkommen.")
        if self.order_cutoff_local and self.order_cutoff_local.tzinfo is not None:
            raise ValueError("Bestellschluss wird in der Betriebszeitzone angegeben.")
        self.delivery_weekdays.sort()
        self.excluded_delivery_dates.sort()
        return self


class SupplierTermsInput(BookingInput):
    supplier_id: uuid.UUID
    expected_version: int = Field(ge=0)
    effective_on: date
    rules: SupplierRules


class SupplierTermsRead(InventoryRead):
    supplier_id: uuid.UUID
    version: int
    effective_on: date
    rules: SupplierRules


class QuoteLineInput(InventoryInput):
    product_id: uuid.UUID
    price_id: uuid.UUID
    packs: int = Field(ge=1, le=1000000)


class QuoteInput(InventoryInput):
    supplier_id: uuid.UUID
    expected_on: date | None = None
    lines: list[QuoteLineInput] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def unique_lines(self) -> QuoteInput:
        if len({row.product_id for row in self.lines}) != len(self.lines):
            raise ValueError("Jeden Lieferartikel nur einmal aufnehmen.")
        return self


class QuoteLineRead(InventoryInput):
    product_id: uuid.UUID
    price_id: uuid.UUID
    packs: int
    bonus_packs: int
    paid_quantity: Decimal
    ordered_bonus_quantity: Decimal
    ordered_quantity: Decimal
    pack_price_cents: int
    net_cents: int
    conditions: ProductConditions


class QuoteRead(InventoryInput):
    supplier_id: uuid.UUID
    supplier_terms_id: uuid.UUID | None
    lines: list[QuoteLineRead]
    earliest_delivery_on: date | None
    shortfall_to_minimum_net_cents: int
    net_cents: int
    expected_delivery_feasible: bool | None
    fingerprint: str


class BonusAgreementInput(BookingInput):
    supplier_id: uuid.UUID
    reference: str = Field(min_length=1, max_length=120)
    period_start: date
    period_end: date
    source_basis: Literal["own_approved_invoice_net_before_credits"] = (
        "own_approved_invoice_net_before_credits"
    )
    rate_bps: int = Field(ge=1, le=10000)
    threshold_cents: int = Field(default=0, ge=0, le=1000000000000)
    mode: Literal["whole_base_at_threshold", "excess_only"] = "excess_only"

    @model_validator(mode="after")
    def period(self) -> BonusAgreementInput:
        if not 0 <= (self.period_end - self.period_start).days <= 1095:
            raise ValueError("Bonusperiode muss zwischen einem Tag und drei Jahren liegen.")
        return self


class BonusAgreementRead(BonusAgreementInput, InventoryRead):
    currency: str


class BonusSourceRead(InventoryInput):
    invoice_id: uuid.UUID
    purchase_line_id: uuid.UUID
    issued_on: date
    decided_at: datetime
    quantity: Decimal
    net_cents: int


class BonusPreview(InventoryInput):
    agreement_id: uuid.UUID
    currency: str
    period_start: date
    period_end: date
    sources: list[BonusSourceRead]
    source_net_cents: int
    claim_cents: int
    already_stated_cents: int
    delta_cents: int
    fingerprint: str
    blocking_reasons: list[str]


class BonusStatementInput(BookingInput):
    agreement_id: uuid.UUID
    fingerprint: str = Field(min_length=64, max_length=64)


class BonusStatementRead(InventoryRead):
    agreement_id: uuid.UUID
    sequence: int
    delta_cents: int
    snapshot: BonusPreview


class BonusDocumentInput(BookingInput):
    supplier_id: uuid.UUID
    reference: str = Field(min_length=1, max_length=120)
    issued_on: date
    net_cents: int = Field(gt=0, le=1000000000000)
    tax_cents: int = Field(ge=0, le=1000000000000)
    currency: str = Field(pattern=r"^[A-Z]{3}$")


class BonusDocumentRead(BonusDocumentInput, InventoryRead):
    original_issued_on: date
    original_net_cents: int
    original_tax_cents: int
    status: Literal["active", "void"] = "active"
    version: int = 1
    effective_revision_id: uuid.UUID | None = None
    allocated_cents: int
    remaining_cents: int


class BonusAllocationInput(BookingInput):
    document_id: uuid.UUID
    document_revision_id: uuid.UUID | None = None
    agreement_id: uuid.UUID
    amount_cents: int = Field(gt=0, le=1000000000000)


class BonusAllocationRead(BonusAllocationInput, InventoryRead):
    pass


class BonusBalance(InventoryInput):
    agreement_id: uuid.UUID
    claimed_cents: int
    allocated_cents: int
    remaining_cents: int


class BonusSnapshot(InventoryInput):
    document_revisions: list[BonusDocumentRevisionRead] = Field(default_factory=list)
    reversals: list[BonusAllocationReversalRead] = Field(default_factory=list)
    agreements: list[BonusAgreementRead]
    statements: list[BonusStatementRead]
    documents: list[BonusDocumentRead]
    allocations: list[BonusAllocationRead]
    balances: list[BonusBalance]
