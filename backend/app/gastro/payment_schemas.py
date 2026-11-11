"""Exact original-unit cash selections; no provider charge is requested here."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from app.gastro.cash_schemas import EntryRead, Input


class PaymentScope(Input):
    visit_id: uuid.UUID | None = None
    guest_tab_ids: list[uuid.UUID] = Field(default_factory=list, max_length=100)
    order_ids: list[uuid.UUID] = Field(default_factory=list, max_length=50)

    @model_validator(mode="after")
    def one_scope(self) -> PaymentScope:
        if sum((self.visit_id is not None, bool(self.guest_tab_ids), bool(self.order_ids))) > 1:
            raise ValueError("Genau einen Besuchs-, Gäste- oder Bonbereich wählen.")
        if len(set(self.guest_tab_ids)) != len(self.guest_tab_ids) or len(
            set(self.order_ids)
        ) != len(self.order_ids):
            raise ValueError("Gäste und Bons nur einmal auswählen.")
        return self


class UnitAmount(Input):
    order_id: uuid.UUID
    line_id: str
    unit: int = Field(ge=0, le=1000000)
    amount_cents: int | None = Field(default=None, ge=1, le=100000000)

    @model_validator(mode="after")
    def identity(self) -> UnitAmount:
        if self.line_id != "tip":
            self.line_id = str(uuid.UUID(self.line_id))
        elif self.unit != 0:
            raise ValueError("Bontrinkgeld besitzt nur Einheit 0.")
        return self


class PaymentQuoteInput(Input):
    scope: PaymentScope = Field(default_factory=PaymentScope)
    mode: Literal["all", "amount", "units", "parts", "tip_only"] = "all"
    units: list[UnitAmount] = Field(default_factory=list, max_length=1000)
    part_ids: list[uuid.UUID] = Field(default_factory=list, max_length=100)
    amount_cents: int | None = Field(default=None, ge=1, le=100000000)
    new_tip_cents: int = Field(default=0, ge=0, le=100000)
    recipient_id: uuid.UUID | None = None
    payer_tab_id: uuid.UUID | None = None
    payer_label: str = Field(default="", max_length=80)

    @model_validator(mode="after")
    def selection(self) -> PaymentQuoteInput:
        scoped = self.scope.visit_id is not None or bool(
            self.scope.guest_tab_ids or self.scope.order_ids
        )
        if self.mode == "tip_only":
            if (
                scoped
                or self.units
                or self.part_ids
                or self.amount_cents
                or not self.new_tip_cents
                or self.payer_tab_id is None
            ):
                raise ValueError(
                    "Nur-Trinkgeld benötigt Gastkontext, positiven Tip und keine Bon-/Planauswahl."
                )
        elif self.mode == "parts":
            if not self.part_ids or scoped or self.units:
                raise ValueError("Plananteile ohne zusätzliche Bon-/Gastauswahl angeben.")
        elif not scoped:
            raise ValueError("Besuch, Gäste oder Originalbons auswählen.")
        if self.mode == "units" and not self.units:
            raise ValueError("Konkrete Originaleinheiten auswählen.")
        if self.mode != "units" and self.units:
            raise ValueError("Einheiten nur im Positionsmodus angeben.")
        if self.mode != "parts" and self.part_ids:
            raise ValueError("Plananteile nur im Planmodus angeben.")
        if self.mode == "amount" and self.amount_cents is None:
            raise ValueError("Teilbetrag erforderlich.")
        if self.mode not in {"amount", "parts"} and self.amount_cents is not None:
            raise ValueError("Gesamtteilbetrag nur im Betrags-/Planmodus angeben.")
        if len(set(self.part_ids)) != len(self.part_ids) or len(
            {(u.order_id, u.line_id, u.unit) for u in self.units}
        ) != len(self.units):
            raise ValueError("Einheiten und Plananteile nur einmal auswählen.")
        return self


class PaymentBlocker(BaseModel):
    code: str
    message: str
    order_id: uuid.UUID | None = None


class PaymentUnitRead(BaseModel):
    order_id: uuid.UUID
    order_number: str
    line_id: str
    unit: int
    name: str
    kind: str
    gross_cents: int
    tax_cents: int
    paid_cents: int
    remaining_cents: int
    cancelled: bool
    guest_tab_id: uuid.UUID | None = None
    guest_label: str = "Nicht zugeordnet"
    assignment_id: uuid.UUID | None = None
    assignment_version: int | None = None


class PaymentOrderRead(BaseModel):
    order_id: uuid.UUID
    number: str
    version: int
    cancellation_version: int | None
    payment_status: str
    fulfillment_status: str
    remaining_cents: int
    refund_due_cents: int
    checkout_blocked: bool


class PaymentBalanceInput(Input):
    scope: PaymentScope
    before_order_id: uuid.UUID | None = None
    limit: int = Field(default=50, ge=1, le=50)


class PaymentBalanceRead(BaseModel):
    has_more: bool = False
    next_before_order_id: uuid.UUID | None = None
    page_totals: Literal[True] = True
    currency: str
    source_hash: str
    orders: list[PaymentOrderRead]
    units: list[PaymentUnitRead]
    remaining_cents: int
    refund_due_cents: int
    blockers: list[PaymentBlocker]


class PaymentAllocationRead(BaseModel):
    order_id: uuid.UUID
    line_id: str
    unit: int
    name: str
    kind: str
    amount_cents: int
    tax_cents: int


class PaymentQuoteRead(BaseModel):
    quote_hash: str
    source_hash: str
    currency: str
    orders: list[PaymentOrderRead]
    allocations: list[PaymentAllocationRead]
    receipt_amount_cents: int
    new_tip_cents: int
    amount_cents: int
    selected_remaining_cents: int
    payer_tab_id: uuid.UUID | None
    payer_label: str
    recipient_id: uuid.UUID | None
    blockers: list[PaymentBlocker]


class PaymentGroupInput(Input):
    request_key: uuid.UUID
    quote: PaymentQuoteInput
    quote_hash: str = Field(min_length=64, max_length=64)
    session_id: uuid.UUID
    received_cents: int = Field(ge=1, le=100000000)
    confirmed: Literal[True]


class PaymentGroupRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    created_at: datetime
    session_id: uuid.UUID
    currency: str
    payer_tab_id: uuid.UUID | None
    payer_label: str
    receipt_amount_cents: int
    new_tip_cents: int
    amount_cents: int
    received_cents: int
    change_cents: int
    quote_hash: str
    allocations: list[PaymentAllocationRead]
    entries: list[EntryRead]
    tip_entry_id: uuid.UUID | None
    part_payments: list[dict[str, JsonValue]]
