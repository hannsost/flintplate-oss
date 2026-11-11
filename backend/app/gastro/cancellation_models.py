"""Immutable requests, approvals and individual cancelled receipt units."""

from __future__ import annotations

import uuid

from pydantic import JsonValue
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.gastro.models import GastroBase


class CancellationRequest(GastroBase):
    __tablename__ = "fp_cancellation_requests"
    __table_args__ = (
        UniqueConstraint("venue_id", "id", name="uq_fp_cancel_request_scope"),
        UniqueConstraint("venue_id", "request_key", name="uq_fp_cancel_request_key"),
        ForeignKeyConstraint(["venue_id", "order_id"], ["fp_orders.venue_id", "fp_orders.id"]),
        CheckConstraint(
            "order_version > 0 AND length(trim(note)) >= 3", name="ck_fp_cancel_request_reason"
        ),
        CheckConstraint("source IN ('staff','guest','legacy')", name="ck_fp_cancel_request_source"),
    )
    venue_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("fp_venues.id"), index=True)
    order_id: Mapped[uuid.UUID] = mapped_column(index=True)
    order_number: Mapped[str] = mapped_column(String(20))
    requester_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    original_actor_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    request_key: Mapped[uuid.UUID] = mapped_column()
    request_hash: Mapped[str] = mapped_column(String(64))
    order_version: Mapped[int] = mapped_column(Integer)
    reason_code: Mapped[str] = mapped_column(String(24))
    note: Mapped[str] = mapped_column(String(500))
    source: Mapped[str] = mapped_column(String(12), default="staff", server_default="staff")
    selection: Mapped[dict[str, JsonValue]] = mapped_column(JSONB)
    preview: Mapped[dict[str, JsonValue]] = mapped_column(JSONB)


class CancellationDecision(GastroBase):
    __tablename__ = "fp_cancellation_decisions"
    __table_args__ = (
        UniqueConstraint("venue_id", "id", name="uq_fp_cancel_decision_scope"),
        UniqueConstraint("request_id", name="uq_fp_cancel_decision_request"),
        UniqueConstraint("venue_id", "request_key", name="uq_fp_cancel_decision_key"),
        ForeignKeyConstraint(
            ["venue_id", "request_id"],
            ["fp_cancellation_requests.venue_id", "fp_cancellation_requests.id"],
        ),
        CheckConstraint("decision IN ('approve','reject')", name="ck_fp_cancel_decision_kind"),
        CheckConstraint("length(trim(note)) >= 3", name="ck_fp_cancel_decision_reason"),
    )
    venue_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("fp_venues.id"), index=True)
    request_id: Mapped[uuid.UUID] = mapped_column()
    actor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    request_key: Mapped[uuid.UUID] = mapped_column()
    request_hash: Mapped[str] = mapped_column(String(64))
    decision: Mapped[str] = mapped_column(String(10))
    note: Mapped[str] = mapped_column(String(500))
    self_approved: Mapped[bool] = mapped_column(Boolean)


class CancellationExecution(GastroBase):
    __tablename__ = "fp_cancellation_executions"
    __table_args__ = (
        UniqueConstraint("venue_id", "id", name="uq_fp_cancel_execution_scope"),
        UniqueConstraint("request_id", name="uq_fp_cancel_execution_request"),
        UniqueConstraint("decision_id", name="uq_fp_cancel_execution_decision"),
        ForeignKeyConstraint(
            ["venue_id", "request_id"],
            ["fp_cancellation_requests.venue_id", "fp_cancellation_requests.id"],
        ),
        ForeignKeyConstraint(
            ["venue_id", "decision_id"],
            ["fp_cancellation_decisions.venue_id", "fp_cancellation_decisions.id"],
        ),
        ForeignKeyConstraint(["venue_id", "order_id"], ["fp_orders.venue_id", "fp_orders.id"]),
        CheckConstraint(
            "result_version = order_version + 1", name="ck_fp_cancel_execution_version"
        ),
    )
    venue_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("fp_venues.id"), index=True)
    order_id: Mapped[uuid.UUID] = mapped_column(index=True)
    request_id: Mapped[uuid.UUID] = mapped_column()
    decision_id: Mapped[uuid.UUID] = mapped_column()
    actor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    order_number: Mapped[str] = mapped_column(String(20))
    reason_code: Mapped[str] = mapped_column(String(24))
    note: Mapped[str] = mapped_column(String(500))
    order_version: Mapped[int] = mapped_column(Integer)
    result_version: Mapped[int] = mapped_column(Integer)
    lines: Mapped[list[dict[str, JsonValue]]] = mapped_column(JSONB)
    money: Mapped[dict[str, JsonValue]] = mapped_column(JSONB)
    original_snapshot: Mapped[dict[str, JsonValue]] = mapped_column(JSONB)
    checkout_reconciliation_required: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false"
    )
    kitchen_required: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")


