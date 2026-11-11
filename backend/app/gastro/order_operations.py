"""Versioned table service and station-level preparation, independent of payment."""

from __future__ import annotations

import uuid
from typing import Literal, cast

from fastapi import APIRouter, Depends, HTTPException
from pydantic import Field, JsonValue
from sqlalchemy import ForeignKey, String, UniqueConstraint, select
from sqlalchemy.orm import Mapped, mapped_column

from app.gastro import service as svc
from app.gastro.models import GastroBase, Order
from app.gastro.router import DB, Actor, private_response
from app.gastro.schemas import LineInput, OrderInput, OrderRead, VersionInput

router = APIRouter(dependencies=[Depends(private_response)])


class OrderOperation(GastroBase):
    __tablename__ = "fp_order_operations"
    __table_args__ = (UniqueConstraint("venue_id", "request_key", name="uq_fp_order_operation"),)
    venue_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("fp_venues.id"), index=True)
    order_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("fp_orders.id"), index=True)
    request_key: Mapped[uuid.UUID] = mapped_column()
    request_hash: Mapped[str] = mapped_column(String(64))
    kind: Mapped[str] = mapped_column(String(64))


class AppendInput(VersionInput):
    request_key: uuid.UUID
    lines: list[LineInput] = Field(min_length=1, max_length=100)


class TransferInput(VersionInput):
    request_key: uuid.UUID
    table_id: uuid.UUID


class LineStateInput(VersionInput):
    request_key: uuid.UUID
    status: Literal["preparing", "ready", "served"]


async def prepare(
    db: DB, order: Order, data: AppendInput | TransferInput | LineStateInput, kind: str
) -> bool:
    prior = (
        await db.execute(
            select(OrderOperation).where(
                OrderOperation.venue_id == order.venue_id,
                OrderOperation.request_key == data.request_key,
            )
        )
    ).scalar_one_or_none()
    if prior:
        if (
            prior.order_id != order.id
            or prior.kind != kind
            or prior.request_hash != svc.digest(data)
        ):
            raise HTTPException(409, "Diese Vorgangs-ID wurde bereits anders verwendet.")
        return False
    svc.check_version(order.version, data.version)
    if kind in {"append", "transfer"}:
        from app.gastro.service_models import ServiceRoundChild, ServiceUnitAssignment

        if (
            await db.execute(
                select(ServiceRoundChild.id).where(ServiceRoundChild.order_id == order.id)
            )
        ).first() or (
            await db.execute(
                select(ServiceUnitAssignment.id)
                .where(ServiceUnitAssignment.order_id == order.id)
                .limit(1)
            )
        ).first():
            raise HTTPException(
                409,
                "Dieser Bon gehört zum Gastservice. Eine neue Runde senden oder den Gastkontext ändern.",
            )
    if order.cancellation_units and kind in {"append", "transfer"}:
        raise HTTPException(
            409,
            "Dieser Bon enthält Stornobelege. Weitere Bestellungen bitte auf einem neuen Bon erfassen.",
        )
    if order.pos_requested or order.paid_at or order.status == "cancelled":
        raise HTTPException(409, "Die Bestellung ist an der Kasse oder bereits abgeschlossen.")
    db.add(
        OrderOperation(
            venue_id=order.venue_id,
            order_id=order.id,
            request_key=data.request_key,
            request_hash=svc.digest(data),
            kind=kind,
        )
    )
    return True


