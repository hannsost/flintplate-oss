"""Persistent participant targets, independent from actual money receipts."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from app.gastro.cash_schemas import Input
from app.gastro.payment_schemas import PaymentBlocker, PaymentQuoteInput, PaymentScope, UnitAmount


class EqualParticipant(Input):
    payer_tab_id: uuid.UUID | None = None
    label: str = Field(default="", max_length=80)


class EqualPlanInput(Input):
    request_key: uuid.UUID
    selection: PaymentQuoteInput
    participants: list[EqualParticipant] = Field(min_length=2, max_length=100)
    quote_hash: str = Field(min_length=64, max_length=64)
    supersedes_id: uuid.UUID | None = None
    reason: str = Field(default="", max_length=300)

    @model_validator(mode="after")
    def ordinary_selection(self) -> EqualPlanInput:
        if self.selection.mode not in {"all", "amount", "units"} or self.selection.new_tip_cents:
            raise ValueError("Plan verteilt ausschließlich ausgewählte vorhandene Bonforderungen.")
        if self.supersedes_id is not None and len(self.reason) < 3:
            raise ValueError("Neue Restaufteilung begründen.")
        guests = [p.payer_tab_id for p in self.participants if p.payer_tab_id is not None]
        if len(guests) != len(set(guests)):
            raise ValueError("Gastkonto nicht mehrfach als Planperson verwenden.")
        return self


class EqualPartRead(BaseModel):
    id: uuid.UUID
    ordinal: int
    payer_tab_id: uuid.UUID | None
    label: str
    target_cents: int
    paid_cents: int
    remaining_cents: int
    unit_budgets: list[UnitAmount]


class EqualPlanRead(BaseModel):
    id: uuid.UUID
    root_plan_id: uuid.UUID
    revision: int
    created_at: datetime
    currency: str
    source_hash: str
    source_scope: PaymentScope
    source_order_ids: list[uuid.UUID]
    total_cents: int
    paid_cents: int
    remaining_cents: int
    status: Literal["open", "paid", "stale", "abandoned", "superseded"]
    next_plan_id: uuid.UUID | None
    parts: list[EqualPartRead]
    blockers: list[PaymentBlocker]


class EqualActionInput(Input):
    request_key: uuid.UUID
    action: Literal["abandon"] = "abandon"
    reason: str = Field(min_length=3, max_length=300)
