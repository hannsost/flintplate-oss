from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class RegisterInput(Input):
    name: str = Field(min_length=1, max_length=80)


class RegisterRead(RegisterInput):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID


class OpenSession(Input):
    request_key: uuid.UUID
    register_id: uuid.UUID
    operator_id: uuid.UUID
    opening_cents: int = Field(ge=0, le=100000000)


class SessionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    register_id: uuid.UUID
    operator_id: uuid.UUID
    status: str
    version: int
    created_at: datetime
    counted_cents: int | None
    expected_cents: int | None
    difference_cents: int | None
    count_reason: str
    closed_at: datetime | None


class MovementInput(Input):
    request_key: uuid.UUID
    amount_cents: int = Field(ge=-100000000, le=100000000)
    reason: str = Field(min_length=3, max_length=300)

    @model_validator(mode="after")
    def nonzero(self) -> MovementInput:
        if not self.amount_cents:
            raise ValueError("Betrag darf nicht null sein.")
        return self


class CountInput(Input):
    request_key: uuid.UUID
    version: int = Field(ge=1)
    counted_cents: int = Field(ge=0, le=100000000)
    reason: str = Field(default="", max_length=300)


class CloseInput(Input):
    version: int = Field(ge=1)
    reason: str = Field(default="", max_length=300)


class ItemSelection(Input):
    line_id: uuid.UUID
    quantity: int = Field(ge=1, le=99)


class CashPaymentInput(Input):
    request_key: uuid.UUID
    version: int = Field(ge=1)
    session_id: uuid.UUID
    mode: Literal["amount", "equal", "items"] = "amount"
    amount_cents: int | None = Field(default=None, ge=0, le=100000000)
    people: int | None = Field(default=None, ge=1, le=100)
    items: list[ItemSelection] = Field(default_factory=list, max_length=100)
    tip_cents: int = Field(default=0, ge=0, le=100000)
    payer: str = Field(default="", max_length=80)
    received_cents: int | None = Field(default=None, ge=0, le=100000000)

    @model_validator(mode="after")
    def split_input(self) -> CashPaymentInput:
        if self.mode == "amount" and self.amount_cents is None:
            raise ValueError("Teilbetrag erforderlich.")
        if self.mode == "equal" and self.people is None:
            raise ValueError("Anzahl verbleibender Personen erforderlich.")
        if self.mode == "items" and not self.items and not self.tip_cents:
            raise ValueError("Mindestens eine Position oder Trinkgeld auswählen.")
        if len({line.line_id for line in self.items}) != len(self.items):
            raise ValueError("Positionen nur einmal auswählen.")
        return self


class RefundInput(Input):
    request_key: uuid.UUID
    amount_cents: int = Field(ge=1, le=100000000)
    session_id: uuid.UUID | None = None
    reason: str = Field(min_length=3, max_length=300)
    cancellation_id: uuid.UUID | None = None
    confirmed: bool = False


class ExternalRefundInput(Input):
    request_key: uuid.UUID
    original_id: uuid.UUID
    amount_cents: int = Field(ge=1, le=100000000)
    reference: str = Field(min_length=1, max_length=160)
    reason: str = Field(min_length=3, max_length=300)
    cancellation_id: uuid.UUID | None = None
    cancellation_version: int | None = Field(default=None, ge=1)
    confirmed: bool = False


class CheckoutCorrectionInput(Input):
    request_key: uuid.UUID
    version: int = Field(ge=1)
    cancellation_version: int = Field(ge=1)
    remaining_cents: int = Field(ge=0)
    cancelled_cents: int = Field(ge=0)
    reference: str = Field(min_length=1, max_length=160)
    confirmed: Literal[True]
    no_pending_payments: Literal[True]


class CheckoutCorrectionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    execution_id: uuid.UUID
    order_id: uuid.UUID
    device_id: uuid.UUID
    reference: str
    created_at: datetime


class RefundClaimRead(BaseModel):
    cancellation_id: uuid.UUID
    original_id: uuid.UUID
    method: str
    amount_cents: int
    tax_cents: int
    refunded_cents: int
    remaining_cents: int
    allocations: list[dict[str, JsonValue]]


class EntryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    session_id: uuid.UUID | None
    order_id: uuid.UUID | None
    original_id: uuid.UUID | None
    kind: str
    method: str
    amount_cents: int
    received_cents: int | None
    change_cents: int | None
    allocations: list[dict[str, JsonValue]]
    payer: str
    reason: str
    external_reference: str | None
    created_at: datetime


class BalanceLine(BaseModel):
    line_id: uuid.UUID
    name: str
    kind: str
    remaining_quantity: int
    remaining_cents: int
    cancelled_quantity: int = 0
    cancelled_cents: int = 0


class BalanceRead(BaseModel):
    order_id: uuid.UUID
    version: int
    total_cents: int
    voucher_cents: int
    tip_cents: int
    paid_cents: int
    remaining_cents: int
    remaining_tip_cents: int
    refunded_cents: int
    lines: list[BalanceLine]
    entries: list[EntryRead]
    corrected_total_cents: int = 0
    cancelled_cents: int = 0
    unpaid_credit_cents: int = 0
    refund_due_cents: int = 0
    refund_claims: list[RefundClaimRead] = Field(default_factory=list)
    checkout_blocked: bool = False
    cancellation_version: int | None = None
    historical_cancelled: bool = False


class ReconciliationRead(BaseModel):
    day: str
    receipts: dict[str, int]
    refunds: dict[str, int]
    tip_cents: int
    tax_cents: int
    open_sessions: int
    differences_cents: int
