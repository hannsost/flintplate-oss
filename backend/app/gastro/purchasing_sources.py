"""Bounded, read-only supplier options for a caller-provided physical shortage.

The caller owns authorization and the shortage calculation. This helper neither
subtracts incoming deliveries nor places orders. It lists at most 50 priced
catalog entries, alphabetically by supplier and SKU, rather than claiming to
find a globally cheapest basket. Prices and delivery dates are calculations as
of the requested instant; creating an order still validates the current sources.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.gastro.inventory_models import StockItem
from app.gastro.models import Venue
from app.gastro.purchasing_math import earliest_delivery, minimum_packs_for_need, priced_packs
from app.gastro.purchasing_models import Supplier, SupplierPrice, SupplierProduct
from app.gastro.purchasing_terms_models import SupplierOrderTerms
from app.gastro.purchasing_terms_schemas import ProductConditions, SupplierRules

MAX_SOURCE_OPTIONS = 50


class SupplierSourceOption(BaseModel):
    supplier_id: uuid.UUID
    supplier_name: str
    product_id: uuid.UUID
    price_id: uuid.UUID
    price_version: int
    price_effective_on: date
    supplier_terms_id: uuid.UUID | None
    supplier_terms_version: int | None
    supplier_sku: str
    pack_name: str
    pack_quantity: Decimal
    unit: str
    currency: str
    need_quantity: Decimal
    packs: int | None = None
    bonus_packs: int | None = None
    paid_quantity: Decimal | None = None
    ordered_bonus_quantity: Decimal | None = None
    ordered_quantity: Decimal | None = None
    overage_quantity: Decimal | None = None
    pack_price_cents: int | None = None
    net_cents: int | None = None
    tax_rate_bps: int
    earliest_delivery_on: date | None = None
    minimum_order_net_cents: int | None = None
    shortfall_to_minimum_net_cents: int | None = None
    blocking_reasons: list[str] = Field(default_factory=list)


async def suggested_sources(
    db: AsyncSession,
    venue: Venue,
    item_id: uuid.UUID,
    need: Decimal,
    as_of: datetime,
    *,
    limit: int = MAX_SOURCE_OPTIONS,
) -> list[SupplierSourceOption]:
    """Return up to ``limit`` eligible options (1–50), including blocked quotes.

    Unknown or not-yet-priced catalog entries cannot quote a cost and are not
    listed. Unknown supplier conditions leave delivery/minimum fields null.
    The limit applies before calculation, so an invalid option never silently
    selects an entirely different supplier or suppresses its valid neighbours.
    No ORM model is mutated and the function does not flush the caller's session.
    """
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("Berechnungszeit benötigt einen Zeitzonenbezug.")
    if not need.is_finite() or need < 0:
        raise ValueError("Bedarf muss eine endliche nichtnegative Menge sein.")
    if isinstance(limit, bool) or not 1 <= limit <= MAX_SOURCE_OPTIONS:
        raise ValueError("Lieferantenauswahl ist auf 1 bis 50 Katalogoptionen begrenzt.")
    if need == 0:
        return []
    on_date = as_of.astimezone(ZoneInfo(venue.timezone)).date()
    ranked_prices = (
        select(
            SupplierPrice.id.label("price_id"),
            func.row_number()
            .over(
                partition_by=SupplierPrice.product_id,
                order_by=(SupplierPrice.effective_on.desc(), SupplierPrice.version.desc()),
            )
            .label("position"),
        )
        .where(
            SupplierPrice.venue_id == venue.id,
            SupplierPrice.effective_on <= on_date,
            SupplierPrice.created_at <= as_of,
        )
        .subquery()
    )
    # Suppress autoflush as well as explicit writes: this is a planning read.
    with db.no_autoflush:
        candidates = (
            await db.execute(
                select(SupplierProduct, Supplier, SupplierPrice, StockItem.unit)
                .join(Supplier, Supplier.id == SupplierProduct.supplier_id)
                .join(StockItem, StockItem.id == SupplierProduct.item_id)
                .join(SupplierPrice, SupplierPrice.product_id == SupplierProduct.id)
                .join(ranked_prices, ranked_prices.c.price_id == SupplierPrice.id)
                .where(
                    SupplierProduct.venue_id == venue.id,
                    Supplier.venue_id == venue.id,
                    StockItem.venue_id == venue.id,
                    SupplierPrice.venue_id == venue.id,
                    SupplierProduct.item_id == item_id,
                    SupplierProduct.created_at <= as_of,
                    Supplier.created_at <= as_of,
                    StockItem.created_at <= as_of,
                    ranked_prices.c.position == 1,
                )
                .order_by(Supplier.name, SupplierProduct.supplier_sku, SupplierProduct.id)
                .limit(limit)
            )
        ).all()
        if not candidates:
            return []
        supplier_ids = {supplier.id for _, supplier, _, _ in candidates}
        terms_rows = (
            await db.execute(
                select(SupplierOrderTerms)
                .where(
                    SupplierOrderTerms.venue_id == venue.id,
                    SupplierOrderTerms.supplier_id.in_(supplier_ids),
                    SupplierOrderTerms.effective_on <= on_date,
                    SupplierOrderTerms.created_at <= as_of,
                )
                .order_by(SupplierOrderTerms.version.desc())
            )
        ).scalars()
        terms_by_supplier: dict[uuid.UUID, SupplierOrderTerms] = {}
        for row in terms_rows:
            terms_by_supplier.setdefault(row.supplier_id, row)

    options: list[SupplierSourceOption] = []
    for product, supplier, price, unit in candidates:
        terms = terms_by_supplier.get(supplier.id)
        rules = SupplierRules.model_validate(terms.rules) if terms else None
        option = SupplierSourceOption(
            supplier_id=supplier.id,
            supplier_name=supplier.name,
            product_id=product.id,
            price_id=price.id,
            price_version=price.version,
            price_effective_on=price.effective_on,
            supplier_terms_id=terms.id if terms else None,
            supplier_terms_version=terms.version if terms else None,
            supplier_sku=product.supplier_sku,
            pack_name=product.pack_name,
            pack_quantity=product.pack_quantity,
            unit=unit,
            currency=venue.currency,
            need_quantity=need,
            tax_rate_bps=price.tax_rate_bps,
            minimum_order_net_cents=rules.minimum_order_net_cents if rules else None,
        )
        conditions = ProductConditions.model_validate(price.conditions)
        try:
            packs = minimum_packs_for_need(need, product.pack_quantity, conditions)
            applied, bonus_packs = priced_packs(packs, price.pack_price_cents, conditions)
            option.packs = packs
            option.bonus_packs = bonus_packs
            option.paid_quantity = packs * product.pack_quantity
            option.ordered_bonus_quantity = bonus_packs * product.pack_quantity
            option.ordered_quantity = option.paid_quantity + option.ordered_bonus_quantity
            option.overage_quantity = option.ordered_quantity - need
            option.pack_price_cents = applied
            option.net_cents = packs * applied
            if option.net_cents > 1000000000:
                option.blocking_reasons.append("Bestellwert überschreitet die Buchungsgrenze.")
            if rules is not None:
                option.shortfall_to_minimum_net_cents = max(
                    0, rules.minimum_order_net_cents - option.net_cents
                )
                if option.shortfall_to_minimum_net_cents:
                    option.blocking_reasons.append(
                        "Mindestbestellwert der Lieferantenbestellung noch nicht erreicht."
                    )
        except HTTPException as exc:
            if exc.status_code != 422:
                raise
            option.blocking_reasons.append(str(exc.detail))
        if rules is not None:
            try:
                option.earliest_delivery_on = earliest_delivery(as_of, rules, venue.timezone)
            except HTTPException as exc:
                if exc.status_code != 422:
                    raise
                option.blocking_reasons.append(str(exc.detail))
        options.append(option)
    return options
