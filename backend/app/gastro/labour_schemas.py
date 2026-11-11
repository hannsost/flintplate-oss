"""Explicit UTC validity and full revision input for calculated personnel costs."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from itertools import pairwise

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator


class LabourPeriod(BaseModel):
    model_config = ConfigDict(extra="forbid")
    valid_from: AwareDatetime
    valid_until: AwareDatetime | None = None
    hourly_cents: int = Field(ge=0, le=1000000, strict=True)
    employer_markup_bps: int = Field(ge=0, le=100000, strict=True)
    source_reference: str = Field(min_length=3, max_length=300)

    @field_validator("valid_from", "valid_until")
    @classmethod
    def utc(cls, value: datetime | None) -> datetime | None:
        return value.astimezone(UTC) if value is not None else None

    @field_validator("source_reference", mode="before")
    @classmethod
    def clean_source(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @model_validator(mode="after")
    def valid_window(self) -> LabourPeriod:
        if self.valid_until is not None and self.valid_until <= self.valid_from:
            raise ValueError("Das Gültigkeitsende muss nach dem Beginn liegen.")
        return self


class LabourRevisionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_key: uuid.UUID
    version: int = Field(ge=0, strict=True)
    reason: str = Field(min_length=3, max_length=300)
    source_reference: str = Field(min_length=3, max_length=300)
    periods: list[LabourPeriod] = Field(max_length=200)

    @field_validator("reason", "source_reference", mode="before")
    @classmethod
    def clean_reference(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @model_validator(mode="after")
    def ordered_non_overlapping(self) -> LabourRevisionInput:
        self.periods.sort(key=lambda period: period.valid_from)
        for previous, current in pairwise(self.periods):
            if previous.valid_until is None or previous.valid_until > current.valid_from:
                raise ValueError("Kostensatz-Zeiträume dürfen sich nicht überschneiden.")
        return self


class LabourRevisionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    worker_id: uuid.UUID
    previous_id: uuid.UUID | None
    version: int
    currency: str
    actor_id: uuid.UUID
    created_at: datetime
    reason: str
    source_reference: str
    periods: list[LabourPeriod]


class LabourCurrent(BaseModel):
    worker_id: uuid.UUID
    full_name: str
    current: LabourRevisionRead | None


class LabourSummary(BaseModel):
    cost_cents: int | None
    known_cost_cents: int
    valued_minutes: int
    unvalued_minutes: int
    ambiguous_minutes: int = 0
    rate_revision_ids: list[uuid.UUID]
    source_fingerprint: str
    basis: str = "current_immutable_rate_revisions"
