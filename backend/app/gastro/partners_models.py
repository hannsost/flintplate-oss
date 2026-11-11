"""Partner ownership, commercial recognition and immutable monthly statements."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from pydantic import JsonValue
from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.gastro.inventory_models import InventoryBase


class PartnerBase(InventoryBase):
    __abstract__ = True
    venue_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("fp_venues.id"), index=True)


def scoped(column: str, table: str, name: str) -> ForeignKeyConstraint:
    return ForeignKeyConstraint(
        ["venue_id", column], [f"{table}.venue_id", f"{table}.id"], name=name
    )


class PartnerContract(PartnerBase):
    __tablename__ = "fp_partner_contracts"
    __table_args__ = (
        UniqueConstraint("venue_id", "id", name="uq_fp_partner_contract_scope"),
        UniqueConstraint("venue_id", "menu_item_id", name="uq_fp_partner_contract_menu"),
        UniqueConstraint("venue_id", "request_key", name="uq_fp_partner_contract_request"),
        scoped("owner_id", "fp_stock_owners", "fk_fp_partner_contract_owner"),
        scoped("item_id", "fp_stock_items", "fk_fp_partner_contract_item"),
        scoped("menu_item_id", "fp_menu_items", "fk_fp_partner_contract_menu"),
    )
    owner_id: Mapped[uuid.UUID] = mapped_column()
    item_id: Mapped[uuid.UUID] = mapped_column()
    menu_item_id: Mapped[uuid.UUID] = mapped_column()
    name: Mapped[str] = mapped_column(String(120))
    currency: Mapped[str] = mapped_column(String(3))
    request_key: Mapped[uuid.UUID] = mapped_column()
    request_hash: Mapped[str] = mapped_column(String(64))
    actor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))


class PartnerTerms(PartnerBase):
    __tablename__ = "fp_partner_terms"
    __table_args__ = (
        UniqueConstraint("venue_id", "id", name="uq_fp_partner_terms_scope"),
        UniqueConstraint("contract_id", "version", name="uq_fp_partner_terms_version"),
        UniqueConstraint("contract_id", "effective_on", name="uq_fp_partner_terms_date"),
        UniqueConstraint("venue_id", "request_key", name="uq_fp_partner_terms_request"),
        CheckConstraint("version > 0 AND stock_per_sale > 0", name="ck_fp_partner_terms_quantity"),
        CheckConstraint("EXTRACT(DAY FROM effective_on) = 1", name="ck_fp_partner_terms_month"),
        scoped("contract_id", "fp_partner_contracts", "fk_fp_partner_terms_contract"),
    )
    contract_id: Mapped[uuid.UUID] = mapped_column()
    version: Mapped[int] = mapped_column(Integer)
    effective_on: Mapped[date] = mapped_column(Date)
    active: Mapped[bool] = mapped_column(Boolean)
    stock_per_sale: Mapped[Decimal] = mapped_column(Numeric(18, 6))
    rules: Mapped[dict[str, JsonValue]] = mapped_column(JSONB)
    request_key: Mapped[uuid.UUID] = mapped_column()
    request_hash: Mapped[str] = mapped_column(String(64))
    actor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))


class PartnerPosting(PartnerBase):
    __tablename__ = "fp_partner_postings"
    __table_args__ = (
        UniqueConstraint("venue_id", "id", name="uq_fp_partner_posting_scope"),
        UniqueConstraint("venue_id", "request_key", name="uq_fp_partner_posting_request"),
        scoped("contract_id", "fp_partner_contracts", "fk_fp_partner_posting_contract"),
    )
    contract_id: Mapped[uuid.UUID] = mapped_column()
    kind: Mapped[str] = mapped_column(String(20))
    request_key: Mapped[uuid.UUID] = mapped_column()
    request_hash: Mapped[str] = mapped_column(String(64))
    reason: Mapped[str] = mapped_column(String(300))
    actor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))


class PartnerEvent(PartnerBase):
    __tablename__ = "fp_partner_events"
    __table_args__ = (
        UniqueConstraint("venue_id", "id", name="uq_fp_partner_event_scope"),
        Index(
            "uq_fp_partner_sale_unit",
            "venue_id",
            "order_id",
            "line_id",
            "unit",
            unique=True,
            postgresql_where=text("kind = 'sale'"),
        ),
        Index(
            "uq_fp_partner_refund_unit",
            "venue_id",
            "cash_entry_id",
            "line_id",
            "unit",
            unique=True,
            postgresql_where=text("kind = 'refund'"),
        ),
        Index(
            "uq_fp_partner_loss_operation",
            "venue_id",
            "stock_operation_id",
            unique=True,
            postgresql_where=text("kind IN ('waste','return')"),
        ),
        CheckConstraint(
            "kind IN ('sale','refund','return','waste')", name="ck_fp_partner_event_kind"
        ),
        CheckConstraint(
            "physical_quantity >= 0 AND loss_cents >= 0", name="ck_fp_partner_event_quantity"
        ),
        CheckConstraint(
            "posting_month >= source_month AND EXTRACT(DAY FROM posting_month) = 1 AND EXTRACT(DAY FROM source_month) = 1",
            name="ck_fp_partner_event_month",
        ),
        scoped("contract_id", "fp_partner_contracts", "fk_fp_partner_event_contract"),
        scoped("terms_id", "fp_partner_terms", "fk_fp_partner_event_terms"),
        scoped("posting_id", "fp_partner_postings", "fk_fp_partner_event_posting"),
        scoped("original_id", "fp_partner_events", "fk_fp_partner_event_original"),
        scoped("stock_operation_id", "fp_stock_operations", "fk_fp_partner_event_stock"),
        scoped("order_id", "fp_orders", "fk_fp_partner_event_order"),
        scoped("cash_entry_id", "fp_cash_entries", "fk_fp_partner_event_cash"),
    )
    contract_id: Mapped[uuid.UUID] = mapped_column(index=True)
    terms_id: Mapped[uuid.UUID] = mapped_column()
    posting_id: Mapped[uuid.UUID] = mapped_column()
    original_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    stock_operation_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    order_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    cash_entry_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    line_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    unit: Mapped[int | None] = mapped_column(Integer, nullable=True)
    kind: Mapped[str] = mapped_column(String(12))
    occurred_on: Mapped[date] = mapped_column(Date)
    source_month: Mapped[date] = mapped_column(Date)
    posting_month: Mapped[date] = mapped_column(Date)
    physical_quantity: Mapped[Decimal] = mapped_column(Numeric(18, 6))
    gross_cents: Mapped[int] = mapped_column(BigInteger)
    net_cents: Mapped[int] = mapped_column(BigInteger)
    unit_fee_cents: Mapped[int] = mapped_column(BigInteger)
    loss_cents: Mapped[int] = mapped_column(BigInteger)
    evidence: Mapped[list[dict[str, JsonValue]]] = mapped_column(JSONB)


class PartnerSettlement(PartnerBase):
    __tablename__ = "fp_partner_settlements"
    __table_args__ = (
        UniqueConstraint("venue_id", "id", name="uq_fp_partner_settlement_scope"),
        UniqueConstraint("contract_id", "month", name="uq_fp_partner_settlement_month"),
        UniqueConstraint("venue_id", "request_key", name="uq_fp_partner_settlement_request"),
        CheckConstraint("EXTRACT(DAY FROM month) = 1", name="ck_fp_partner_settlement_month"),
        scoped("contract_id", "fp_partner_contracts", "fk_fp_partner_settlement_contract"),
    )
    contract_id: Mapped[uuid.UUID] = mapped_column()
    month: Mapped[date] = mapped_column(Date)
    payable_to_partner_cents: Mapped[int] = mapped_column(BigInteger)
    snapshot: Mapped[dict[str, JsonValue]] = mapped_column(JSONB)
    request_key: Mapped[uuid.UUID] = mapped_column()
    request_hash: Mapped[str] = mapped_column(String(64))
    reason: Mapped[str] = mapped_column(String(300))
    actor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))


class LoanAccount(PartnerBase):
    __tablename__ = "fp_loan_accounts"
    __table_args__ = (
        UniqueConstraint("venue_id", "id", name="uq_fp_loan_account_scope"),
        UniqueConstraint("venue_id", "owner_id", "reference", name="uq_fp_loan_account_reference"),
        CheckConstraint("deposit_per_unit_cents >= 0", name="ck_fp_loan_account_deposit"),
        scoped("owner_id", "fp_stock_owners", "fk_fp_loan_account_owner"),
    )
    owner_id: Mapped[uuid.UUID] = mapped_column()
    name: Mapped[str] = mapped_column(String(120))
    reference: Mapped[str] = mapped_column(String(120))
    serialized: Mapped[bool] = mapped_column(Boolean)
    deposit_per_unit_cents: Mapped[int] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String(3))


class LoanEntry(PartnerBase):
    __tablename__ = "fp_loan_entries"
    __table_args__ = (
        UniqueConstraint("venue_id", "request_key", name="uq_fp_loan_entry_request"),
        UniqueConstraint("venue_id", "cash_entry_id", name="uq_fp_loan_entry_cash"),
        Index(
            "uq_fp_loan_entry_reference",
            "venue_id",
            "external_reference",
            unique=True,
            postgresql_where=text("external_reference <> ''"),
        ),
        CheckConstraint(
            "kind IN ('received','returned','broken','deposit_paid','deposit_refunded','deposit_forfeited')",
            name="ck_fp_loan_entry_kind",
        ),
        CheckConstraint("quantity >= 0 AND amount_cents >= 0", name="ck_fp_loan_entry_amount"),
        scoped("account_id", "fp_loan_accounts", "fk_fp_loan_entry_account"),
        scoped("cash_entry_id", "fp_cash_entries", "fk_fp_loan_entry_cash"),
    )
    account_id: Mapped[uuid.UUID] = mapped_column()
    kind: Mapped[str] = mapped_column(String(20))
    quantity: Mapped[int] = mapped_column(Integer)
    amount_cents: Mapped[int] = mapped_column(Integer)
    cash_entry_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    external_reference: Mapped[str] = mapped_column(String(160))
    request_key: Mapped[uuid.UUID] = mapped_column()
    request_hash: Mapped[str] = mapped_column(String(64))
    reason: Mapped[str] = mapped_column(String(300))
    actor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
