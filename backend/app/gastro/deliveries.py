"""Record supplier confirmations and reconcile receipts without inventing incoming stock."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.gastro import service as svc
from app.gastro.delivery_models import DeliveryConfirmation
from app.gastro.delivery_schemas import DeliveryInput, DeliveryRead
from app.gastro.inventory import item_for, validate_quantity
from app.gastro.models import Venue
from app.gastro.purchasing_models import PurchaseOrder, PurchaseOrderLine, PurchaseReceipt
from app.gastro.router import DB, Actor, private_response

router = APIRouter(dependencies=[Depends(private_response)])
PREFIX = "/venues/{venue_id}/purchasing/delivery-confirmations"
ZERO = Decimal(0)


async def line_source(
    db: AsyncSession, venue_id: uuid.UUID, line_id: uuid.UUID
) -> tuple[PurchaseOrderLine, PurchaseOrder]:
    row = (
        await db.execute(
            select(PurchaseOrderLine, PurchaseOrder)
            .join(PurchaseOrder, PurchaseOrder.id == PurchaseOrderLine.order_id)
            .where(PurchaseOrderLine.venue_id == venue_id, PurchaseOrderLine.id == line_id)
        )
    ).one_or_none()
    if row is None:
        raise HTTPException(404, "Einkaufsposition nicht gefunden.")
    return row[0], row[1]


async def latest(
    db: AsyncSession, venue_id: uuid.UUID, line_id: uuid.UUID
) -> DeliveryConfirmation | None:
    return (
        await db.execute(
            select(DeliveryConfirmation)
            .where(
                DeliveryConfirmation.venue_id == venue_id,
                DeliveryConfirmation.line_id == line_id,
            )
            .order_by(DeliveryConfirmation.version.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def read_confirmation(
    db: AsyncSession, venue: Venue, row: DeliveryConfirmation
) -> DeliveryRead:
    line, order = await line_source(db, venue.id, row.line_id)
    current = await latest(db, venue.id, row.line_id)
    receipts = list(
        (
            await db.execute(
                select(PurchaseReceipt).where(
                    PurchaseReceipt.venue_id == venue.id,
                    PurchaseReceipt.line_id == row.line_id,
                )
            )
        ).scalars()
    )
    return render_confirmation(venue, row, line, order, current, receipts)


def render_confirmation(
    venue: Venue,
    row: DeliveryConfirmation,
    line: PurchaseOrderLine,
    order: PurchaseOrder,
    current: DeliveryConfirmation | None,
    receipts: list[PurchaseReceipt],
) -> DeliveryRead:
    related = [receipt for receipt in receipts if receipt.confirmation_id == row.id]
    accepted = sum((r.accepted_quantity for r in receipts), ZERO)
    accepted_bonus = sum((r.accepted_bonus_quantity for r in receipts), ZERO)
    arrived_bonus = sum(
        (r.accepted_bonus_quantity + r.rejected_bonus_quantity for r in related), ZERO
    )
    arrived = sum((r.accepted_quantity + r.rejected_quantity for r in related), ZERO)
    paid = row.paid_quantity - arrived + arrived_bonus
    bonus = row.bonus_quantity - arrived_bonus
    conflicts: list[str] = []
    if current is None or current.id != row.id:
        conflicts.append("Durch eine neuere Lieferzusage ersetzt.")
    if row.status != "confirmed":
        conflicts.append("Lieferzusage wurde abgesagt.")
    if order.status not in {"ordered", "partial"} and paid + bonus > 0:
        conflicts.append("Einkaufsbestellung ist nicht mehr offen.")
    if paid < 0 or bonus < 0:
        conflicts.append("Zugeordnete Liefermengen überschreiten die Zusage.")
    if (
        paid > line.ordered_quantity - line.ordered_bonus_quantity - accepted + accepted_bonus
        or bonus > line.ordered_bonus_quantity - accepted_bonus
    ):
        conflicts.append(
            "Andere Warenannahmen haben den Einkaufsrest unter diese Zusage reduziert."
        )
    if row.expected_on < datetime.now(ZoneInfo(venue.timezone)).date() and paid + bonus > 0:
        conflicts.append("Liefertermin verstrichen; aktuelle Zusage prüfen.")
    return DeliveryRead(
        id=row.id,
        venue_id=row.venue_id,
        created_at=row.created_at,
        line_id=row.line_id,
        previous_id=row.previous_id,
        version=row.version,
        status=row.status,
        expected_on=row.expected_on,
        paid_quantity=row.paid_quantity,
        bonus_quantity=row.bonus_quantity,
        reference=row.reference,
        reason=row.reason,
        order_id=order.id,
        supplier_id=order.supplier_id,
        owner_id=order.owner_id,
        item_id=line.item_id,
        unit=line.unit,
        current=current is not None and current.id == row.id,
        remaining_paid_quantity=paid,
        remaining_bonus_quantity=bonus,
        remaining_physical_quantity=paid + bonus,
        rejected_quantity=sum((r.rejected_quantity for r in related), ZERO),
        reliable_for_planning=not conflicts and paid + bonus > 0,
        conflicts=conflicts,
    )


@router.get(
    PREFIX,
    response_model=list[DeliveryRead],
    status_code=200,
    summary="Lieferzusagen, Historie und verlässlich offene Mengen anzeigen",
)
async def confirmations(
    venue_id: uuid.UUID,
    user: Actor,
    db: DB,
    line_id: uuid.UUID | None = None,
    current_only: bool = True,
    before_version: int | None = Query(default=None, ge=1),
) -> list[DeliveryRead]:
    venue, _ = await svc.venue_access(db, user, venue_id, svc.KITCHEN)
    statement = select(DeliveryConfirmation).where(DeliveryConfirmation.venue_id == venue_id)
    if line_id is not None:
        await line_source(db, venue_id, line_id)
        statement = statement.where(DeliveryConfirmation.line_id == line_id)
    elif not current_only or before_version is not None:
        raise HTTPException(422, "Eine Historie benötigt die konkrete Einkaufsposition.")
    else:
        statement = (
            statement.join(PurchaseOrderLine, PurchaseOrderLine.id == DeliveryConfirmation.line_id)
            .join(PurchaseOrder, PurchaseOrder.id == PurchaseOrderLine.order_id)
            .where(PurchaseOrder.status.in_(["ordered", "partial"]))
        )
    if current_only:
        statement = statement.distinct(DeliveryConfirmation.line_id).order_by(
            DeliveryConfirmation.line_id, DeliveryConfirmation.version.desc()
        )
    else:
        if before_version is not None:
            statement = statement.where(DeliveryConfirmation.version < before_version)
        statement = statement.order_by(DeliveryConfirmation.version.desc()).limit(50)
    rows = list((await db.execute(statement)).scalars())
    if not rows:
        return []
    line_ids = {row.line_id for row in rows}
    sources = (
        await db.execute(
            select(PurchaseOrderLine, PurchaseOrder)
            .join(
                PurchaseOrder,
                PurchaseOrder.id == PurchaseOrderLine.order_id,
            )
            .where(PurchaseOrderLine.venue_id == venue_id, PurchaseOrderLine.id.in_(line_ids))
        )
    ).all()
    by_line = {line.id: (line, order) for line, order in sources}
    receipts = list(
        (
            await db.execute(
                select(PurchaseReceipt).where(
                    PurchaseReceipt.venue_id == venue_id,
                    PurchaseReceipt.line_id.in_(line_ids),
                )
            )
        ).scalars()
    )
    current_by_line = (
        {row.line_id: row for row in rows}
        if current_only
        else {key: await latest(db, venue_id, key) for key in line_ids}
    )
    return [
        render_confirmation(
            venue,
            row,
            *by_line[row.line_id],
            current_by_line[row.line_id],
            [receipt for receipt in receipts if receipt.line_id == row.line_id],
        )
        for row in rows
    ]


@router.post(
    PREFIX,
    response_model=DeliveryRead,
    status_code=201,
    summary="Konkrete Lieferantenzusage erfassen oder vollständig ersetzen",
)
async def confirm(venue_id: uuid.UUID, data: DeliveryInput, user: Actor, db: DB) -> DeliveryRead:
    venue, _ = await svc.venue_access(db, user, venue_id, svc.MANAGERS, lock=True)
    previous_request = (
        await db.execute(
            select(DeliveryConfirmation).where(
                DeliveryConfirmation.venue_id == venue_id,
                DeliveryConfirmation.request_key == data.request_key,
            )
        )
    ).scalar_one_or_none()
    if previous_request is not None:
        if previous_request.request_hash != svc.digest(data):
            raise HTTPException(409, "Vorgangs-ID gehört zu einer anderen Lieferzusage.")
        return await read_confirmation(db, venue, previous_request)
    line, order = await line_source(db, venue_id, data.line_id)
    current = await latest(db, venue_id, line.id)
    svc.check_version(current.version if current else 0, data.expected_version)
    if data.status == "confirmed" and order.status not in {"ordered", "partial"}:
        raise HTTPException(
            409, "Nur offene freigegebene Einkaufspositionen können eine Zusage erhalten."
        )
    if (
        data.status == "confirmed"
        and data.expected_on < datetime.now(ZoneInfo(venue.timezone)).date()
    ):
        raise HTTPException(422, "Neue Lieferzusage darf keinen vergangenen Termin haben.")
    item = await item_for(db, venue_id, line.item_id)
    validate_quantity(item, data.paid_quantity, data.bonus_quantity)
    receipts = list(
        (
            await db.execute(
                select(PurchaseReceipt).where(
                    PurchaseReceipt.venue_id == venue_id,
                    PurchaseReceipt.line_id == line.id,
                )
            )
        ).scalars()
    )
    bonus_received = sum((r.accepted_bonus_quantity for r in receipts), ZERO)
    paid_received = sum((r.accepted_quantity - r.accepted_bonus_quantity for r in receipts), ZERO)
    if (
        data.paid_quantity > line.ordered_quantity - line.ordered_bonus_quantity - paid_received
        or data.bonus_quantity > line.ordered_bonus_quantity - bonus_received
    ):
        raise HTTPException(409, "Bestätigte Restmenge überschreitet die offene Einkaufsmenge.")
    row = DeliveryConfirmation(
        venue_id=venue_id,
        line_id=line.id,
        previous_id=current.id if current else None,
        version=(current.version if current else 0) + 1,
        status=data.status,
        expected_on=data.expected_on,
        paid_quantity=data.paid_quantity,
        bonus_quantity=data.bonus_quantity,
        reference=data.reference,
        reason=data.reason,
        actor_id=user.id,
        request_key=data.request_key,
        request_hash=svc.digest(data),
    )
    db.add(row)
    await db.flush()
    svc.event(
        db,
        venue_id,
        "purchasing.delivery_confirmed",
        row.id,
        {"line_id": str(line.id), "version": row.version, "status": row.status},
        user.id,
    )
    return await read_confirmation(db, venue, row)


async def validate_receipt_confirmation(
    db: AsyncSession,
    venue: Venue,
    line: PurchaseOrderLine,
    confirmation_id: uuid.UUID | None,
    paid_quantity: Decimal,
    bonus_quantity: Decimal,
    unconfirmed_reason: str,
) -> None:
    current = await latest(db, venue.id, line.id)
    if confirmation_id is None:
        if current is not None and current.status == "confirmed":
            result = await read_confirmation(db, venue, current)
            if result.remaining_physical_quantity > 0 and len(unconfirmed_reason.strip()) < 3:
                raise HTTPException(
                    409,
                    "Lieferzusage zuordnen oder eine unbestätigte andere Lieferung ausdrücklich begründen.",
                )
        return
    if current is None or current.id != confirmation_id or current.status != "confirmed":
        raise HTTPException(
            409, "Lieferzusage gehört nicht zur aktuellen Einkaufsposition oder wurde ersetzt."
        )
    result = await read_confirmation(db, venue, current)
    # An overdue arrival remains a real receipt. Date alone must not suppress it.
    if (
        paid_quantity > result.remaining_paid_quantity
        or bonus_quantity > result.remaining_bonus_quantity
    ):
        raise HTTPException(409, "Angetroffene Menge überschreitet die offene Lieferzusage.")
