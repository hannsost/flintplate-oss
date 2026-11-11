from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import TYPE_CHECKING

from pydantic import JsonValue
from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Identity,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base_model import UUIDBase

if TYPE_CHECKING:
    from app.gastro.cancellation_models import CancellationExecution, CancellationUnit


class GastroBase(UUIDBase):
    __abstract__ = True
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=func.now(), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=func.now(), server_default=func.now(), onupdate=func.now()
    )


class Venue(GastroBase):
    __tablename__ = "fp_venues"
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("customers.id"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    timezone: Mapped[str] = mapped_column(String(80), default="Europe/Berlin")
    currency: Mapped[str] = mapped_column(String(3), default="EUR")
    guest_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    default_stay_minutes: Mapped[int] = mapped_column(Integer, default=90)
    walkin_hold_seats: Mapped[int] = mapped_column(Integer, default=0)
    guest_table_orders: Mapped[bool] = mapped_column(Boolean, default=False)
    guestbook_retention_days: Mapped[int] = mapped_column(Integer, default=365)
    chat_retention_days: Mapped[int] = mapped_column(Integer, default=90)
    guest_open_tables: Mapped[bool] = mapped_column(Boolean, default=False)
    tip_mode: Mapped[str] = mapped_column(String(20), default="pool_hours")
    tip_kitchen_bps: Mapped[int] = mapped_column(Integer, default=0)


class Membership(GastroBase):
    stations: Mapped[list[str]] = mapped_column(JSONB, default=list)
    competence: Mapped[int] = mapped_column(Integer, default=1)
    emergency_opt_in: Mapped[bool] = mapped_column(Boolean, default=False)
    template_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("fp_profile_templates.id"), nullable=True
    )
    overrides: Mapped[list[str]] = mapped_column(JSONB, default=list)
    __tablename__ = "fp_memberships"
    __table_args__ = (UniqueConstraint("venue_id", "user_id", name="uq_fp_member"),)
    venue_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("fp_venues.id"), index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    role: Mapped[str] = mapped_column(String(20))
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class DiningTable(GastroBase):
    __tablename__ = "fp_tables"
    __table_args__ = (
        UniqueConstraint("venue_id", "name", name="uq_fp_table_name"),
        CheckConstraint("seats > 0", name="ck_fp_table_seats"),
    )
    venue_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("fp_venues.id"), index=True)
    name: Mapped[str] = mapped_column(String(40))
    area: Mapped[str] = mapped_column(String(80), default="Restaurant")
    seats: Mapped[int] = mapped_column(Integer, default=4)
    x: Mapped[int] = mapped_column(Integer, default=0)
    y: Mapped[int] = mapped_column(Integer, default=0)
    room_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("fp_rooms.id"), nullable=True)
    kind: Mapped[str] = mapped_column(String(20), default="table")
    hourly_rate_cents: Mapped[int] = mapped_column(Integer, default=0)
    billing_minutes: Mapped[int] = mapped_column(Integer, default=15)
    tax_rate_bps: Mapped[int] = mapped_column(Integer, default=1900)
    tags: Mapped[list[str]] = mapped_column(JSONB, default=list)
    min_party: Mapped[int] = mapped_column(Integer, default=1)
    combinable_with: Mapped[list[str]] = mapped_column(JSONB, default=list)
    version: Mapped[int] = mapped_column(Integer, default=1)


