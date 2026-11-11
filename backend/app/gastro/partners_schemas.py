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
)


class PartnerRules(InventoryInput):
    revenue_basis: Literal["net", "gross"] = "net"
    share_bps: int = Field(default=0, ge=0, le=10000)
    revenue_threshold_cents: int = Field(default=0, ge=0, le=100000000)
    per_sale_cents: int = Field(default=0, ge=0, le=100000000)
    fixed_monthly_cents: int = Field(default=0, ge=-100000000, le=100000000)
    minimum_monthly_cents: int | None = Field(default=None, ge=0, le=100000000)
    loss_responsibility: Literal["venue", "partner"] = "partner"
    loss_per_stock_unit_cents: int = Field(default=0, ge=0, le=100000000)


class TermsInput(BookingInput):
    effective_on: date
    active: bool = True
    stock_per_sale: PositiveQuantity
    rules: PartnerRules

    @model_validator(mode="after")
    def month_boundary(self) -> TermsInput:
        if self.effective_on.day != 1:
            raise ValueError("Vertragsversionen gelten ab einem Monatsersten.")
        return self


class ContractInput(TermsInput):
    name: str = Field(min_length=2, max_length=120)
    owner_id: uuid.UUID
    item_id: uuid.UUID
    menu_item_id: uuid.UUID


class VersionInput(TermsInput):
    expected_version: int = Field(ge=1)


class TermsRead(InventoryRead):
    contract_id: uuid.UUID
    version: int
    effective_on: date
    active: bool
    stock_per_sale: Decimal
    rules: PartnerRules


class ContractRead(InventoryRead):
    name: str
    owner_id: uuid.UUID
    item_id: uuid.UUID
    menu_item_id: uuid.UUID
    currency: str
    terms: list[TermsRead]


class SaleInput(BookingInput):
    contract_id: uuid.UUID
    order_id: uuid.UUID
    line_id: uuid.UUID
    units: list[int] = Field(min_length=1, max_length=99)

    @model_validator(mode="after")
    def valid_units(self) -> SaleInput:
        if any(unit < 0 or unit > 98 for unit in self.units) or len(set(self.units)) != len(
            self.units
        ):
            raise ValueError("Verkaufseinheiten eindeutig mit Indizes 0 bis 98 angeben.")
        self.units.sort()
        return self


class RefundInput(BookingInput):
    contract_id: uuid.UUID
    cash_entry_id: uuid.UUID


class PartnerStockInput(BookingInput):
    contract_id: uuid.UUID
    lot_id: uuid.UUID
    location_id: uuid.UUID
    quantity: PositiveQuantity
    kind: Literal["return", "waste"]


class LossInput(BookingInput):
    contract_id: uuid.UUID
    stock_operation_id: uuid.UUID


class LossCandidate(InventoryInput):
    stock_operation_id: uuid.UUID
    owner_id: uuid.UUID
    item_id: uuid.UUID
    quantity: Decimal
    occurred_on: date
    reason: str


class EventRead(InventoryRead):
    contract_id: uuid.UUID
    terms_id: uuid.UUID
    original_id: uuid.UUID | None
    stock_operation_id: uuid.UUID | None
    order_id: uuid.UUID | None
    cash_entry_id: uuid.UUID | None
    line_id: uuid.UUID | None
    unit: int | None
    kind: str
    occurred_on: date
    source_month: date
    posting_month: date
    physical_quantity: Decimal
    gross_cents: int
    net_cents: int
    unit_fee_cents: int
    loss_cents: int
    evidence: list[dict[str, JsonValue]]


class PostingRead(InventoryRead):
    contract_id: uuid.UUID
    request_key: uuid.UUID
    kind: str
    events: list[EventRead]


class SettlementComponent(InventoryInput):
    source_month: date
    terms_id: uuid.UUID
    revenue_cents: int
    share_cents: int
    unit_fees_cents: int
    fixed_cents: int
    guarantee_topup_cents: int
    loss_cents: int
    calculated_payable_cents: int
    previously_settled_cents: int
    delta_cents: int
    event_ids: list[uuid.UUID]


class SettlementPreview(InventoryInput):
    contract_id: uuid.UUID
    month: date
    currency: str
    payable_to_partner_cents: int
    components: list[SettlementComponent]
    fingerprint: str


class SettlementInput(BookingInput):
    contract_id: uuid.UUID
    month: date
    fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")


class SettlementRead(InventoryRead):
    contract_id: uuid.UUID
    month: date
    payable_to_partner_cents: int
    snapshot: SettlementPreview
    reason: str


class LoanAccountInput(InventoryInput):
    owner_id: uuid.UUID
    name: str = Field(min_length=2, max_length=120)
    reference: str = Field(min_length=1, max_length=120)
    serialized: bool = False
    deposit_per_unit_cents: int = Field(default=0, ge=0, le=100000000)


class LoanEntryInput(BookingInput):
    account_id: uuid.UUID
    kind: Literal[
        "received", "returned", "broken", "deposit_paid", "deposit_refunded", "deposit_forfeited"
    ]
    quantity: int = Field(default=0, ge=0, le=1000000)
    amount_cents: int = Field(default=0, ge=0, le=100000000)
    cash_entry_id: uuid.UUID | None = None
    external_reference: str = Field(default="", max_length=160)

    @model_validator(mode="after")
    def separate_money_and_custody(self) -> LoanEntryInput:
        if self.kind in {"received", "returned", "broken"}:
            if (
                not self.quantity
                or self.amount_cents
                or self.cash_entry_id
                or self.external_reference
            ):
                raise ValueError(
                    "Bestandsbuchungen enthalten ausschließlich eine positive Stückzahl."
                )
        elif self.quantity or not self.amount_cents:
            raise ValueError("Pfandbuchungen enthalten ausschließlich einen positiven Geldbetrag.")
        elif self.kind == "deposit_forfeited":
            if self.cash_entry_id or not self.external_reference:
                raise ValueError("Pfandverfall benötigt einen Beleg, aber keinen Zahlungsvorgang.")
        elif bool(self.cash_entry_id) == bool(self.external_reference):
            raise ValueError("Genau einen Kassenbeleg oder externen Zahlungsnachweis angeben.")
        return self


class LoanEntryRead(InventoryRead):
    kind: str
    quantity: int
    amount_cents: int
    cash_entry_id: uuid.UUID | None
    external_reference: str
    reason: str


class LoanAccountRead(LoanAccountInput, InventoryRead):
    currency: str
    physical_quantity: int
    received_quantity: int
    returned_quantity: int
    broken_quantity: int
    deposit_claim_cents: int
    unpaid_deposit_cents: int
    refundable_deposit_cents: int
    entries: list[LoanEntryRead]


class PartnerSnapshot(InventoryInput):
    business_date: date
    contracts: list[ContractRead]
    events: list[EventRead]
    settlements: list[SettlementRead]
    loans: list[LoanAccountRead]
    unassigned_losses: list[LossCandidate]


class SaleCandidate(InventoryInput):
    contract_id: uuid.UUID
    line_id: uuid.UUID
    name: str
    units: list[int]
    gross_cents: int
    stock_quantity: Decimal


class RefundCandidate(InventoryInput):
    contract_id: uuid.UUID
    cash_entry_id: uuid.UUID
    gross_cents: int


class CandidateRead(InventoryInput):
    order_id: uuid.UUID
    sales: list[SaleCandidate]
    refunds: list[RefundCandidate]
    notes: list[str]
