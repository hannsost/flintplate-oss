"""Supplier catalogs, frozen purchase terms, receiving and invoice verification."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import JsonValue
from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
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


class PurchasingBase(InventoryBase):
    __abstract__ = True
    venue_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("fp_venues.id"), index=True)


class Supplier(PurchasingBase):
    __tablename__ = "fp_suppliers"
    __table_args__ = (
        UniqueConstraint("venue_id", "id", name="uq_fp_supplier_scope"),
        UniqueConstraint("venue_id", "name", name="uq_fp_supplier_name"),
    )
    name: Mapped[str] = mapped_column(String(120))
    reference: Mapped[str] = mapped_column(String(120), default="", server_default="")
    contact: Mapped[str] = mapped_column(String(200), default="", server_default="")


class SupplierProduct(PurchasingBase):
    __tablename__ = "fp_supplier_products"
    __table_args__ = (
        UniqueConstraint("venue_id", "id", name="uq_fp_supplier_product_scope"),
        UniqueConstraint(
            "venue_id", "supplier_id", "supplier_sku", name="uq_fp_supplier_product_sku"
        ),
        CheckConstraint("pack_quantity > 0", name="ck_fp_supplier_pack_quantity"),
        ForeignKeyConstraint(
            ["venue_id", "supplier_id"],
            ["fp_suppliers.venue_id", "fp_suppliers.id"],
            name="fk_fp_supplier_product_supplier",
        ),
        ForeignKeyConstraint(
            ["venue_id", "item_id"],
            ["fp_stock_items.venue_id", "fp_stock_items.id"],
            name="fk_fp_supplier_product_item",
        ),
    )
    supplier_id: Mapped[uuid.UUID] = mapped_column()
    item_id: Mapped[uuid.UUID] = mapped_column()
    supplier_sku: Mapped[str] = mapped_column(String(80))
    pack_name: Mapped[str] = mapped_column(String(80))
    pack_quantity: Mapped[Decimal] = mapped_column(Numeric(18, 6))
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")


class SupplierPrice(PurchasingBase):
    __tablename__ = "fp_supplier_prices"
    __table_args__ = (
        UniqueConstraint("venue_id", "id", name="uq_fp_supplier_price_scope"),
        UniqueConstraint("product_id", "version", name="uq_fp_supplier_price_version"),
        CheckConstraint("pack_price_cents >= 0", name="ck_fp_supplier_price_amount"),
        CheckConstraint("tax_rate_bps BETWEEN 0 AND 10000", name="ck_fp_supplier_price_tax"),
        ForeignKeyConstraint(
            ["venue_id", "product_id"],
            ["fp_supplier_products.venue_id", "fp_supplier_products.id"],
            name="fk_fp_supplier_price_product",
        ),
    )
    conditions: Mapped[dict[str, JsonValue]] = mapped_column(
        JSONB, default=dict, server_default="{}"
    )
    product_id: Mapped[uuid.UUID] = mapped_column()
    version: Mapped[int] = mapped_column(Integer)
    effective_on: Mapped[date] = mapped_column(Date)
    pack_price_cents: Mapped[int] = mapped_column(Integer)
    tax_rate_bps: Mapped[int] = mapped_column(Integer)
    actor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))


class PurchaseOrder(PurchasingBase):
    __tablename__ = "fp_purchase_orders"
    __table_args__ = (
        UniqueConstraint("venue_id", "id", name="uq_fp_purchase_order_scope"),
        UniqueConstraint("venue_id", "request_key", name="uq_fp_purchase_order_request"),
        UniqueConstraint("venue_id", "number", name="uq_fp_purchase_order_number"),
        ForeignKeyConstraint(
            ["venue_id", "supplier_terms_id"],
            ["fp_supplier_order_terms.venue_id", "fp_supplier_order_terms.id"],
            name="fk_fp_purchase_order_supplier_terms",
        ),
        CheckConstraint(
            "status IN ('draft','ordered','partial','received','closed','cancelled')",
            name="ck_fp_purchase_order_status",
        ),
        ForeignKeyConstraint(
            ["venue_id", "supplier_id"],
            ["fp_suppliers.venue_id", "fp_suppliers.id"],
            name="fk_fp_purchase_order_supplier",
        ),
        ForeignKeyConstraint(
            ["venue_id", "owner_id"],
            ["fp_stock_owners.venue_id", "fp_stock_owners.id"],
            name="fk_fp_purchase_order_owner",
        ),
        ForeignKeyConstraint(
            ["venue_id", "location_id"],
            ["fp_stock_locations.venue_id", "fp_stock_locations.id"],
            name="fk_fp_purchase_order_location",
        ),
    )
    supplier_id: Mapped[uuid.UUID] = mapped_column()
    owner_id: Mapped[uuid.UUID] = mapped_column()
    location_id: Mapped[uuid.UUID] = mapped_column()
    supplier_terms_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    supplier_terms_snapshot: Mapped[dict[str, JsonValue]] = mapped_column(
        JSONB, default=dict, server_default="{}"
    )
    earliest_delivery_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    number: Mapped[str] = mapped_column(String(24))
    status: Mapped[str] = mapped_column(String(12), default="draft", server_default="draft")
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    request_key: Mapped[uuid.UUID] = mapped_column()
    request_hash: Mapped[str] = mapped_column(String(64))
    expected_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    currency: Mapped[str] = mapped_column(String(3))
    note: Mapped[str] = mapped_column(String(300))
    actor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))


class PurchaseOrderLine(PurchasingBase):
    __tablename__ = "fp_purchase_order_lines"
    __table_args__ = (
        UniqueConstraint("venue_id", "id", name="uq_fp_purchase_line_scope"),
        UniqueConstraint("order_id", "product_id", name="uq_fp_purchase_line_product"),
        CheckConstraint(
            "ordered_bonus_quantity >= 0 AND ordered_quantity = packs * pack_quantity + ordered_bonus_quantity",
            name="ck_fp_purchase_line_bonus",
        ),
        CheckConstraint(
            "packs > 0 AND ordered_quantity > 0 AND pack_quantity > 0",
            name="ck_fp_purchase_line_quantity",
        ),
        CheckConstraint(
            "pack_price_cents >= 0 AND tax_rate_bps BETWEEN 0 AND 10000",
            name="ck_fp_purchase_line_price",
        ),
        ForeignKeyConstraint(
            ["venue_id", "order_id"],
            ["fp_purchase_orders.venue_id", "fp_purchase_orders.id"],
            name="fk_fp_purchase_line_order",
        ),
        ForeignKeyConstraint(
            ["venue_id", "product_id"],
            ["fp_supplier_products.venue_id", "fp_supplier_products.id"],
            name="fk_fp_purchase_line_product",
        ),
        ForeignKeyConstraint(
            ["venue_id", "item_id"],
            ["fp_stock_items.venue_id", "fp_stock_items.id"],
            name="fk_fp_purchase_line_item",
        ),
        ForeignKeyConstraint(
            ["venue_id", "price_id"],
            ["fp_supplier_prices.venue_id", "fp_supplier_prices.id"],
            name="fk_fp_purchase_line_price",
        ),
    )
    order_id: Mapped[uuid.UUID] = mapped_column(index=True)
    product_id: Mapped[uuid.UUID] = mapped_column()
    item_id: Mapped[uuid.UUID] = mapped_column()
    price_id: Mapped[uuid.UUID] = mapped_column()
    item_name: Mapped[str] = mapped_column(String(120))
    unit: Mapped[str] = mapped_column(String(10))
    supplier_sku: Mapped[str] = mapped_column(String(80))
    pack_name: Mapped[str] = mapped_column(String(80))
    pack_quantity: Mapped[Decimal] = mapped_column(Numeric(18, 6))
    packs: Mapped[int] = mapped_column(Integer)
    ordered_quantity: Mapped[Decimal] = mapped_column(Numeric(18, 6))
    ordered_bonus_quantity: Mapped[Decimal] = mapped_column(
        Numeric(18, 6), default=0, server_default="0"
    )
    conditions_snapshot: Mapped[dict[str, JsonValue]] = mapped_column(
        JSONB, default=dict, server_default="{}"
    )
    pack_price_cents: Mapped[int] = mapped_column(Integer)
    tax_rate_bps: Mapped[int] = mapped_column(Integer)


class PurchaseReceipt(PurchasingBase):
    __tablename__ = "fp_purchase_receipts"
    __table_args__ = (
        ForeignKeyConstraint(
            ["venue_id", "confirmation_id"],
            ["fp_delivery_confirmations.venue_id", "fp_delivery_confirmations.id"],
            name="fk_fp_purchase_receipt_confirmation",
        ),
        UniqueConstraint("venue_id", "request_key", name="uq_fp_purchase_receipt_request"),
        CheckConstraint(
            "accepted_bonus_quantity BETWEEN 0 AND accepted_quantity AND rejected_bonus_quantity BETWEEN 0 AND rejected_quantity",
            name="ck_fp_purchase_receipt_bonus",
        ),
        CheckConstraint(
            "accepted_quantity >= 0 AND rejected_quantity >= 0 AND accepted_quantity + rejected_quantity > 0",
            name="ck_fp_purchase_receipt_quantity",
        ),
        CheckConstraint(
            "(accepted_quantity > 0 AND stock_operation_id IS NOT NULL) OR (accepted_quantity = 0 AND stock_operation_id IS NULL)",
            name="ck_fp_purchase_receipt_posting",
        ),
        ForeignKeyConstraint(
            ["venue_id", "line_id"],
            ["fp_purchase_order_lines.venue_id", "fp_purchase_order_lines.id"],
            name="fk_fp_purchase_receipt_line",
        ),
        ForeignKeyConstraint(
            ["venue_id", "stock_operation_id"],
            ["fp_stock_operations.venue_id", "fp_stock_operations.id"],
            name="fk_fp_purchase_receipt_operation",
        ),
    )
    confirmation_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True, index=True)
    line_id: Mapped[uuid.UUID] = mapped_column(index=True)
    stock_operation_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True, unique=True)
    request_key: Mapped[uuid.UUID] = mapped_column()
    request_hash: Mapped[str] = mapped_column(String(64))
    accepted_quantity: Mapped[Decimal] = mapped_column(Numeric(18, 6))
    rejected_quantity: Mapped[Decimal] = mapped_column(Numeric(18, 6))
    accepted_bonus_quantity: Mapped[Decimal] = mapped_column(
        Numeric(18, 6), default=0, server_default="0"
    )
    rejected_bonus_quantity: Mapped[Decimal] = mapped_column(
        Numeric(18, 6), default=0, server_default="0"
    )
    reference: Mapped[str] = mapped_column(String(120))
    rejection_reason: Mapped[str] = mapped_column(String(300))
    details: Mapped[dict[str, JsonValue]] = mapped_column(JSONB)
    actor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))


class PurchaseInvoice(PurchasingBase):
    __tablename__ = "fp_purchase_invoices"
    __table_args__ = (
        UniqueConstraint("venue_id", "id", name="uq_fp_purchase_invoice_scope"),
        UniqueConstraint("venue_id", "request_key", name="uq_fp_purchase_invoice_request"),
        Index(
            "uq_fp_purchase_invoice_number",
            "venue_id",
            "supplier_id",
            "number",
            unique=True,
            postgresql_where=text("status <> 'rejected'"),
        ),
        CheckConstraint(
            "status IN ('draft','approved','rejected')", name="ck_fp_purchase_invoice_status"
        ),
        ForeignKeyConstraint(
            ["venue_id", "supplier_id"],
            ["fp_suppliers.venue_id", "fp_suppliers.id"],
            name="fk_fp_purchase_invoice_supplier",
        ),
    )
    supplier_id: Mapped[uuid.UUID] = mapped_column()
    number: Mapped[str] = mapped_column(String(80))
    issued_on: Mapped[date] = mapped_column(Date)
    currency: Mapped[str] = mapped_column(String(3))
    status: Mapped[str] = mapped_column(String(12), default="draft", server_default="draft")
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    request_key: Mapped[uuid.UUID] = mapped_column()
    request_hash: Mapped[str] = mapped_column(String(64))
    actor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decided_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    decision_reason: Mapped[str] = mapped_column(String(300), default="", server_default="")
    approval_snapshot: Mapped[dict[str, JsonValue] | None] = mapped_column(JSONB, nullable=True)


class PurchaseInvoiceLine(PurchasingBase):
    __tablename__ = "fp_purchase_invoice_lines"
    __table_args__ = (
        UniqueConstraint("invoice_id", "purchase_line_id", name="uq_fp_purchase_invoice_line"),
        CheckConstraint(
            "quantity > 0 AND net_cents >= 0 AND tax_rate_bps BETWEEN 0 AND 10000",
            name="ck_fp_purchase_invoice_line_value",
        ),
        ForeignKeyConstraint(
            ["venue_id", "invoice_id"],
            ["fp_purchase_invoices.venue_id", "fp_purchase_invoices.id"],
            name="fk_fp_purchase_invoice_line_invoice",
        ),
        ForeignKeyConstraint(
            ["venue_id", "purchase_line_id"],
            ["fp_purchase_order_lines.venue_id", "fp_purchase_order_lines.id"],
            name="fk_fp_purchase_invoice_line_order",
        ),
    )
    invoice_id: Mapped[uuid.UUID] = mapped_column(index=True)
    purchase_line_id: Mapped[uuid.UUID] = mapped_column()
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 6))
    net_cents: Mapped[int] = mapped_column(Integer)
    tax_rate_bps: Mapped[int] = mapped_column(Integer)