class MenuItem(GastroBase):
    __tablename__ = "fp_menu_items"
    __table_args__ = (
        UniqueConstraint("venue_id", "sku", name="uq_fp_menu_sku"),
        UniqueConstraint("venue_id", "id", name="uq_fp_partner_menu_scope"),
    )
    venue_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("fp_venues.id"), index=True)
    sku: Mapped[str] = mapped_column(String(60))
    draft: Mapped[dict[str, JsonValue]] = mapped_column(JSONB)
    published: Mapped[dict[str, JsonValue] | None] = mapped_column(JSONB, nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    published_version: Mapped[int | None] = mapped_column(Integer, nullable=True)


class Order(GastroBase):
    def __init__(self, **kwargs: object) -> None:
        # New receipts must be serializable before any relationship SELECT.
        kwargs.setdefault("cancellation_units", [])
        kwargs.setdefault("cancellation_executions", [])
        super().__init__(**kwargs)

    cancellation_units: Mapped[list[CancellationUnit]] = relationship(
        "CancellationUnit",
        lazy="selectin",
        foreign_keys="CancellationUnit.order_id",
        order_by="CancellationUnit.line_id, CancellationUnit.unit",
    )
    cancellation_executions: Mapped[list[CancellationExecution]] = relationship(
        "CancellationExecution",
        lazy="selectin",
        foreign_keys="CancellationExecution.order_id",
        order_by="CancellationExecution.result_version",
    )
    fulfillment_status: Mapped[str] = mapped_column(String(20), default="sent")
    payment_status: Mapped[str] = mapped_column(String(20), default="open")
    __tablename__ = "fp_orders"
    __table_args__ = (
        UniqueConstraint("venue_id", "id", name="uq_fp_partner_order_scope"),
        UniqueConstraint("venue_id", "request_key", name="uq_fp_order_request"),
        CheckConstraint("total_cents >= 0", name="ck_fp_order_total"),
    )
    venue_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("fp_venues.id"), index=True)
    table_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("fp_tables.id"), nullable=True, index=True
    )
    actor_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    device_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("fp_devices.id"), nullable=True)
    request_key: Mapped[uuid.UUID] = mapped_column()
    request_hash: Mapped[str] = mapped_column(String(64))
    number: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20), default="sent", index=True)
    lines: Mapped[list[dict[str, JsonValue]]] = mapped_column(JSONB)
    total_cents: Mapped[int] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String(3), default="EUR")
    guests: Mapped[int] = mapped_column(Integer, default=1)
    note: Mapped[str] = mapped_column(String(500), default="")
    version: Mapped[int] = mapped_column(Integer, default=1)
    pos_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    fulfillment: Mapped[str] = mapped_column(String(20), default="dine_in")
    customer_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("fp_guest_accounts.id"), nullable=True
    )
    subtotal_cents: Mapped[int] = mapped_column(Integer, default=0)
    discount_cents: Mapped[int] = mapped_column(Integer, default=0)
    discount_reason: Mapped[str] = mapped_column(String(160), default="")
    voucher_cents: Mapped[int] = mapped_column(Integer, default=0)
    payment_reference: Mapped[str | None] = mapped_column(String(160), nullable=True)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    tip_refunded_cents: Mapped[int] = mapped_column(Integer, default=0)
    tip_cents: Mapped[int] = mapped_column(Integer, default=0)
    tip_recipient_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    tip_run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("fp_tip_runs.id"), nullable=True
    )


class Reservation(GastroBase):
    __tablename__ = "fp_reservations"
    __table_args__ = (CheckConstraint("ends_at > starts_at", name="ck_fp_reservation_time"),)
    venue_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("fp_venues.id"), index=True)
    table_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("fp_tables.id"), index=True)
    customer_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("fp_guest_accounts.id"), nullable=True
    )
    guest_name: Mapped[str] = mapped_column(String(120))
    guests: Mapped[int] = mapped_column(Integer)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(20), default="confirmed")
    version: Mapped[int] = mapped_column(Integer, default=1)


class Shift(GastroBase):
    __tablename__ = "fp_shifts"
    __table_args__ = (CheckConstraint("ends_at > starts_at", name="ck_fp_shift_time"),)
    venue_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("fp_venues.id"), index=True)
    worker_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    assignment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("worker_assignments.id"), unique=True
    )
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    break_minutes: Mapped[int] = mapped_column(Integer, default=30)
    station: Mapped[str] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(20), default="draft")
    version: Mapped[int] = mapped_column(Integer, default=1)


class Device(GastroBase):
    __tablename__ = "fp_devices"
    venue_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("fp_venues.id"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    kind: Mapped[str] = mapped_column(String(30))
    token_digest: Mapped[str] = mapped_column(String(64), unique=True)
    scopes: Mapped[list[str]] = mapped_column(JSONB)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Event(GastroBase):
    audit_sequence: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    previous_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    event_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    canonical_payload: Mapped[str | None] = mapped_column(String, nullable=True)
    __tablename__ = "fp_events"
    sequence: Mapped[int] = mapped_column(BigInteger, Identity(), unique=True)
    venue_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("fp_venues.id"), index=True)
    kind: Mapped[str] = mapped_column(String(80))
    aggregate_id: Mapped[uuid.UUID] = mapped_column()
    actor_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    device_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("fp_devices.id"), nullable=True)
    payload: Mapped[dict[str, JsonValue]] = mapped_column(JSONB)


