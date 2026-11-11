"""Public staff contract for pseudonymous visits and one-send guest rounds."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from app.gastro.schemas import LineInput, OrderRead


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class SettingsRead(BaseModel):
    workflow: Literal["table", "guest", "counter", "mixed"] = "table"
    guest_label_mode: Literal["number", "name_or_number", "seat_or_number"] = "number"
    version: int = 0


class SettingsInput(Input):
    request_key: uuid.UUID
    version: int = Field(ge=0)
    workflow: Literal["table", "guest", "counter", "mixed"]
    guest_label_mode: Literal["number", "name_or_number", "seat_or_number"]


class TabSpec(Input):
    kind: Literal["guest", "shared"] = "guest"
    label: str = Field(default="", max_length=120)
    current_table_id: uuid.UUID | None = None
    seat_label: str = Field(default="", max_length=30)
    present: bool = True

    @model_validator(mode="after")
    def presence(self) -> Self:
        if self.kind == "shared":
            self.present = False
        return self


class VisitCreate(Input):
    request_key: uuid.UUID
    reservation_id: uuid.UUID | None = None
    label: str = Field(default="", max_length=120)
    tabs: list[TabSpec] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def unique_shared(self) -> Self:
        if sum(tab.kind == "shared" for tab in self.tabs) > 1:
            raise ValueError("Pro Besuch gibt es nur ein gemeinsames Konto.")
        return self


class TabRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    venue_id: uuid.UUID
    visit_id: uuid.UUID
    kind: Literal["guest", "shared"]
    number: int
    label: str
    current_table_id: uuid.UUID | None
    seat_label: str
    present: bool
    version: int
    created_at: datetime


class VisitRead(BaseModel):
    reservation_id: uuid.UUID | None
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    venue_id: uuid.UUID
    number: str
    label: str
    version: int
    ended_at: datetime | None
    created_at: datetime
    tabs: list[TabRead]


class VisitPage(BaseModel):
    items: list[VisitRead]
    next_before: uuid.UUID | None
    has_more: bool


class TabCreate(TabSpec):
    request_key: uuid.UUID
    visit_version: int = Field(ge=1)


class TabContext(Input):
    request_key: uuid.UUID
    version: int = Field(ge=1)
    label: str = Field(max_length=120)
    current_table_id: uuid.UUID | None
    seat_label: str = Field(max_length=30)
    present: bool
    reason: str = Field(min_length=3, max_length=500)


class VisitEnd(Input):
    request_key: uuid.UUID
    version: int = Field(ge=1)
    reason: str = Field(min_length=3, max_length=500)


class TabVersion(Input):
    guest_tab_id: uuid.UUID
    version: int = Field(ge=1)


class RowAssignment(Input):
    guest_tab_id: uuid.UUID
    units: list[int] = Field(min_length=1, max_length=99)


class CartRow(LineInput):
    model_config = ConfigDict(extra="forbid")
    cart_row_id: uuid.UUID
    assignments: list[RowAssignment] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def complete(self) -> Self:
        units = [unit for assignment in self.assignments for unit in assignment.units]
        if sorted(units) != list(range(self.quantity)) or len(
            {a.guest_tab_id for a in self.assignments}
        ) != len(self.assignments):
            raise ValueError("Jedes Stück genau einmal einem Gast oder Gemeinsam zuordnen.")
        return self


class RoundInput(Input):
    accept_warnings: bool = False
    request_key: uuid.UUID
    visit_version: int = Field(ge=1)
    tab_versions: list[TabVersion] = Field(min_length=1, max_length=100)
    fulfillment: Literal["dine_in", "takeaway"] = "dine_in"
    note: str = Field(default="", max_length=500)
    rows: list[CartRow] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def references(self) -> Self:
        ids = [row.cart_row_id for row in self.rows]
        tabs = [tab.guest_tab_id for tab in self.tab_versions]
        selected = {a.guest_tab_id for row in self.rows for a in row.assignments}
        if (
            len(set(ids)) != len(ids)
            or len(set(tabs)) != len(tabs)
            or set(tabs) != selected
            or sum(row.quantity for row in self.rows) > 1000
        ):
            raise ValueError(
                "Eindeutige Zeilen und exakte Gastversionen, höchstens 1000 Stücke erforderlich."
            )
        return self


class RoundChildRead(BaseModel):
    guest_tab_id: uuid.UUID
    order_id: uuid.UUID
    number: str
    label_snapshot: str
    order: OrderRead


class RoundRead(BaseModel):
    id: uuid.UUID
    visit_id: uuid.UUID
    number: int
    created_at: datetime
    children: list[RoundChildRead]


class RoundPage(BaseModel):
    items: list[RoundRead]
    next_before: uuid.UUID | None
    has_more: bool


class UnitKey(Input):
    order_id: uuid.UUID
    line_id: uuid.UUID
    unit: int = Field(ge=0, le=98)


class AssignmentInput(Input):
    guest_tab_id: uuid.UUID
    tab_version: int = Field(ge=1)
    units: list[UnitKey] = Field(min_length=1, max_length=1000)
    reason: str = Field(min_length=3, max_length=500)

    @model_validator(mode="after")
    def unique(self) -> Self:
        if len({(u.order_id, u.line_id, u.unit) for u in self.units}) != len(self.units):
            raise ValueError("Stücke müssen eindeutig sein.")
        return self


class AssignmentCommit(AssignmentInput):
    request_key: uuid.UUID
    preview_hash: str = Field(min_length=64, max_length=64)


class AssignmentPreview(BaseModel):
    guest_tab_id: uuid.UUID
    units: list[UnitKey]
    preview_hash: str
    blockers: list[str]


class AssignedUnitRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    order_id: uuid.UUID
    line_id: uuid.UUID
    unit: int
    guest_tab_id: uuid.UUID
    before_tab_id: uuid.UUID | None = None
    version: int
    cart_row_id: uuid.UUID | None
    cart_unit: int | None


class AssignmentResult(BaseModel):
    assignments: list[AssignedUnitRead]


class OrderServiceContextRead(BaseModel):
    order_id: uuid.UUID
    round_id: uuid.UUID | None
    round_number: int | None
    visit_id: uuid.UUID
    visit_number: str
    tabs: list[TabRead]
    assignments: list[AssignedUnitRead]


class TablePresenceRead(BaseModel):
    table_id: uuid.UUID
    visit_ids: list[uuid.UUID]
    guest_tab_ids: list[uuid.UUID]
    guest_count: int


class CommandRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    kind: str
    actor_id: uuid.UUID
    reason: str
    target_id: uuid.UUID
    snapshots: list[dict[str, JsonValue]]
    result: dict[str, JsonValue]
    created_at: datetime


class HistoryPage(BaseModel):
    items: list[CommandRead]
    next_before: uuid.UUID | None
    has_more: bool
