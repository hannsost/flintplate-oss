"""Stable split budgets, payment proofs and explicit terminal actions."""

from __future__ import annotations

import uuid

from pydantic import JsonValue
from sqlalchemy import CheckConstraint, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.gastro.models import GastroBase


class EqualSplitPlan(GastroBase):
    __tablename__ = "fp_equal_split_plans"
    __table_args__ = (
        UniqueConstraint("venue_id", "request_key", name="uq_fp_equal_plan_request"),
        UniqueConstraint("root_plan_id", "revision", name="uq_fp_equal_plan_revision"),
        CheckConstraint("revision>0 AND total_cents>0", name="ck_fp_equal_plan_amount"),
    )
    venue_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("fp_venues.id"), index=True)
    root_plan_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("fp_equal_split_plans.id", deferrable=True, initially="DEFERRED")
    )
    supersedes_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("fp_equal_split_plans.id"), nullable=True, unique=True
    )
    revision: Mapped[int] = mapped_column(Integer)
    actor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    request_key: Mapped[uuid.UUID]
    request_hash: Mapped[str] = mapped_column(String(64))
    currency: Mapped[str] = mapped_column(String(3))
    total_cents: Mapped[int] = mapped_column(Integer)
    source_hash: Mapped[str] = mapped_column(String(64))
    source_snapshot: Mapped[list[dict[str, JsonValue]]] = mapped_column(JSONB)
    selection: Mapped[dict[str, JsonValue]] = mapped_column(JSONB)
    reason: Mapped[str] = mapped_column(String(300), default="")


class EqualSplitPart(GastroBase):
    __tablename__ = "fp_equal_split_parts"
    __table_args__ = (
        UniqueConstraint("plan_id", "ordinal", name="uq_fp_equal_part_ordinal"),
        CheckConstraint("ordinal>=0 AND target_cents>=0", name="ck_fp_equal_part_amount"),
    )
    venue_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("fp_venues.id"), index=True)
    plan_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("fp_equal_split_plans.id"), index=True)
    ordinal: Mapped[int] = mapped_column(Integer)
    payer_tab_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("fp_guest_tabs.id"), nullable=True
    )
    label: Mapped[str] = mapped_column(String(80))
    target_cents: Mapped[int] = mapped_column(Integer)
    unit_budgets: Mapped[list[dict[str, JsonValue]]] = mapped_column(JSONB)


class EqualSplitPartPayment(GastroBase):
    __tablename__ = "fp_equal_split_part_payments"
    __table_args__ = (
        UniqueConstraint("group_id", "part_id", name="uq_fp_equal_part_group"),
        CheckConstraint("amount_cents>0", name="ck_fp_equal_part_payment_amount"),
    )
    venue_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("fp_venues.id"), index=True)
    group_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("fp_payment_groups.id"), index=True)
    part_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("fp_equal_split_parts.id"), index=True)
    amount_cents: Mapped[int] = mapped_column(Integer)
    allocations: Mapped[list[dict[str, JsonValue]]] = mapped_column(JSONB)


class EqualSplitPlanAction(GastroBase):
    __tablename__ = "fp_equal_split_plan_actions"
    __table_args__ = (
        UniqueConstraint("venue_id", "request_key", name="uq_fp_equal_action_request"),
    )
    venue_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("fp_venues.id"), index=True)
    plan_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("fp_equal_split_plans.id"), unique=True)
    next_plan_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("fp_equal_split_plans.id"), nullable=True, unique=True
    )
    actor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(String(20))
    reason: Mapped[str] = mapped_column(String(300))
    request_key: Mapped[uuid.UUID]
    request_hash: Mapped[str] = mapped_column(String(64))
