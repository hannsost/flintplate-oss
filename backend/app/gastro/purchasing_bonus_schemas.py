"""Append-only corrections to recorded supplier bonus evidence."""

from __future__ import annotations

import uuid
from datetime import date
from typing import Literal

from pydantic import Field, model_validator

from app.gastro.inventory_schemas import BookingInput, InventoryRead


class BonusDocumentRevisionInput(BookingInput):
    expected_version: int = Field(ge=1)
    kind: Literal["corrected", "void"]
    issued_on: date | None = None
    net_cents: int | None = Field(default=None, gt=0, le=1000000000000)
    tax_cents: int | None = Field(default=None, ge=0, le=1000000000000)

    @model_validator(mode="after")
    def complete_revision(self) -> BonusDocumentRevisionInput:
        values = (self.issued_on, self.net_cents, self.tax_cents)
        if self.kind == "corrected" and any(value is None for value in values):
            raise ValueError("Korrektur benötigt Belegdatum, Nettobetrag und Steuerbetrag.")
        if self.kind == "void" and any(value is not None for value in values):
            raise ValueError("Beim Verwerfen bleiben die bisherigen Belegwerte erhalten.")
        return self


class ScopedBonusDocumentRevisionInput(BonusDocumentRevisionInput):
    document_id: uuid.UUID


class BonusDocumentRevisionRead(BookingInput, InventoryRead):
    document_id: uuid.UUID
    previous_revision_id: uuid.UUID | None
    version: int
    kind: Literal["corrected", "void"]
    issued_on: date
    net_cents: int
    tax_cents: int
    actor_id: uuid.UUID


class ScopedBonusReversalInput(BookingInput):
    allocation_id: uuid.UUID


class BonusAllocationReversalRead(BookingInput, InventoryRead):
    allocation_id: uuid.UUID
    document_id: uuid.UUID
    document_revision_id: uuid.UUID | None
    agreement_id: uuid.UUID
    amount_cents: int
    actor_id: uuid.UUID
