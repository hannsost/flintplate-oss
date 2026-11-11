"""Pydantic schemas for Payroll (Sprint 4.10)."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field, model_validator

MONTH_NAMES = {
    1: "Januar",
    2: "Februar",
    3: "März",
    4: "April",
    5: "Mai",
    6: "Juni",
    7: "Juli",
    8: "August",
    9: "September",
    10: "Oktober",
    11: "November",
    12: "Dezember",
}


class PayStubCreate(BaseModel):
    worker_id: uuid.UUID
    period_year: int = Field(..., ge=2020, le=2099)
    period_month: int = Field(..., ge=1, le=12)
    gross_cents: int = Field(..., ge=0, le=2147483647)
    net_cents: int = Field(..., ge=0, le=2147483647)
    tax_cents: int = Field(0, ge=0, le=2147483647)
    social_security_cents: int = Field(0, ge=0, le=2147483647)
    hours_worked: Decimal | None = Field(None, ge=0, le=999999.99)
    overtime_hours: Decimal | None = Field(None, ge=0, le=999999.99)
    document_url: str | None = None
    notes: str | None = None

    @model_validator(mode="after")
    def net_lte_gross(self) -> PayStubCreate:
        if self.net_cents > self.gross_cents:
            raise ValueError("net_cents cannot exceed gross_cents")
        return self


class PayStubUpdate(BaseModel):
    gross_cents: int | None = Field(None, ge=0, le=2147483647)
    net_cents: int | None = Field(None, ge=0, le=2147483647)
    tax_cents: int | None = Field(None, ge=0, le=2147483647)
    social_security_cents: int | None = Field(None, ge=0, le=2147483647)
    hours_worked: Decimal | None = Field(None, ge=0, le=999999.99)
    overtime_hours: Decimal | None = Field(None, ge=0, le=999999.99)
    document_url: str | None = None
    notes: str | None = None


class PayStubRead(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    worker_id: uuid.UUID
    created_by: uuid.UUID | None
    period_year: int
    period_month: int
    period_label: str = ""
    gross_cents: int
    net_cents: int
    tax_cents: int
    social_security_cents: int
    hours_worked: Decimal | None
    overtime_hours: Decimal | None
    document_url: str | None
    notes: str | None
    status: str
    published_at: datetime | None
    created_at: datetime
    updated_at: datetime
    # Enriched
    worker_name: str | None = None
    worker_email: str = ""

    model_config = {"from_attributes": True}

    @model_validator(mode="after")
    def set_period_label(self) -> PayStubRead:
        self.period_label = (
            f"{MONTH_NAMES.get(self.period_month, str(self.period_month))} {self.period_year}"
        )
        return self