class CancellationUnit(GastroBase):
    __tablename__ = "fp_cancellation_units"
    __table_args__ = (
        UniqueConstraint("order_id", "line_id", "unit", name="uq_fp_cancel_unit"),
        Index("uq_fp_cancel_tip", "order_id", unique=True, postgresql_where=text("kind='tip'")),
        ForeignKeyConstraint(
            ["venue_id", "execution_id"],
            ["fp_cancellation_executions.venue_id", "fp_cancellation_executions.id"],
        ),
        ForeignKeyConstraint(["venue_id", "order_id"], ["fp_orders.venue_id", "fp_orders.id"]),
        CheckConstraint(
            "unit >= 0 AND gross_cents >= 0 AND tax_cents >= 0 AND tax_cents <= gross_cents",
            name="ck_fp_cancel_unit_original",
        ),
        CheckConstraint(
            "unpaid_credit_cents >= 0 AND unpaid_tax_cents >= 0 AND refund_due_cents >= 0 AND refund_tax_cents >= 0 AND already_refunded_cents >= 0 AND already_refunded_tax_cents >= 0",
            name="ck_fp_cancel_unit_parts",
        ),
        CheckConstraint(
            "gross_cents = unpaid_credit_cents + refund_due_cents + already_refunded_cents AND tax_cents = unpaid_tax_cents + refund_tax_cents + already_refunded_tax_cents",
            name="ck_fp_cancel_unit_conservation",
        ),
    )
    venue_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("fp_venues.id"), index=True)
    order_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("fp_orders.id"), index=True)
    execution_id: Mapped[uuid.UUID] = mapped_column()
    line_id: Mapped[uuid.UUID] = mapped_column()
    unit: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(20))
    name: Mapped[str] = mapped_column(String(160))
    gross_cents: Mapped[int] = mapped_column(Integer)
    tax_cents: Mapped[int] = mapped_column(Integer)
    unpaid_credit_cents: Mapped[int] = mapped_column(Integer)
    unpaid_tax_cents: Mapped[int] = mapped_column(Integer)
    refund_due_cents: Mapped[int] = mapped_column(Integer)
    refund_tax_cents: Mapped[int] = mapped_column(Integer)
    already_refunded_cents: Mapped[int] = mapped_column(Integer)
    already_refunded_tax_cents: Mapped[int] = mapped_column(Integer)
    refund_allocations: Mapped[list[dict[str, JsonValue]]] = mapped_column(JSONB)


class CancellationAcknowledgement(GastroBase):
    __tablename__ = "fp_cancellation_acknowledgements"
    __table_args__ = (
        UniqueConstraint("execution_id", name="uq_fp_cancel_ack_execution"),
        UniqueConstraint("venue_id", "request_key", name="uq_fp_cancel_ack_key"),
        ForeignKeyConstraint(
            ["venue_id", "execution_id"],
            ["fp_cancellation_executions.venue_id", "fp_cancellation_executions.id"],
        ),
    )
    venue_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("fp_venues.id"), index=True)
    execution_id: Mapped[uuid.UUID] = mapped_column()
    actor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    request_key: Mapped[uuid.UUID] = mapped_column()
    request_hash: Mapped[str] = mapped_column(String(64))
