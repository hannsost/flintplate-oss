"""Actual additive cash tips and their independently confirmed returns."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.gastro.cash_schemas import Input


class PayerTipRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    payment_group_id: uuid.UUID
    original_id: uuid.UUID | None
    kind: str
    amount_cents: int
    session_id: uuid.UUID
    currency: str
    payer_tab_id: uuid.UUID | None
    payer_label: str
    recipient_id: uuid.UUID | None
    reason: str
    created_at: datetime
    refunded_cents: int = 0
    refundable_cents: int = 0
    tip_run_id: uuid.UUID | None = None


class PayerTipReturnInput(Input):
    request_key: uuid.UUID
    session_id: uuid.UUID
    amount_cents: int = Field(ge=1, le=100000)
    reason: str = Field(min_length=3, max_length=300)
    confirmed: Literal[True]