class DeviceReceipt(GastroBase):
    __tablename__ = "fp_device_receipts"
    __table_args__ = (UniqueConstraint("device_id", "request_key", name="uq_fp_receipt_request"),)
    device_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("fp_devices.id"), index=True)
    request_key: Mapped[uuid.UUID] = mapped_column()
    request_hash: Mapped[str] = mapped_column(String(64))
    order_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("fp_orders.id"))


class FireFlintLink(GastroBase):
    __tablename__ = "fp_fireflint_links"
    access_ciphertext: Mapped[str | None] = mapped_column(String(24000), nullable=True)
    refresh_ciphertext: Mapped[str | None] = mapped_column(String(24000), nullable=True)
    snapshot_data: Mapped[dict[str, JsonValue] | None] = mapped_column(JSONB, nullable=True)
    venue_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("fp_venues.id"), unique=True)
    org_id: Mapped[uuid.UUID] = mapped_column()
    content_id: Mapped[uuid.UUID] = mapped_column()
    type_key: Mapped[str] = mapped_column(String(80), default="gastro_menu")
    expected_revision: Mapped[int] = mapped_column(Integer)
    version: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(30), default="configured")
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(String(300), nullable=True)


class Floor(GastroBase):
    __tablename__ = "fp_floors"
    __table_args__ = (UniqueConstraint("venue_id", "name", name="uq_fp_floor_name"),)
    venue_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("fp_venues.id"), index=True)
    name: Mapped[str] = mapped_column(String(80))
    level: Mapped[int] = mapped_column(Integer, default=0)


class Room(GastroBase):
    __tablename__ = "fp_rooms"
    __table_args__ = (UniqueConstraint("floor_id", "name", name="uq_fp_room_name"),)
    venue_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("fp_venues.id"), index=True)
    floor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("fp_floors.id"), index=True)
    name: Mapped[str] = mapped_column(String(80))


class UsageSession(GastroBase):
    __tablename__ = "fp_usage_sessions"
    __table_args__ = (UniqueConstraint("venue_id", "request_key", name="uq_fp_usage_key"),)
    venue_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("fp_venues.id"), index=True)
    table_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("fp_tables.id"), index=True)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reserved_until: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    hourly_rate_cents: Mapped[int] = mapped_column(Integer)
    billing_minutes: Mapped[int] = mapped_column(Integer)
    tax_rate_bps: Mapped[int] = mapped_column(Integer)
    request_key: Mapped[uuid.UUID] = mapped_column()
    request_hash: Mapped[str] = mapped_column(String(64))
    order_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("fp_orders.id"), nullable=True)
    guest_name: Mapped[str] = mapped_column(String(120))


class GuestAccount(GastroBase):
    __tablename__ = "fp_guest_accounts"
    __table_args__ = (
        UniqueConstraint("venue_id", "user_id", name="uq_fp_guest_account"),
        CheckConstraint("points >= 0", name="ck_fp_guest_points"),
    )
    venue_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("fp_venues.id"), index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    points: Mapped[int] = mapped_column(Integer, default=0)


class LoyaltyEntry(GastroBase):
    __tablename__ = "fp_loyalty_entries"
    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("fp_guest_accounts.id"), index=True)
    order_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("fp_orders.id"), unique=True)
    points: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(String(120))


class Voucher(GastroBase):
    __tablename__ = "fp_vouchers"
    __table_args__ = (
        CheckConstraint("balance_cents >= 0", name="ck_fp_voucher_balance"),
        UniqueConstraint("venue_id", "request_key", name="uq_fp_voucher_issue_key"),
    )
    venue_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("fp_venues.id"), index=True)
    code_digest: Mapped[str] = mapped_column(String(64), unique=True)
    label: Mapped[str] = mapped_column(String(80))
    initial_cents: Mapped[int] = mapped_column(Integer)
    balance_cents: Mapped[int] = mapped_column(Integer)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    reference: Mapped[str] = mapped_column(String(160))
    request_key: Mapped[uuid.UUID] = mapped_column()


