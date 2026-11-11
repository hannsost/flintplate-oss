"""Named floor arrangements, separate from person profiles and resource tariffs."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator

MAX_PROFILE_TABLES = 500
MAX_ACTIVE_PROFILES = 50


class LayoutInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class TableVersion(LayoutInput):
    table_id: uuid.UUID
    version: int = Field(ge=1, strict=True)


class PositionRead(TableVersion):
    # Existing TableInput.area permits whitespace; snapshots preserve it exactly.
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)

    x: int = Field(ge=0, le=1000, strict=True)
    y: int = Field(ge=0, le=1000, strict=True)
    room_id: uuid.UUID | None
    area: str = Field(min_length=1, max_length=80)


class PositionInput(LayoutInput):
    request_key: uuid.UUID
    version: int = Field(ge=1, strict=True)
    x: int = Field(ge=0, le=1000, strict=True)
    y: int = Field(ge=0, le=1000, strict=True)


class ProfileSaveInput(LayoutInput):
    request_key: uuid.UUID
    profile_id: uuid.UUID | None = None
    expected_version: int = Field(default=0, ge=0, strict=True)
    name: str = Field(min_length=2, max_length=80)
    # None selects the whole venue, not just resources without a room.
    room_id: uuid.UUID | None = None
    tables: list[TableVersion] = Field(min_length=1, max_length=MAX_PROFILE_TABLES)

    @model_validator(mode="after")
    def capture_identity(self) -> ProfileSaveInput:
        if (self.profile_id is None) != (self.expected_version == 0):
            raise ValueError("Neue Profile benötigen Version 0, bestehende ihre aktuelle Version.")
        if len({row.table_id for row in self.tables}) != len(self.tables):
            raise ValueError("Jede Ressource darf nur einmal im Profil stehen.")
        self.tables.sort(key=lambda row: str(row.table_id))
        return self


class ProfileRead(LayoutInput):
    id: uuid.UUID
    name: str
    room_id: uuid.UUID | None
    version: int
    archived: bool
    current_revision_id: uuid.UUID
    table_count: int
    created_at: datetime
    updated_at: datetime


class RevisionRead(LayoutInput):
    model_config = ConfigDict(extra="forbid", from_attributes=True)
    id: uuid.UUID
    profile_id: uuid.UUID
    previous_id: uuid.UUID | None
    version: int
    name: str
    room_id: uuid.UUID | None
    archived: bool
    placements: list[PositionRead]
    actor_id: uuid.UUID
    created_at: datetime


class ProfilePreviewInput(LayoutInput):
    version: int = Field(ge=1, strict=True)
    revision_id: uuid.UUID | None = None


class PreviewRow(LayoutInput):
    table_id: uuid.UUID
    name: str
    current: PositionRead | None
    saved: PositionRead
    changed: bool


class ProfilePreviewRead(LayoutInput):
    profile_id: uuid.UUID
    profile_version: int
    revision_id: uuid.UUID
    snapshot_version: int
    name: str
    room_id: uuid.UUID | None
    rows: list[PreviewRow]
    added_table_ids: list[uuid.UUID]
    missing_table_ids: list[uuid.UUID]
    blocking_reasons: list[str]
    fingerprint: str


class ProfileApplyInput(LayoutInput):
    request_key: uuid.UUID
    version: int = Field(ge=1, strict=True)
    revision_id: uuid.UUID
    fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")


class ProfileApplyRead(LayoutInput):
    request_key: uuid.UUID
    profile_id: uuid.UUID
    profile_version: int
    revision_id: uuid.UUID
    positions: list[PositionRead]
    changed_table_ids: list[uuid.UUID]


class ProfileArchiveInput(LayoutInput):
    request_key: uuid.UUID
    version: int = Field(ge=1, strict=True)
    archived: bool = True
