"""Vermerke Pydantic schemas."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, field_validator

VermerkType = Literal[
    "präferenz",
    "warnhinweis",
    "beziehungswissen",
    "dokumentenhinweis",
    "override_grund",
]

VermerkVisibility = Literal["internal", "partner", "public"]


class VermerkCreate(BaseModel):
    type: VermerkType
    text: str
    visibility: VermerkVisibility = "internal"
    valid_until: date | None = None
    strength: int | None = None  # 1–5, nur bei warnhinweis sinnvoll
    source: str | None = "manual"

    # Genau eines muss gesetzt sein
    candidate_id: uuid.UUID | None = None
    application_id: uuid.UUID | None = None
    assignment_id: uuid.UUID | None = None

    @field_validator("strength")
    @classmethod
    def strength_range(cls, v: int | None) -> int | None:
        if v is not None and not (1 <= v <= 5):
            raise ValueError("strength muss zwischen 1 und 5 liegen")
        return v


class VermerkUpdate(BaseModel):
    text: str | None = None
    valid_until: date | None = None
    strength: int | None = None
    visibility: VermerkVisibility | None = None
    is_active: bool | None = None


class VermerkRead(BaseModel):
    id: uuid.UUID
    author_id: uuid.UUID | None
    candidate_id: uuid.UUID | None
    application_id: uuid.UUID | None
    assignment_id: uuid.UUID | None
    type: str
    text: str
    valid_until: date | None
    strength: int | None
    visibility: str
    source: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