class VoucherEntry(GastroBase):
    __tablename__ = "fp_voucher_entries"
    __table_args__ = (UniqueConstraint("venue_id", "request_key", name="uq_fp_voucher_request"),)
    venue_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("fp_venues.id"), index=True)
    voucher_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("fp_vouchers.id"), index=True)
    order_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("fp_orders.id"), nullable=True)
    amount_cents: Mapped[int] = mapped_column(Integer)
    request_key: Mapped[uuid.UUID] = mapped_column()
    request_hash: Mapped[str] = mapped_column(String(64))
    kind: Mapped[str] = mapped_column(String(20))
    actor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))


class SupportTicket(GastroBase):
    __tablename__ = "fp_support_tickets"
    venue_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("fp_venues.id"), index=True)
    actor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    category: Mapped[str] = mapped_column(String(30))
    subject: Mapped[str] = mapped_column(String(160))
    description: Mapped[str] = mapped_column(String(3000))
    status: Mapped[str] = mapped_column(String(20), default="open")


class Availability(GastroBase):
    __tablename__ = "fp_availability"
    venue_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("fp_venues.id"), index=True)
    worker_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Emergency(GastroBase):
    __tablename__ = "fp_emergencies"
    __table_args__ = (UniqueConstraint("venue_id", "request_key", name="uq_fp_emergency_key"),)
    venue_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("fp_venues.id"), index=True)
    shift_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("fp_shifts.id"), index=True)
    replacement_shift_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("fp_shifts.id"), nullable=True
    )
    actor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    mode: Mapped[str] = mapped_column(String(20))
    reason: Mapped[str] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(20), default="open")
    timeout_minutes: Mapped[int] = mapped_column(Integer)
    ranking: Mapped[list[dict[str, JsonValue]]] = mapped_column(JSONB)
    request_key: Mapped[uuid.UUID] = mapped_column()
    request_hash: Mapped[str] = mapped_column(String(64))
    version: Mapped[int] = mapped_column(Integer, default=1)


class EmergencyOffer(GastroBase):
    __tablename__ = "fp_emergency_offers"
    __table_args__ = (UniqueConstraint("emergency_id", "worker_id", name="uq_fp_emergency_worker"),)
    emergency_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("fp_emergencies.id"), index=True)
    worker_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    position: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), default="queued")
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    responded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Decision(GastroBase):
    """One recorded proposal: what was asked, which options were offered, what was chosen."""

    __tablename__ = "fp_decisions"
    venue_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("fp_venues.id"), index=True)
    actor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    kind: Mapped[str] = mapped_column(String(40))
    request: Mapped[dict[str, JsonValue]] = mapped_column(JSONB)
    options: Mapped[list[dict[str, JsonValue]]] = mapped_column(JSONB)
    prompt: Mapped[str] = mapped_column(String(1000), default="")
    prompt_applied: Mapped[bool] = mapped_column(Boolean, default=False)
    engine: Mapped[str] = mapped_column(String(40))
    chosen_key: Mapped[str | None] = mapped_column(String(40), nullable=True)
    chosen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1)


class DecisionCriterion(GastroBase):
    """Reusable free-text criteria a venue wants considered in later proposals."""

    __tablename__ = "fp_decision_criteria"
    __table_args__ = (UniqueConstraint("venue_id", "kind", "label", name="uq_fp_criteria_label"),)
    venue_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("fp_venues.id"), index=True)
    kind: Mapped[str] = mapped_column(String(40))
    label: Mapped[str] = mapped_column(String(80))
    text: Mapped[str] = mapped_column(String(1000))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    version: Mapped[int] = mapped_column(Integer, default=1)


class ProfileTemplate(GastroBase):
    """Shared qualification profile several team members can inherit from."""

    __tablename__ = "fp_profile_templates"
    __table_args__ = (UniqueConstraint("venue_id", "name", name="uq_fp_template_name"),)
    venue_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("fp_venues.id"), index=True)
    name: Mapped[str] = mapped_column(String(80))
    description: Mapped[str] = mapped_column(String(300), default="")
    stations: Mapped[list[str]] = mapped_column(JSONB, default=list)
    competence: Mapped[int] = mapped_column(Integer, default=1)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    version: Mapped[int] = mapped_column(Integer, default=1)


