"""Purchasing through physical receiving and a reproducible three-way invoice check."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import cast
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select

from app.gastro import inventory
from app.gastro import service as svc
from app.gastro.inventory_models import StockOperation, StockOwner
from app.gastro.inventory_schemas import ReceiptInput, Unit
from app.gastro.purchasing_math import earliest_delivery, priced_packs, request_digest
from app.gastro.purchasing_models import (
    PurchaseInvoice,
    PurchaseInvoiceLine,
    PurchaseOrder,
    PurchaseOrderLine,
    PurchaseReceipt,
    Supplier,
    SupplierPrice,
    SupplierProduct,
)
from app.gastro.purchasing_schemas import (
    CatalogInput,
    CatalogRead,
    InvoiceCheck,
    InvoiceDecision,
    InvoiceInput,
    InvoiceLineCheck,
    OrderStateInput,
    PriceInput,
    PriceRead,
    PurchaseInvoiceRead,
    PurchaseLineRead,
    PurchaseOrderInput,
    PurchaseOrderRead,
    PurchaseReceiptInput,
    PurchaseReceiptRead,
    PurchasingSnapshot,
    SupplierInput,
    SupplierRead,
)
from app.gastro.purchasing_terms_models import SupplierOrderTerms
from app.gastro.purchasing_terms_schemas import ProductConditions, SupplierRules, SupplierTermsRead
from app.gastro.router import DB, Actor, private_response

router = APIRouter(dependencies=[Depends(private_response)])
PREFIX = "/venues/{venue_id}/purchasing"


def cents(amount: Decimal) -> int:
    return int(amount.quantize(Decimal(1), rounding=ROUND_HALF_UP))


async def supplier_for(db: DB, venue_id: uuid.UUID, supplier_id: uuid.UUID) -> Supplier:
    row = (
        await db.execute(
            select(Supplier).where(Supplier.venue_id == venue_id, Supplier.id == supplier_id)
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, "Lieferant nicht gefunden.")
    return row


async def product_for(db: DB, venue_id: uuid.UUID, product_id: uuid.UUID) -> SupplierProduct:
    row = (
        await db.execute(
            select(SupplierProduct).where(
                SupplierProduct.venue_id == venue_id, SupplierProduct.id == product_id
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, "Lieferartikel nicht gefunden.")
    return row


async def order_for(db: DB, venue_id: uuid.UUID, order_id: uuid.UUID) -> PurchaseOrder:
    row = (
        await db.execute(
            select(PurchaseOrder).where(
                PurchaseOrder.venue_id == venue_id, PurchaseOrder.id == order_id
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, "Einkaufsbestellung nicht gefunden.")
    return row


async def line_for(db: DB, venue_id: uuid.UUID, line_id: uuid.UUID) -> PurchaseOrderLine:
    row = (
        await db.execute(
            select(PurchaseOrderLine).where(
                PurchaseOrderLine.venue_id == venue_id, PurchaseOrderLine.id == line_id
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, "Bestellposition nicht gefunden.")
    return row


async def price_for(
    db: DB, venue_id: uuid.UUID, product_id: uuid.UUID, today: date
) -> SupplierPrice | None:
    return (
        await db.execute(
            select(SupplierPrice)
            .where(
                SupplierPrice.venue_id == venue_id,
                SupplierPrice.product_id == product_id,
                SupplierPrice.effective_on <= today,
            )
            .order_by(SupplierPrice.effective_on.desc(), SupplierPrice.version.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def terms_for(
    db: DB, venue_id: uuid.UUID, supplier_id: uuid.UUID, today: date
) -> SupplierOrderTerms | None:
    return (
        await db.execute(
            select(SupplierOrderTerms)
            .where(
                SupplierOrderTerms.venue_id == venue_id,
                SupplierOrderTerms.supplier_id == supplier_id,
                SupplierOrderTerms.effective_on <= today,
            )
            .order_by(SupplierOrderTerms.effective_on.desc(), SupplierOrderTerms.version.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def catalog_read(db: DB, product: SupplierProduct, today: date) -> CatalogRead:
    prices = (
        (
            await db.execute(
                select(SupplierPrice)
                .where(
                    SupplierPrice.venue_id == product.venue_id,
                    SupplierPrice.product_id == product.id,
                )
                .order_by(SupplierPrice.effective_on.desc(), SupplierPrice.version.desc())
            )
        )
        .scalars()
        .all()
    )
    current = next((price for price in prices if price.effective_on <= today), None)
    return CatalogRead(
        id=product.id,
        created_at=product.created_at,
        supplier_id=product.supplier_id,
        item_id=product.item_id,
        supplier_sku=product.supplier_sku,
        pack_name=product.pack_name,
        pack_quantity=product.pack_quantity,
        version=product.version,
        current_price=PriceRead.model_validate(current) if current else None,
        prices=[PriceRead.model_validate(price) for price in prices],
    )


async def receipts_for(db: DB, venue_id: uuid.UUID, line_id: uuid.UUID) -> list[PurchaseReceipt]:
    return list(
        (
            await db.execute(
                select(PurchaseReceipt)
                .where(
                    PurchaseReceipt.venue_id == venue_id,
                    PurchaseReceipt.line_id == line_id,
                )
                .order_by(PurchaseReceipt.created_at, PurchaseReceipt.id)
            )
        ).scalars()
    )


async def order_read(db: DB, order: PurchaseOrder) -> PurchaseOrderRead:
    lines = (
        (
            await db.execute(
                select(PurchaseOrderLine)
                .where(
                    PurchaseOrderLine.venue_id == order.venue_id,
                    PurchaseOrderLine.order_id == order.id,
                )
                .order_by(PurchaseOrderLine.supplier_sku)
            )
        )
        .scalars()
        .all()
    )
    result = []
    receipts: list[PurchaseReceiptRead] = []
    tax = 0
    net = 0
    for line in lines:
        rows = await receipts_for(db, order.venue_id, line.id)
        received = sum((row.accepted_quantity for row in rows), Decimal(0))
        bonus_received = sum((row.accepted_bonus_quantity for row in rows), Decimal(0))
        rejected = sum((row.rejected_quantity for row in rows), Decimal(0))
        amount = line.packs * line.pack_price_cents
        net += amount
        tax += cents(Decimal(amount) * line.tax_rate_bps / 10000)
        result.append(
            PurchaseLineRead(
                id=line.id,
                created_at=line.created_at,
                product_id=line.product_id,
                item_id=line.item_id,
                price_id=line.price_id,
                item_name=line.item_name,
                unit=cast(Unit, line.unit),
                supplier_sku=line.supplier_sku,
                pack_name=line.pack_name,
                pack_quantity=line.pack_quantity,
                packs=line.packs,
                ordered_quantity=line.ordered_quantity,
                ordered_bonus_quantity=line.ordered_bonus_quantity,
                received_bonus_quantity=bonus_received,
                remaining_bonus_quantity=line.ordered_bonus_quantity - bonus_received,
                billable_received_quantity=received - bonus_received,
                conditions_snapshot=ProductConditions.model_validate(line.conditions_snapshot),
                received_quantity=received,
                rejected_quantity=rejected,
                remaining_quantity=line.ordered_quantity - received,
                pack_price_cents=line.pack_price_cents,
                tax_rate_bps=line.tax_rate_bps,
                net_cents=amount,
            )
        )
        receipts.extend(PurchaseReceiptRead.model_validate(row) for row in rows)
    order_rules = SupplierRules.model_validate(order.supplier_terms_snapshot)
    return PurchaseOrderRead(
        supplier_terms_id=order.supplier_terms_id,
        supplier_terms_snapshot=order.supplier_terms_snapshot,
        earliest_delivery_on=order.earliest_delivery_on,
        shortfall_to_minimum_net_cents=max(0, order_rules.minimum_order_net_cents - net),
        id=order.id,
        created_at=order.created_at,
        supplier_id=order.supplier_id,
        owner_id=order.owner_id,
        location_id=order.location_id,
        number=order.number,
        status=order.status,
        version=order.version,
        request_key=order.request_key,
        expected_on=order.expected_on,
        currency=order.currency,
        note=order.note,
        lines=result,
        receipts=receipts,
        net_cents=net,
        tax_cents=tax,
        total_cents=net + tax,
    )


async def check_invoice(db: DB, invoice: PurchaseInvoice) -> InvoiceCheck:
    if invoice.approval_snapshot is not None:
        return InvoiceCheck.model_validate(invoice.approval_snapshot)
    rows = (
        (
            await db.execute(
                select(PurchaseInvoiceLine)
                .where(
                    PurchaseInvoiceLine.venue_id == invoice.venue_id,
                    PurchaseInvoiceLine.invoice_id == invoice.id,
                )
                .order_by(PurchaseInvoiceLine.id)
            )
        )
        .scalars()
        .all()
    )
    checks = []
    net = 0
    tax = 0
    for row in rows:
        line = await line_for(db, invoice.venue_id, row.purchase_line_id)
        receipts = await receipts_for(db, invoice.venue_id, line.id)
        received_bonus = sum((receipt.accepted_bonus_quantity for receipt in receipts), Decimal(0))
        received = (
            sum((receipt.accepted_quantity for receipt in receipts), Decimal(0)) - received_bonus
        )
        billed_totals = (
            await db.execute(
                select(
                    func.coalesce(func.sum(PurchaseInvoiceLine.quantity), 0),
                    func.coalesce(func.sum(PurchaseInvoiceLine.net_cents), 0),
                )
                .join(PurchaseInvoice, PurchaseInvoice.id == PurchaseInvoiceLine.invoice_id)
                .where(
                    PurchaseInvoiceLine.venue_id == invoice.venue_id,
                    PurchaseInvoiceLine.purchase_line_id == line.id,
                    PurchaseInvoice.status == "approved",
                    PurchaseInvoice.id != invoice.id,
                )
            )
        ).one()
        billed = Decimal(str(billed_totals[0]))
        # Allocate the cumulative rounded amount, so splitting invoices cannot create extra cents.
        expected = cents(
            (billed + row.quantity) * line.pack_price_cents / line.pack_quantity
        ) - int(billed_totals[1])
        differences = []
        if row.quantity > received - billed:
            differences.append(
                "Menge übersteigt den angenommenen, noch nicht abgerechneten Wareneingang."
            )
        if row.net_cents != expected:
            differences.append(
                f"Nettobetrag weicht um {row.net_cents - expected} Cent vom Bestellpreis ab."
            )
        if row.tax_rate_bps != line.tax_rate_bps:
            differences.append("Steuersatz weicht von der Bestellung ab.")
        checks.append(
            InvoiceLineCheck(
                purchase_line_id=line.id,
                quantity=row.quantity,
                net_cents=row.net_cents,
                tax_rate_bps=row.tax_rate_bps,
                item_name=line.item_name,
                unit=cast(Unit, line.unit),
                expected_net_cents=expected,
                received_quantity=received,
                received_bonus_quantity=received_bonus,
                already_invoiced_quantity=billed,
                differences=differences,
            )
        )
        net += row.net_cents
        tax += cents(Decimal(row.net_cents) * row.tax_rate_bps / 10000)
    return InvoiceCheck(
        matched=bool(checks) and not any(line.differences for line in checks),
        lines=checks,
        net_cents=net,
        tax_cents=tax,
        total_cents=net + tax,
    )


async def invoice_read(db: DB, invoice: PurchaseInvoice) -> PurchaseInvoiceRead:
    return PurchaseInvoiceRead(
        id=invoice.id,
        created_at=invoice.created_at,
        supplier_id=invoice.supplier_id,
        number=invoice.number,
        issued_on=invoice.issued_on,
        currency=invoice.currency,
        status=invoice.status,
        version=invoice.version,
        decision_reason=invoice.decision_reason,
        check=await check_invoice(db, invoice),
    )


@router.get(
    PREFIX + "/snapshot",
    response_model=PurchasingSnapshot,
    status_code=200,
    summary="Lieferanten, Gebinde, Preisstände, Bestellungen und Rechnungsprüfung",
)
async def snapshot(venue_id: uuid.UUID, user: Actor, db: DB) -> PurchasingSnapshot:
    venue, _ = await svc.venue_access(db, user, venue_id, svc.KITCHEN, lock=True)
    today = datetime.now(ZoneInfo(venue.timezone)).date()
    suppliers = (
        await db.execute(
            select(Supplier).where(Supplier.venue_id == venue_id).order_by(Supplier.name)
        )
    ).scalars()
    products = (
        (
            await db.execute(
                select(SupplierProduct)
                .where(SupplierProduct.venue_id == venue_id)
                .order_by(SupplierProduct.supplier_sku)
            )
        )
        .scalars()
        .all()
    )
    orders = (
        (
            await db.execute(
                select(PurchaseOrder)
                .where(PurchaseOrder.venue_id == venue_id)
                .order_by(PurchaseOrder.created_at.desc(), PurchaseOrder.id)
            )
        )
        .scalars()
        .all()
    )
    invoices = (
        (
            await db.execute(
                select(PurchaseInvoice)
                .where(PurchaseInvoice.venue_id == venue_id)
                .order_by(PurchaseInvoice.created_at.desc(), PurchaseInvoice.id)
            )
        )
        .scalars()
        .all()
    )
    return PurchasingSnapshot(
        supplier_terms=[
            SupplierTermsRead.model_validate(row)
            for row in (
                await db.execute(
                    select(SupplierOrderTerms)
                    .where(SupplierOrderTerms.venue_id == venue_id)
                    .order_by(SupplierOrderTerms.supplier_id, SupplierOrderTerms.version.desc())
                )
            ).scalars()
        ],
        business_date=today,
        suppliers=[SupplierRead.model_validate(row) for row in suppliers],
        catalog=[await catalog_read(db, row, today) for row in products],
        orders=[await order_read(db, row) for row in orders],
        invoices=[await invoice_read(db, row) for row in invoices],
    )


@router.post(
    PREFIX + "/suppliers",
    response_model=SupplierRead,
    status_code=201,
    summary="Lieferanten im eigenen Betrieb erfassen",
)
async def create_supplier(
    venue_id: uuid.UUID, data: SupplierInput, user: Actor, db: DB
) -> Supplier:
    await svc.venue_access(db, user, venue_id, svc.MANAGERS, lock=True)
    if (
        await db.execute(
            select(Supplier.id).where(Supplier.venue_id == venue_id, Supplier.name == data.name)
        )
    ).first():
        raise HTTPException(409, "Dieser Lieferant ist bereits erfasst.")
    row = Supplier(venue_id=venue_id, **data.model_dump())
    db.add(row)
    await db.flush()
    svc.event(db, venue_id, "purchasing.supplier_created", row.id, {}, user.id)
    return row


@router.post(
    PREFIX + "/catalog",
    response_model=CatalogRead,
    status_code=201,
    summary="Lieferartikel mit Gebindeumrechnung und erstem Nettopreis anlegen",
)
async def create_product(
    venue_id: uuid.UUID, data: CatalogInput, user: Actor, db: DB
) -> CatalogRead:
    venue, _ = await svc.venue_access(db, user, venue_id, svc.MANAGERS, lock=True)
    await supplier_for(db, venue_id, data.supplier_id)
    item = await inventory.item_for(db, venue_id, data.item_id)
    inventory.validate_quantity(item, data.pack_quantity)
    if (
        await db.execute(
            select(SupplierProduct.id).where(
                SupplierProduct.venue_id == venue_id,
                SupplierProduct.supplier_id == data.supplier_id,
                SupplierProduct.supplier_sku == data.supplier_sku,
            )
        )
    ).first():
        raise HTTPException(409, "Diese Lieferartikelnummer ist bereits erfasst.")
    product = SupplierProduct(
        venue_id=venue_id,
        supplier_id=data.supplier_id,
        item_id=item.id,
        supplier_sku=data.supplier_sku,
        pack_name=data.pack_name,
        pack_quantity=data.pack_quantity,
    )
    db.add(product)
    await db.flush()
    db.add(
        SupplierPrice(
            venue_id=venue_id,
            product_id=product.id,
            version=1,
            effective_on=data.effective_on,
            pack_price_cents=data.pack_price_cents,
            tax_rate_bps=data.tax_rate_bps,
            conditions=data.conditions.model_dump(mode="json", exclude_defaults=True),
            actor_id=user.id,
        )
    )
    svc.event(
        db, venue_id, "purchasing.catalog_created", product.id, {"item_id": str(item.id)}, user.id
    )
    await db.flush()
    return await catalog_read(db, product, datetime.now(ZoneInfo(venue.timezone)).date())


@router.post(
    PREFIX + "/prices",
    response_model=CatalogRead,
    status_code=201,
    summary="Neuen Lieferantenpreis ergänzen und bisherige Preisstände erhalten",
)
async def add_price(venue_id: uuid.UUID, data: PriceInput, user: Actor, db: DB) -> CatalogRead:
    venue, _ = await svc.venue_access(db, user, venue_id, svc.MANAGERS, lock=True)
    product = await product_for(db, venue_id, data.product_id)
    svc.check_version(product.version, data.expected_version)
    product.version += 1
    db.add(
        SupplierPrice(
            venue_id=venue_id,
            product_id=product.id,
            version=product.version,
            effective_on=data.effective_on,
            pack_price_cents=data.pack_price_cents,
            tax_rate_bps=data.tax_rate_bps,
            conditions=data.conditions.model_dump(mode="json", exclude_defaults=True),
            actor_id=user.id,
        )
    )
    svc.event(
        db, venue_id, "purchasing.price_added", product.id, {"version": product.version}, user.id
    )
    await db.flush()
    return await catalog_read(db, product, datetime.now(ZoneInfo(venue.timezone)).date())


@router.post(
    PREFIX + "/orders",
    response_model=PurchaseOrderRead,
    status_code=201,
    summary="Einkaufsentwurf mit festgehaltenen Gebinden und Preisen anlegen",
)
async def create_order(
    venue_id: uuid.UUID, data: PurchaseOrderInput, user: Actor, db: DB
) -> PurchaseOrderRead:
    venue, _ = await svc.venue_access(db, user, venue_id, svc.MANAGERS, lock=True)
    previous = (
        await db.execute(
            select(PurchaseOrder).where(
                PurchaseOrder.venue_id == venue_id,
                PurchaseOrder.request_key == data.request_key,
            )
        )
    ).scalar_one_or_none()
    if previous is not None:
        if previous.request_hash != request_digest(data):
            raise HTTPException(
                409, "Diese Vorgangs-ID gehört zu einer anderen Einkaufsbestellung."
            )
        return await order_read(db, previous)
    await supplier_for(db, venue_id, data.supplier_id)
    await inventory.location_for(db, venue_id, data.location_id)
    if not (
        await db.execute(
            select(StockOwner.id).where(
                StockOwner.venue_id == venue_id, StockOwner.id == data.owner_id
            )
        )
    ).first():
        raise HTTPException(404, "Eigentümer nicht gefunden.")
    today = datetime.now(ZoneInfo(venue.timezone)).date()
    terms = await terms_for(db, venue_id, data.supplier_id, today)
    if data.supplier_terms_id is not None and (terms is None or terms.id != data.supplier_terms_id):
        raise HTTPException(409, "Lieferbedingungen sind nicht mehr aktuell. Bitte neu laden.")
    rules = SupplierRules.model_validate(terms.rules if terms else {})
    lines = []
    for entry in data.lines:
        product = await product_for(db, venue_id, entry.product_id)
        if product.supplier_id != data.supplier_id:
            raise HTTPException(422, "Der Lieferartikel gehört zu einem anderen Lieferanten.")
        price = await price_for(db, venue_id, product.id, today)
        if price is None or price.id != entry.price_id:
            raise HTTPException(
                409, "Der Lieferantenpreis ist nicht mehr aktuell. Bitte neu laden."
            )
        item = await inventory.item_for(db, venue_id, product.item_id)
        conditions = ProductConditions.model_validate(price.conditions)
        applied_price, bonus_packs = priced_packs(entry.packs, price.pack_price_cents, conditions)
        quantity = product.pack_quantity * (entry.packs + bonus_packs)
        if quantity > 999999999:
            raise HTTPException(422, "Die Bestellmenge ist zu groß.")
        lines.append(
            PurchaseOrderLine(
                venue_id=venue_id,
                product_id=product.id,
                item_id=item.id,
                price_id=price.id,
                item_name=item.name,
                unit=item.unit,
                supplier_sku=product.supplier_sku,
                pack_name=product.pack_name,
                pack_quantity=product.pack_quantity,
                packs=entry.packs,
                ordered_quantity=quantity,
                ordered_bonus_quantity=product.pack_quantity * bonus_packs,
                conditions_snapshot=conditions.model_dump(mode="json", exclude_defaults=True),
                pack_price_cents=applied_price,
                tax_rate_bps=price.tax_rate_bps,
            )
        )
    if sum(line.packs * line.pack_price_cents for line in lines) > 1000000000:
        raise HTTPException(422, "Der Bestellwert ist zu groß.")
    count = (
        await db.execute(
            select(func.count())
            .select_from(PurchaseOrder)
            .where(PurchaseOrder.venue_id == venue_id)
        )
    ).scalar_one()
    order = PurchaseOrder(
        venue_id=venue_id,
        supplier_id=data.supplier_id,
        owner_id=data.owner_id,
        location_id=data.location_id,
        number=f"EK-{count + 1001}",
        supplier_terms_id=terms.id if terms else None,
        supplier_terms_snapshot=rules.model_dump(mode="json", exclude_defaults=True),
        earliest_delivery_on=(
            earliest_delivery(datetime.now(UTC), rules, venue.timezone) if terms else None
        ),
        request_key=data.request_key,
        request_hash=request_digest(data),
        expected_on=data.expected_on,
        currency=venue.currency,
        note=data.reason,
        actor_id=user.id,
    )
    db.add(order)
    await db.flush()
    for line in lines:
        line.order_id = order.id
        db.add(line)
    svc.event(db, venue_id, "purchasing.order_created", order.id, {"number": order.number}, user.id)
    await db.flush()
    return await order_read(db, order)


@router.post(
    PREFIX + "/orders/{order_id}/state",
    response_model=PurchaseOrderRead,
    status_code=200,
    summary="Bestellung freigeben, ohne Wareneingang stornieren oder Restlieferung schließen",
)
async def order_state(
    venue_id: uuid.UUID, order_id: uuid.UUID, data: OrderStateInput, user: Actor, db: DB
) -> PurchaseOrderRead:
    venue, _ = await svc.venue_access(db, user, venue_id, svc.MANAGERS, lock=True)
    order = await order_for(db, venue_id, order_id)
    svc.check_version(order.version, data.version)
    current = await order_read(db, order)
    if data.status == "ordered":
        if order.status != "draft":
            raise HTTPException(409, "Nur ein Entwurf kann freigegeben werden.")
        today = datetime.now(ZoneInfo(venue.timezone)).date()
        current_terms = await terms_for(db, venue_id, order.supplier_id, today)
        if (current_terms.id if current_terms else None) != order.supplier_terms_id:
            raise HTTPException(
                409, "Lieferbedingungen haben sich geändert. Einen neuen Entwurf anlegen."
            )
        if current.shortfall_to_minimum_net_cents:
            raise HTTPException(
                409,
                f"Mindestbestellwert um {current.shortfall_to_minimum_net_cents} Cent unterschritten.",
            )
        if (
            current_terms
            and order.expected_on
            and order.expected_on
            < earliest_delivery(
                datetime.now(UTC), SupplierRules.model_validate(current_terms.rules), venue.timezone
            )
        ):
            raise HTTPException(
                409, "Gewünschter Liefertermin liegt vor dem frühesten geplanten Zugang."
            )
        for line in current.lines:
            price = await price_for(db, venue_id, line.product_id, today)
            if price is None or price.id != line.price_id:
                raise HTTPException(
                    409,
                    "Ein Preis hat sich geändert. Bitte einen neuen Einkaufsentwurf mit dem geprüften Preis anlegen.",
                )
    elif data.status == "cancelled":
        if order.status not in {"draft", "ordered"} or any(
            line.received_quantity for line in current.lines
        ):
            raise HTTPException(
                409, "Eine Bestellung mit angenommener Ware kann nicht storniert werden."
            )
    elif order.status not in {"ordered", "partial"}:
        raise HTTPException(409, "Nur eine freigegebene offene Lieferung kann geschlossen werden.")
    order.status = data.status
    order.version += 1
    svc.event(
        db,
        venue_id,
        "purchasing.order_state_changed",
        order.id,
        {"status": order.status, "reason": data.reason},
        user.id,
    )
    await db.flush()
    return await order_read(db, order)


@router.post(
    PREFIX + "/orders/{order_id}/receipts",
    response_model=PurchaseOrderRead,
    status_code=201,
    summary="Teilwareneingang annehmen, Abweichungen dokumentieren und Lagerbestand buchen",
)
async def receive(
    venue_id: uuid.UUID, order_id: uuid.UUID, data: PurchaseReceiptInput, user: Actor, db: DB
) -> PurchaseOrderRead:
    venue, _ = await svc.venue_access(db, user, venue_id, svc.KITCHEN, lock=True)
    order = await order_for(db, venue_id, order_id)
    line = await line_for(db, venue_id, data.line_id)
    if line.order_id != order.id:
        raise HTTPException(404, "Bestellposition nicht gefunden.")
    previous = (
        await db.execute(
            select(PurchaseReceipt).where(
                PurchaseReceipt.venue_id == venue_id,
                PurchaseReceipt.request_key == data.request_key,
            )
        )
    ).scalar_one_or_none()
    if previous is not None:
        if previous.line_id != line.id or previous.request_hash != request_digest(data):
            raise HTTPException(
                409, "Diese Vorgangs-ID wurde bereits für eine andere Lieferung verwendet."
            )
        return await order_read(db, order)
    if order.status not in {"ordered", "partial"}:
        raise HTTPException(409, "Die Bestellung ist nicht für einen Wareneingang offen.")
    item = await inventory.item_for(db, venue_id, line.item_id)
    inventory.validate_quantity(
        item,
        data.accepted_quantity,
        data.rejected_quantity,
        data.accepted_bonus_quantity,
        data.rejected_bonus_quantity,
    )
    await inventory.location_for(db, venue_id, data.location_id)
    receipts = await receipts_for(db, venue_id, line.id)
    received = sum((row.accepted_quantity for row in receipts), Decimal(0))
    bonus_received = sum((row.accepted_bonus_quantity for row in receipts), Decimal(0))
    if data.accepted_bonus_quantity > line.ordered_bonus_quantity - bonus_received:
        raise HTTPException(409, "Die Gratisannahme überschreitet die zugesagte Gratisrestmenge.")
    if (
        data.accepted_quantity - data.accepted_bonus_quantity
        > line.ordered_quantity - line.ordered_bonus_quantity - received + bonus_received
    ):
        raise HTTPException(
            409, "Die kostenpflichtige Annahme überschreitet die offene Bestellmenge."
        )
    from app.gastro.deliveries import validate_receipt_confirmation

    await validate_receipt_confirmation(
        db,
        venue,
        line,
        data.confirmation_id,
        data.accepted_quantity
        + data.rejected_quantity
        - data.accepted_bonus_quantity
        - data.rejected_bonus_quantity,
        data.accepted_bonus_quantity + data.rejected_bonus_quantity,
        data.unconfirmed_delivery_reason,
    )
    stock_operation_id = None
    if data.accepted_quantity:
        if (
            await db.execute(
                select(StockOperation.id).where(
                    StockOperation.venue_id == venue_id,
                    StockOperation.request_key == data.request_key,
                )
            )
        ).first():
            raise HTTPException(
                409, "Diese Vorgangs-ID gehört bereits zu einer anderen Lagerbuchung."
            )
        result = await inventory.receive(
            venue_id,
            ReceiptInput(
                request_key=data.request_key,
                reason=data.reason,
                item_id=line.item_id,
                owner_id=order.owner_id,
                location_id=data.location_id,
                lot_code=data.lot_code,
                expires_on=data.expires_on,
                blocked=data.blocked,
                quantity=data.accepted_quantity,
                reference=data.reference,
            ),
            user,
            db,
        )
        stock_operation_id = result.id
    db.add(
        PurchaseReceipt(
            venue_id=venue_id,
            line_id=line.id,
            confirmation_id=data.confirmation_id,
            stock_operation_id=stock_operation_id,
            request_key=data.request_key,
            request_hash=request_digest(data),
            accepted_quantity=data.accepted_quantity,
            rejected_quantity=data.rejected_quantity,
            accepted_bonus_quantity=data.accepted_bonus_quantity,
            rejected_bonus_quantity=data.rejected_bonus_quantity,
            reference=data.reference,
            rejection_reason=data.rejection_reason,
            actor_id=user.id,
            details=data.model_dump(mode="json"),
        )
    )
    await db.flush()
    current = await order_read(db, order)
    if all(entry.remaining_quantity == 0 for entry in current.lines):
        order.status = "received"
    elif any(entry.received_quantity for entry in current.lines):
        order.status = "partial"
    order.version += 1
    svc.event(
        db,
        venue_id,
        "purchasing.goods_received",
        order.id,
        {
            "line_id": str(line.id),
            "reference": data.reference,
            "accepted_quantity": str(data.accepted_quantity),
            "rejected_quantity": str(data.rejected_quantity),
        },
        user.id,
    )
    await db.flush()
    return await order_read(db, order)


@router.post(
    PREFIX + "/invoices",
    response_model=PurchaseInvoiceRead,
    status_code=201,
    summary="Lieferantenrechnung gegen Bestellpreis und angenommenen Wareneingang prüfen",
)
async def create_invoice(
    venue_id: uuid.UUID, data: InvoiceInput, user: Actor, db: DB
) -> PurchaseInvoiceRead:
    venue, _ = await svc.venue_access(db, user, venue_id, svc.MANAGERS, lock=True)
    previous = (
        await db.execute(
            select(PurchaseInvoice).where(
                PurchaseInvoice.venue_id == venue_id,
                PurchaseInvoice.request_key == data.request_key,
            )
        )
    ).scalar_one_or_none()
    if previous is not None:
        if previous.request_hash != request_digest(data):
            raise HTTPException(409, "Diese Vorgangs-ID wurde für eine andere Rechnung verwendet.")
        return await invoice_read(db, previous)
    await supplier_for(db, venue_id, data.supplier_id)
    if (
        await db.execute(
            select(PurchaseInvoice.id).where(
                PurchaseInvoice.venue_id == venue_id,
                PurchaseInvoice.supplier_id == data.supplier_id,
                PurchaseInvoice.number == data.number,
                PurchaseInvoice.status != "rejected",
            )
        )
    ).first():
        raise HTTPException(409, "Diese Rechnungsnummer ist für den Lieferanten bereits erfasst.")
    for entry in data.lines:
        line = await line_for(db, venue_id, entry.purchase_line_id)
        order = await order_for(db, venue_id, line.order_id)
        if order.supplier_id != data.supplier_id or order.status in {"draft", "cancelled"}:
            raise HTTPException(
                422,
                "Die Rechnungsposition passt nicht zu einer freigegebenen Bestellung dieses Lieferanten.",
            )
        inventory.validate_quantity(
            await inventory.item_for(db, venue_id, line.item_id), entry.quantity
        )
    if sum(line.net_cents for line in data.lines) > 1000000000:
        raise HTTPException(422, "Der Rechnungsbetrag ist zu groß.")
    invoice = PurchaseInvoice(
        venue_id=venue_id,
        supplier_id=data.supplier_id,
        number=data.number,
        issued_on=data.issued_on,
        currency=venue.currency,
        request_key=data.request_key,
        request_hash=request_digest(data),
        actor_id=user.id,
    )
    db.add(invoice)
    await db.flush()
    for entry in data.lines:
        db.add(PurchaseInvoiceLine(venue_id=venue_id, invoice_id=invoice.id, **entry.model_dump()))
    svc.event(
        db, venue_id, "purchasing.invoice_recorded", invoice.id, {"number": invoice.number}, user.id
    )
    await db.flush()
    return await invoice_read(db, invoice)


@router.post(
    PREFIX + "/invoices/{invoice_id}/decision",
    response_model=PurchaseInvoiceRead,
    status_code=200,
    summary="Abgeglichenen Rechnungsstand freigeben oder mit Begründung zurückweisen",
)
async def decide_invoice(
    venue_id: uuid.UUID, invoice_id: uuid.UUID, data: InvoiceDecision, user: Actor, db: DB
) -> PurchaseInvoiceRead:
    await svc.venue_access(db, user, venue_id, svc.MANAGERS, lock=True)
    invoice = (
        await db.execute(
            select(PurchaseInvoice).where(
                PurchaseInvoice.venue_id == venue_id, PurchaseInvoice.id == invoice_id
            )
        )
    ).scalar_one_or_none()
    if invoice is None:
        raise HTTPException(404, "Lieferantenrechnung nicht gefunden.")
    svc.check_version(invoice.version, data.version)
    if invoice.status != "draft":
        raise HTTPException(409, "Über diese Rechnung wurde bereits entschieden.")
    check = await check_invoice(db, invoice)
    if data.status == "approved" and not check.matched:
        raise HTTPException(
            409,
            "Preis, Steuer oder angenommene Menge stimmen nicht überein. Differenzen zuerst klären.",
        )
    invoice.status = data.status
    invoice.version += 1
    invoice.decided_at = datetime.now(UTC)
    invoice.decided_by = user.id
    invoice.decision_reason = data.reason
    invoice.approval_snapshot = check.model_dump(mode="json")
    svc.event(
        db,
        venue_id,
        "purchasing.invoice_decided",
        invoice.id,
        {"status": invoice.status, "reason": data.reason},
        user.id,
    )
    await db.flush()
    return await invoice_read(db, invoice)
