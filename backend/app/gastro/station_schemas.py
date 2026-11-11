"""Only registry-derived snapshots determine station identity and classification."""

from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

StationKind = Literal["kitchen", "bar", "service", "activities"]


class StationSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: uuid.UUID
    code: str = Field(pattern=r"^[a-z][a-z0-9_]{0,39}$")
    name: str = Field(min_length=2, max_length=80)
    kind: StationKind


class StationRead(StationSnapshot):
    model_config = ConfigDict(from_attributes=True, extra="forbid")
    active: bool
    sort_order: int
    version: int


class StationFields(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_key: uuid.UUID
    name: str = Field(min_length=2, max_length=80)
    sort_order: int = Field(default=0, ge=0, le=999)

    @field_validator("name", mode="before")
    @classmethod
    def clean_name(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class StationCreate(StationFields):
    kind: StationKind


class StationUpdate(StationFields):
    version: int = Field(ge=1)
    active: bool
