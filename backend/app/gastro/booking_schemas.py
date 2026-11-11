"""Explicit grouped seating and waitlist commands; no inferred payments or fees."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from app.gastro.schemas import IntervalInput, ReservationRead


class GroupInput(IntervalInput):
    model_config = ConfigDict(extra="forbid")
    request_key: uuid.UUID
    table_ids: list[uuid.UUID] = Field(min_length=1, max_length=8)
    guest_name: str = Field(min_length=1, max_length=120)
    guests: int = Field(ge=1, le=100)
    source: Literal["reservation", "walk_in"] = "reservation"
    note: str = Field(default="", max_length=500)

    @model_validator(mode="after")
    def unique_resources(self) -> GroupInput:
        if len(set(self.table_ids)) != len(self.table_ids):
            raise ValueError("Jeden Tisch nur einmal auswählen.")
        return self


class GroupRead(ReservationRead):
    table_ids: list[uuid.UUID]
    source: str
    note: str
    checked_in_at: datetime | None
    closed_at: datetime | None


class CommandInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_key: uuid.UUID
    version: int = Field(ge=1)


class GroupState(CommandInput):
    status: Literal["seated", "completed", "cancelled", "no_show"]


class ExtendInput(CommandInput):
    ends_at: AwareDatetime
    reason: str = Field(min_length=3, max_length=300)


class WaitlistInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_key: uuid.UUID
    guest_name: str = Field(min_length=1, max_length=120)
    guests: int = Field(ge=1, le=100)
    note: str = Field(default="", max_length=500)


class WaitlistSeat(CommandInput):
    table_ids: list[uuid.UUID] = Field(min_length=1, max_length=8)
    ends_at: AwareDatetime

    @model_validator(mode="after")
    def unique_resources(self) -> WaitlistSeat:
        if len(set(self.table_ids)) != len(self.table_ids):
            raise ValueError("Jeden Tisch nur einmal auswählen.")
        return self


class WaitlistState(CommandInput):
    status: Literal["cancelled"]


class WaitlistRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    guest_name: str
    guests: int
    note: str
    status: str
    version: int
    reservation_id: uuid.UUID | None
    created_at: datetime
    closed_at: datetime | None


class BoardRead(BaseModel):
    reservations: list[GroupRead]
    waitlist: list[WaitlistRead]
