from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    field_validator,
    model_validator,
)

from app.gastro.cancellation_schemas import CancelledUnitRead
from app.gastro.station_schemas import StationSnapshot

Role = Literal["manager", "service", "kitchen"]
OrderStatus = Literal["sent", "preparing", "ready", "served", "cancelled"]
Scope = Literal[
    "menu:read", "tables:read", "orders:write", "kitchen:write", "events:read", "payments:write"
]


class ReadModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID


class VenueInput(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    timezone: str = "Europe/Berlin"
    currency: Literal["EUR"] = "EUR"
    default_stay_minutes: int = Field(default=90, ge=15, le=600)
    walkin_hold_seats: int = Field(default=0, ge=0, le=1000)

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("Unbekannte Zeitzone") from exc
        return value


class VenueRead(VenueInput, ReadModel):
    role: Role
    guest_enabled: bool = False
    guest_table_orders: bool = False
    guest_open_tables: bool = False
    tip_mode: str = "pool_hours"
    tip_kitchen_bps: int = 0


class VersionInput(BaseModel):
    version: int = Field(ge=1)


class MemberInput(BaseModel):
    user_id: uuid.UUID
    role: Role
    active: bool = True


class MemberRead(ReadModel):
    user_id: uuid.UUID
    full_name: str
    role: Role
    active: bool


class TableInput(BaseModel):
    name: str = Field(min_length=1, max_length=40)
    area: str = Field(default="Restaurant", min_length=1, max_length=80)
    seats: int = Field(default=4, ge=1, le=100)
    x: int = Field(default=0, ge=0, le=1000)
    y: int = Field(default=0, ge=0, le=1000)

    room_id: uuid.UUID | None = None
    kind: Literal["table", "bowling", "billiard", "pedal_boat", "activity"] = "table"
    hourly_rate_cents: int = Field(default=0, ge=0, le=1000000)
    billing_minutes: int = Field(default=15, ge=1, le=60)
    tax_rate_bps: int = Field(default=1900, ge=0, le=10000)
    tags: list[str] = Field(default_factory=list, max_length=12)
    min_party: int = Field(default=1, ge=1, le=100)
    combinable_with: list[str] = Field(default_factory=list, max_length=8)

    @field_validator("combinable_with")
    @classmethod
    def clean_partners(cls, value: list[str]) -> list[str]:
        try:
            partners = [str(uuid.UUID(entry)) for entry in value]
        except ValueError as exc:
            raise ValueError("Kombinierbare Tische werden als Tisch-ID angegeben.") from exc
        if len(set(partners)) != len(partners):
            raise ValueError("Ein kombinierbarer Tisch darf nur einmal genannt werden.")
        return partners

    @field_validator("tags")
    @classmethod
    def clean_tags(cls, value: list[str]) -> list[str]:
        tags = [tag.strip().lower() for tag in value if tag.strip()]
        if any(len(tag) > 30 for tag in tags):
            raise ValueError("Ein Merkmal darf höchstens 30 Zeichen haben.")
        if len(set(tags)) != len(tags):
            raise ValueError("Merkmale dürfen sich nicht wiederholen.")
        return tags

    @model_validator(mode="after")
    def party_fits_seats(self) -> TableInput:
        if self.min_party > self.seats:
            raise ValueError("Die Mindestgruppengröße kann die Sitzplätze nicht überschreiten.")
        return self


class TableUpdate(TableInput, VersionInput):
    pass


class TableRead(TableInput, ReadModel):
    version: int


class Packaging(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    price_cents: int = Field(ge=0, le=10000)
    deposit_cents: int = Field(default=0, ge=0, le=10000)
    tax_rate_bps: int = Field(ge=0, le=10000)
    deposit_tax_rate_bps: int = Field(ge=0, le=10000)
    reusable: bool = False


def food_tag(value: str) -> str:
    """Align displayed German allergen names with existing guest exclusion keys."""
    normalized = value.strip().lower()
    aliases = {
        "erdnüsse": "erdnuss",
        "erdnuesse": "erdnuss",
        "nüsse": "nuss",
        "nuesse": "nuss",
        "schalenfrüchte": "nuss",
        "schalenfruechte": "nuss",
        "eier": "ei",
        "fische": "fisch",
        "krebstiere": "meeresfruechte",
        "weichtiere": "meeresfruechte",
    }
    return aliases.get(normalized, normalized)


class Ingredient(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=80)
    note: str = Field(default="", max_length=160)
    allergens: list[str] = Field(default_factory=list, max_length=14)


class MenuPayload(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    description: str = Field(default="", max_length=2000)
    category: str = Field(default="Speisen", min_length=1, max_length=80)
    price_cents: int = Field(ge=0, le=1000000)
    tax_rate_bps: int = Field(ge=0, le=10000)
    takeaway_packaging: Packaging | None = None
    cost_cents: int = Field(default=0, ge=0, le=1000000)
    allergens: list[str] = Field(default_factory=list, max_length=30)
    available: bool = True
    station: str = Field(default="kitchen", pattern=r"^[a-z][a-z0-9_]{0,39}$")
    station_snapshot: StationSnapshot | None = None
    # Read out at the table; deliberately not part of the public snapshot contract.
    ingredients: list[Ingredient] = Field(default_factory=list, max_length=60)
    contains: list[str] = Field(default_factory=list, max_length=30)

    @model_validator(mode="after")
    def consistent_allergen_declarations(self) -> MenuPayload:
        declared = list(
            dict.fromkeys(
                name.strip()
                for name in [
                    *self.allergens,
                    *[tag for ingredient in self.ingredients for tag in ingredient.allergens],
                ]
                if name.strip()
            )
        )
        tags = sorted(set(self.contains) | {food_tag(name) for name in declared})
        if len(declared) > 30 or len(tags) > 30:
            raise ValueError("Zu viele Allergen- oder Zutatenmerkmale")
        self.allergens = declared
        self.contains = tags
        return self

    @field_validator("contains")
    @classmethod
    def clean_contains(cls, value: list[str]) -> list[str]:
        return sorted({food_tag(entry) for entry in value if entry.strip()})

    @field_validator("allergens")
    @classmethod
    def valid_allergens(cls, value: list[str]) -> list[str]:
        if any(not name.strip() or len(name) > 80 for name in value):
            raise ValueError("Allergenbezeichnungen müssen 1–80 Zeichen lang sein")
        return list(dict.fromkeys(name.strip() for name in value))


class MenuInput(BaseModel):
    sku: str = Field(min_length=1, max_length=60, pattern=r"^[A-Za-z0-9._-]+$")
    data: MenuPayload


class MenuUpdate(VersionInput):
    data: MenuPayload


class MenuRead(ReadModel):
    sku: str
    draft: MenuPayload
    published: MenuPayload | None
    version: int
    published_version: int | None


class MenuPublic(ReadModel):
    sku: str
    version: int
    name: str
    description: str
    category: str
    price_cents: int
    tax_rate_bps: int
    allergens: list[str]
    available: bool
    station: str

    takeaway_packaging: Packaging | None = None


class LineInput(BaseModel):
    course: int = Field(default=1, ge=1, le=12)
    item_id: uuid.UUID
    menu_version: int = Field(ge=1)
    quantity: int = Field(ge=1, le=99)
    note: str = Field(default="", max_length=300)


class OrderInput(BaseModel):
    fulfillment: Literal["dine_in", "takeaway"] = "dine_in"
    request_key: uuid.UUID
    table_id: uuid.UUID | None = None
    guests: int = Field(default=1, ge=1, le=100)
    lines: list[LineInput] = Field(min_length=1, max_length=100)
    note: str = Field(default="", max_length=500)
    # A guest confirms a dietary warning here; a legal block cannot be confirmed away.
    accept_warnings: bool = False


class LineRead(BaseModel):
    station_snapshot: StationSnapshot | None = None
    recipe_id: uuid.UUID | None = None
    line_id: uuid.UUID | None = None
    course: int = 1
    preparation_status: str = "sent"
    kind: str = "product"
    discount_cents: int = 0
    item_id: uuid.UUID
    sku: str
    name: str
    menu_version: int
    quantity: int
    price_cents: int
    tax_rate_bps: int
    tax_cents: int
    total_cents: int
    allergens: list[str]
    station: str
    note: str


class OrderRead(ReadModel):
    cancelled_units: list[CancelledUnitRead] = Field(
        default_factory=list, validation_alias="cancellation_units"
    )
    fulfillment_status: str = "sent"
    payment_status: str = "open"
    fulfillment: str
    subtotal_cents: int
    discount_cents: int
    discount_reason: str
    voucher_cents: int
    number: str
    table_id: uuid.UUID | None
    status: str
    lines: list[LineRead]
    total_cents: int
    currency: str
    guests: int
    note: str
    version: int
    pos_requested: bool
    payment_reference: str | None
    paid_at: datetime | None
    tip_refunded_cents: int = 0
    tip_cents: int = 0
    tip_recipient_id: uuid.UUID | None = None
    created_at: datetime


class StateInput(VersionInput):
    status: OrderStatus
    reason: str = Field(default="", max_length=500)


class IntervalInput(BaseModel):
    starts_at: AwareDatetime
    ends_at: AwareDatetime

    @model_validator(mode="after")
    def interval(self) -> IntervalInput:
        duration = (self.ends_at - self.starts_at).total_seconds()
        if not 0 < duration <= 86400:
            raise ValueError("Zeitraum muss positiv sein und darf höchstens 24 Stunden umfassen")
        return self


class ReservationInput(IntervalInput):
    table_id: uuid.UUID
    guest_name: str = Field(min_length=1, max_length=120)
    guests: int = Field(ge=1, le=100)


class ReservationRead(ReservationInput, ReadModel):
    status: str
    version: int


class ReservationState(VersionInput):
    status: Literal["seated", "cancelled", "completed"]


class ShiftInput(IntervalInput):
    worker_id: uuid.UUID
    station: str = Field(min_length=1, max_length=80)
    break_minutes: int = Field(default=30, ge=0, le=240)

    @model_validator(mode="after")
    def pause(self) -> ShiftInput:
        if self.break_minutes >= (self.ends_at - self.starts_at).total_seconds() / 60:
            raise ValueError("Pause muss kürzer als die Schicht sein")
        return self


class ShiftRead(ShiftInput, ReadModel):
    station_label: str | None = None
    assignment_id: uuid.UUID
    status: str
    version: int


class ShiftState(VersionInput):
    status: Literal["published", "cancelled"]


class DeviceInput(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    kind: Literal["handheld", "pos", "kitchen", "integration"]
    scopes: list[Scope] = Field(min_length=1, max_length=6)
    valid_days: int = Field(default=90, ge=1, le=365)


class DeviceRead(ReadModel):
    name: str
    kind: str
    scopes: list[str]
    active: bool
    expires_at: datetime
    last_seen_at: datetime | None


class DeviceCreated(BaseModel):
    device: DeviceRead
    token: str


class PaymentInput(BaseModel):
    cancellation_version: int | None = Field(default=None, ge=1)
    request_key: uuid.UUID
    order_id: uuid.UUID
    amount_cents: int = Field(ge=0, le=100000000)
    currency: Literal["EUR"] = "EUR"
    reference: str = Field(min_length=1, max_length=160)


class EventRead(ReadModel):
    venue_id: uuid.UUID
    actor_id: uuid.UUID | None
    device_id: uuid.UUID | None
    audit_sequence: int | None
    previous_hash: str | None
    event_hash: str | None
    canonical_payload: str | None
    sequence: int
    kind: str
    aggregate_id: uuid.UUID
    payload: dict[str, JsonValue]
    created_at: datetime


class FireFlintInput(BaseModel):
    org_id: uuid.UUID
    content_id: uuid.UUID
    type_key: str = Field(default="gastro_menu", pattern=r"^[a-z][a-z0-9_]{0,79}$")
    expected_revision: int = Field(ge=1)
    version: int = Field(default=0, ge=0)


class FireFlintRead(ReadModel):
    org_id: uuid.UUID
    content_id: uuid.UUID
    type_key: str
    expected_revision: int
    version: int
    status: str
    last_synced_at: datetime | None
    last_error: str | None


class Overview(BaseModel):
    active_orders: int
    open_total_cents: int
    settled_total_cents: int
    reserved_today: int
    staff_today: int
    available_items: int
    hints: list[str]


class MessageRead(BaseModel):
    message: str


class FloorInput(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    level: int = Field(ge=-10, le=100)


class FloorRead(FloorInput, ReadModel):
    pass


class RoomInput(BaseModel):
    floor_id: uuid.UUID
    name: str = Field(min_length=1, max_length=80)


class RoomRead(RoomInput, ReadModel):
    pass


class UsageInput(BaseModel):
    request_key: uuid.UUID
    table_id: uuid.UUID
    guest_name: str = Field(min_length=1, max_length=120)
    duration_minutes: int = Field(ge=1, le=1440)


class UsageRead(ReadModel):
    table_id: uuid.UUID
    guest_name: str
    starts_at: datetime
    ends_at: datetime | None
    reserved_until: datetime
    hourly_rate_cents: int
    billing_minutes: int
    order_id: uuid.UUID | None


class DiscountInput(VersionInput):
    percent: int = Field(ge=1, le=100)
    reason: str = Field(min_length=3, max_length=160)


class VoucherInput(BaseModel):
    request_key: uuid.UUID
    label: str = Field(min_length=1, max_length=80)
    amount_cents: int = Field(ge=1, le=1000000)
    expires_at: AwareDatetime
    reference: str = Field(min_length=3, max_length=160)


class VoucherRead(ReadModel):
    label: str
    initial_cents: int
    balance_cents: int
    expires_at: datetime
    reference: str


class VoucherCreated(BaseModel):
    voucher: VoucherRead
    code: str | None


class VoucherRedeem(VersionInput):
    request_key: uuid.UUID
    code: str = Field(min_length=8, max_length=100)
    amount_cents: int = Field(ge=1, le=1000000)


class PublicVenue(ReadModel):
    name: str
    currency: str
    timezone: str
    guest_table_orders: bool = False


class GuestSettings(BaseModel):
    enabled: bool
    guest_table_orders: bool = False
    guest_open_tables: bool = False
    tip_mode: Literal["pool_hours", "direct"] = "pool_hours"
    tip_kitchen_bps: int = Field(default=0, ge=0, le=10000)


class TipInput(VersionInput):
    tip_cents: int = Field(ge=0, le=100000)
    recipient_id: uuid.UUID | None = None


class PaymentRequest(BaseModel):
    tip_cents: int = Field(default=0, ge=0, le=100000)


class GuestAccountRead(ReadModel):
    points: int


class TicketInput(BaseModel):
    category: Literal["support", "website", "branding", "marketing", "hardware", "integration"]
    subject: str = Field(min_length=3, max_length=160)
    description: str = Field(min_length=10, max_length=3000)


class TicketRead(TicketInput, ReadModel):
    status: str
    created_at: datetime


class DeviceEventRead(ReadModel):
    sequence: int
    kind: str
    aggregate_id: uuid.UUID
    payload: dict[str, JsonValue]
    created_at: datetime