@router.post(
    "/venues/{venue_id}/orders/{order_id}/append",
    response_model=OrderRead,
    status_code=200,
    summary="Weitere Positionen auf denselben Tischbon bestellen",
)
async def append_order(
    venue_id: uuid.UUID, order_id: uuid.UUID, data: AppendInput, user: Actor, db: DB
) -> Order:
    venue, _ = await svc.venue_access(db, user, venue_id, svc.SERVICE, lock=True)
    order = await svc.order_for_venue(db, venue_id, order_id, lock=True)
    if not await prepare(db, order, data, "append"):
        return order
    if order.discount_cents or order.voucher_cents:
        raise HTTPException(409, "Rabatt oder Gutschein vor einer Nachbestellung zurücknehmen.")
    if len(order.lines) + len(data.lines) > 100:
        raise HTTPException(422, "Dieser Bon hat bereits zu viele Positionen.")
    lines, total = await svc.snapshot_lines(
        db,
        venue,
        OrderInput(request_key=data.request_key, fulfillment=order.fulfillment, lines=data.lines),
    )
    if order.total_cents + total > 100000000 or len(order.lines) + len(lines) > 100:
        raise HTTPException(422, "Die Nachbestellung überschreitet die Bongrenze.")
    order.lines = [*order.lines, *lines]
    order.total_cents += total
    order.subtotal_cents += total
    order.fulfillment_status = order.status = "sent"
    order.version += 1
    svc.event(
        db,
        venue_id,
        "order.appended",
        order.id,
        {
            "lines": cast(JsonValue, lines),
            "total_cents": order.total_cents,
            "version": order.version,
        },
        user.id,
    )
    await db.flush()
    return order


@router.post(
    "/venues/{venue_id}/orders/{order_id}/transfer",
    response_model=OrderRead,
    status_code=200,
    summary="Offenen Tischbon auf einen anderen Tisch verschieben",
)
async def transfer_order(
    venue_id: uuid.UUID, order_id: uuid.UUID, data: TransferInput, user: Actor, db: DB
) -> Order:
    _, _role = await svc.venue_access(db, user, venue_id, svc.SERVICE, lock=True)
    order = await svc.order_for_venue(db, venue_id, order_id, lock=True)
    if not await prepare(db, order, data, "transfer"):
        return order
    table = await svc.table_for_venue(db, venue_id, data.table_id, lock=True)
    if order.fulfillment != "dine_in" or order.guests > table.seats:
        raise HTTPException(422, "Tisch und Gästezahl passen nicht zu dieser Bestellung.")
    previous = order.table_id
    order.table_id = table.id
    order.version += 1
    svc.event(
        db,
        venue_id,
        "order.transferred",
        order.id,
        {
            "previous_table_id": str(previous) if previous else None,
            "table_id": str(table.id),
            "version": order.version,
        },
        user.id,
    )
    await db.flush()
    return order


@router.post(
    "/venues/{venue_id}/orders/{order_id}/lines/{line_id}/status",
    response_model=OrderRead,
    status_code=200,
    summary="Eine Küchenposition mit einem Schritt weiterstellen",
)
async def line_status(
    venue_id: uuid.UUID,
    order_id: uuid.UUID,
    line_id: uuid.UUID,
    data: LineStateInput,
    user: Actor,
    db: DB,
) -> Order:
    venue, role = await svc.venue_access(db, user, venue_id, svc.KITCHEN, lock=True)
    order = await svc.order_for_venue(db, venue_id, order_id, lock=True)
    if not await prepare(db, order, data, f"line:{line_id}"):
        return order
    if role == "kitchen" and data.status == "served":
        raise HTTPException(403, "Servieren erfordert eine Servicerolle.")
    target = next((line for line in order.lines if line.get("line_id") == str(line_id)), None)
    if target is None or target.get("kind", "product") != "product":
        raise HTTPException(404, "Küchenposition nicht gefunden.")
    from app.gastro.cancellation_projection import remaining_lines, update_fulfillment

    if not any(str(line["line_id"]) == str(line_id) for line in remaining_lines(order)):
        raise HTTPException(409, "Diese Position wurde vollständig storniert.")
    current = str(target.get("preparation_status", "sent"))
    if {"sent": "preparing", "preparing": "ready", "ready": "served"}.get(current) != data.status:
        raise HTTPException(409, "Die Position hat inzwischen einen anderen Küchenstand.")
    if data.status == "preparing":
        from app.gastro.recipes import consume_order_lines

        await consume_order_lines(db, venue, order, [target], user.id)
    order.lines = [
        {**line, "preparation_status": data.status} if line.get("line_id") == str(line_id) else line
        for line in order.lines
    ]
    update_fulfillment(order)
    order.version += 1
    svc.event(
        db,
        venue_id,
        "order.line_status_changed",
        order.id,
        {
            "line_id": str(line_id),
            "status": data.status,
            "order_status": order.status,
            "version": order.version,
        },
        user.id,
    )
    await db.flush()
    return order
