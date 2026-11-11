"""The original receipt and the reviewed cancellation are separate documents."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator


class CancellationInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class CancellationSelection(CancellationInput):
    line_id: uuid.UUID
    quantity: int = Field(ge=1, le=99)


class CancellationPreviewInput(CancellationInput):
    version: int = Field(ge=1)
    whole_order: bool = False
    include_tip: bool = False
    lines: list[CancellationSelection] = Field(default_factory=list, max_length=100)
    reason_code: Literal["entry_error", "guest_request", "quality", "unavailable", "other"]
    note: str = Field(min_length=3, max_length=500)

    @model_validator(mode="after")
    def selection_valid(self) -> Self:
        if self.whole_order and self.lines:
            raise ValueError("Gesamtbon oder einzelne Positionen wählen.")
        if not self.whole_order and not self.lines and not self.include_tip:
            raise ValueError("Mindestens eine Position auswählen.")
        if len({line.line_id for line in self.lines}) != len(self.lines):
            raise ValueError("Eine Position darf nur einmal ausgewählt werden.")
        return self


class CancellationCreateInput(CancellationPreviewInput):
    request_key: uuid.UUID
    preview_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    approve: bool = False


class CancellationDecisionInput(CancellationInput):
    request_key: uuid.UUID
    version: int = Field(ge=1)
    preview_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    decision: Literal["approve", "reject"]
    note: str = Field(min_length=3, max_length=500)


class CancellationAckInput(CancellationInput):
    request_key: uuid.UUID


class CancellationLineRead(BaseModel):
    line_index: int = -1
    line_id: uuid.UUID
    name: str
    quantity: int
    units: list[int]
    preparation_status: str
    station: str
    kind: str
    gross_cents: int
    tax_cents: int
    stock_effect: Literal["not_consumed", "consumption_retained"]


class CancellationPreviewRead(BaseModel):
    order_id: uuid.UUID
    order_number: str
    order_version: int
    preview_hash: str
    lines: list[CancellationLineRead]
    gross_cents: int
    tax_cents: int
    money: dict[str, JsonValue]
    warnings: list[str]


class CancellationDecisionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    actor_id: uuid.UUID
    decision: Literal["approve", "reject"]
    note: str
    self_approved: bool
    created_at: datetime


class CancellationAckRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    execution_id: uuid.UUID
    actor_id: uuid.UUID
    created_at: datetime


class CancellationExecutionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    order_id: uuid.UUID
    order_number: str
    actor_id: uuid.UUID
    reason_code: str
    note: str
    order_version: int
    result_version: int
    lines: list[CancellationLineRead]
    money: dict[str, JsonValue]
    checkout_reconciliation_required: bool
    kitchen_required: bool
    created_at: datetime
    acknowledgement: CancellationAckRead | None = None


class CancellationRequestRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    order_id: uuid.UUID
    order_number: str
    requester_id: uuid.UUID
    original_actor_id: uuid.UUID | None
    order_version: int
    reason_code: str
    note: str
    source: str
    created_at: datetime
    preview: CancellationPreviewRead
    decision: CancellationDecisionRead | None = None
    execution: CancellationExecutionRead | None = None


class CancelledUnitRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    execution_id: uuid.UUID
    line_id: uuid.UUID
    unit: int
    gross_cents: int
    tax_cents: int
