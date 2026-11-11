from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator

Permission = Literal["read", "prepare", "approve", "issue", "export", "manage"]
PERMISSIONS: list[str] = ["read", "prepare", "approve", "issue", "export", "manage"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, allow_inf_nan=False)

    @field_validator("*", mode="before")
    @classmethod
    def xml_text(cls, value: object) -> object:
        if isinstance(value, str) and any(
            ord(c) < 32
            and c not in "\n\r\t"
            or 0xD800 <= ord(c) <= 0xDFFF
            or ord(c) in (0xFFFE, 0xFFFF)
            for c in value
        ):
            raise ValueError("Nicht unterstützte Steuerzeichen im Text.")
        return value


class Party(StrictModel):
    name: str = Field(min_length=2, max_length=200)
    street: str = Field(min_length=2, max_length=200)
    postal_code: str = Field(pattern=r"^[0-9]{5}$")
    city: str = Field(min_length=2, max_length=100)
    country: Literal["DE"] = "DE"
    email: EmailStr


class EntityInput(Party):
    vat_id: str = Field(pattern=r"^DE[0-9]{9}$")
    contact_name: str = Field(min_length=2, max_length=100)
    phone: str = Field(min_length=6, max_length=40)
    iban: str = Field(min_length=22, max_length=35)
    invoice_prefix: str = Field(pattern=r"^[A-Z][A-Z0-9]{1,9}$")
    four_eyes: bool = True

    @field_validator("iban")
    @classmethod
    def valid_iban(cls, value: str) -> str:
        value = value.replace(" ", "").upper()
        if len(value) != 22 or not value.startswith("DE") or not value[2:].isdigit():
            raise ValueError("Eine deutsche IBAN wird benötigt.")
        if int(value[4:] + "1314" + value[2:4]) % 97 != 1:
            raise ValueError("Die IBAN-Prüfsumme stimmt nicht.")
        return value


class EntityUpdate(EntityInput):
    version: int = Field(ge=1)


class EntityRead(EntityInput):
    id: uuid.UUID
    version: int
    permissions: list[str]


class GrantInput(StrictModel):
    user_id: uuid.UUID
    permissions: list[Permission] = Field(max_length=6)
    version: int = Field(ge=0)


class GrantRead(BaseModel):
    user_id: uuid.UUID
    name: str
    permissions: list[str]
    version: int


class Line(StrictModel):
    description: str = Field(min_length=2, max_length=500)
    quantity: Decimal = Field(gt=0, le=1000000, max_digits=12, decimal_places=4)
    unit: Literal["HUR", "C62"] = "HUR"
    unit_price: Decimal = Field(gt=0, le=10000000, max_digits=14, decimal_places=6)
    vat_rate: Literal[19] = 19


class InvoiceInput(StrictModel):
    buyer: Party
    buyer_reference: str = Field(min_length=1, max_length=120)
    service_reference: str = Field(min_length=2, max_length=120)
    issue_date: date
    due_date: date
    service_start: date
    service_end: date
    currency: Literal["EUR"] = "EUR"
    lines: list[Line] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def dates_and_totals(self) -> Self:
        if self.due_date < self.issue_date or self.service_end < self.service_start:
            raise ValueError("Fälligkeit und Leistungszeitraum sind nicht schlüssig.")
        if not 2000 <= self.issue_date.year <= 2100:
            raise ValueError("Nicht unterstütztes Rechnungsjahr.")
        if any(money(line.quantity * line.unit_price) <= 0 for line in self.lines):
            raise ValueError("Jede Position benötigt einen positiven gerundeten Nettobetrag.")
        if totals(self)["gross"] > Decimal("999999999.99"):
            raise ValueError("Gesamtbetrag überschreitet die unterstützte Grenze.")
        return self


class InvoiceCreate(InvoiceInput):
    request_key: uuid.UUID


class InvoiceUpdate(InvoiceInput):
    version: int = Field(ge=1)


class Decision(StrictModel):
    version: int = Field(ge=1)
    note: str = Field(min_length=3, max_length=1000)


class CreditInput(Decision):
    request_key: uuid.UUID
    issue_date: date

    @field_validator("issue_date")
    @classmethod
    def supported_year(cls, value: date) -> date:
        if not 2000 <= value.year <= 2100:
            raise ValueError("Nicht unterstütztes Stornojahr.")
        return value


class InvoiceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    entity_id: uuid.UUID
    kind: str
    original_id: uuid.UUID | None
    status: str
    version: int
    number: str | None
    buyer_name: str
    issue_date: date
    service_reference: str
    total: Decimal
    payload: dict[str, object]
    payload_hash: str
    prepared_by: uuid.UUID | None
    approved_by: uuid.UUID | None
    artifact_hash: str | None
    validation: dict[str, object] | None
    created_at: datetime


class EventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    action: str
    note: str
    actor_id: uuid.UUID | None
    created_at: datetime


def money(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def totals(data: InvoiceInput) -> dict[str, Decimal]:
    net = sum((money(line.quantity * line.unit_price) for line in data.lines), Decimal(0))
    tax = money(net * Decimal("0.19"))
    return {"net": net, "tax": tax, "gross": net + tax}