class TipRun(GastroBase):
    """One confirmed distribution of the tips collected in a period."""

    __tablename__ = "fp_tip_runs"
    venue_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("fp_venues.id"), index=True)
    period_start: Mapped[date] = mapped_column(Date)
    period_end: Mapped[date] = mapped_column(Date)
    mode: Mapped[str] = mapped_column(String(20))
    kitchen_bps: Mapped[int] = mapped_column(Integer, default=0)
    total_cents: Mapped[int] = mapped_column(Integer)
    orders: Mapped[int] = mapped_column(Integer, default=0)
    actor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    note: Mapped[str] = mapped_column(String(300), default="")


class TipShare(GastroBase):
    __tablename__ = "fp_tip_shares"
    __table_args__ = (UniqueConstraint("run_id", "worker_id", name="uq_fp_tip_share"),)
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("fp_tip_runs.id"), index=True)
    worker_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    pool: Mapped[str] = mapped_column(String(20))
    minutes: Mapped[int] = mapped_column(Integer, default=0)
    share_cents: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(String(200), default="")


class GuestProfile(GastroBase):
    """A person the house wants to remember, with the consent state that allows it."""

    __tablename__ = "fp_guest_profiles"
    venue_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("fp_venues.id"), index=True)
    display_name: Mapped[str] = mapped_column(String(120))
    reference: Mapped[str] = mapped_column(String(160), default="")
    birthday: Mapped[str | None] = mapped_column(String(5), nullable=True)
    account_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("fp_guest_accounts.id"), nullable=True
    )
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    consent_special: Mapped[bool] = mapped_column(Boolean, default=False)
    consent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    consent_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    markers: Mapped[list[str]] = mapped_column(JSONB, default=list)
    version: Mapped[int] = mapped_column(Integer, default=1)


class GuestNote(GastroBase):
    __tablename__ = "fp_guest_notes"
    profile_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("fp_guest_profiles.id", ondelete="CASCADE"), index=True
    )
    venue_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("fp_venues.id"))
    author_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    text: Mapped[str] = mapped_column(String(1000))
    category: Mapped[str] = mapped_column(String(30))
    visibility: Mapped[str] = mapped_column(String(20), default="team")
    sensitive: Mapped[bool] = mapped_column(Boolean, default=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class DietMarker(GastroBase):
    """A guest property the house reacts to, with the ingredient tags it rules out."""

    __tablename__ = "fp_diet_markers"
    __table_args__ = (UniqueConstraint("venue_id", "key", name="uq_fp_marker_key"),)
    venue_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("fp_venues.id"), index=True)
    key: Mapped[str] = mapped_column(String(40))
    label: Mapped[str] = mapped_column(String(80))
    kind: Mapped[str] = mapped_column(String(20))
    special: Mapped[bool] = mapped_column(Boolean, default=False)
    legal_block: Mapped[bool] = mapped_column(Boolean, default=False)
    avoid: Mapped[list[str]] = mapped_column(JSONB, default=list)
    note: Mapped[str] = mapped_column(String(300), default="")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    version: Mapped[int] = mapped_column(Integer, default=1)


class ChatChannel(GastroBase):
    __tablename__ = "fp_chat_channels"
    __table_args__ = (UniqueConstraint("venue_id", "name", name="uq_fp_channel_name"),)
    venue_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("fp_venues.id"), index=True)
    name: Mapped[str] = mapped_column(String(60))
    topic: Mapped[str] = mapped_column(String(200), default="")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    version: Mapped[int] = mapped_column(Integer, default=1)


class ChatMessage(GastroBase):
    __tablename__ = "fp_chat_messages"
    channel_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("fp_chat_channels.id", ondelete="CASCADE"), index=True
    )
    venue_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("fp_venues.id"))
    author_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    text: Mapped[str] = mapped_column(String(2000))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    sequence: Mapped[int] = mapped_column(BigInteger, Identity(), unique=True)


class ChatRead(GastroBase):
    __tablename__ = "fp_chat_reads"
    __table_args__ = (UniqueConstraint("channel_id", "user_id", name="uq_fp_chat_read"),)
    channel_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("fp_chat_channels.id", ondelete="CASCADE")
    )
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    last_read_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_read_sequence: Mapped[int] = mapped_column(BigInteger, default=0)
