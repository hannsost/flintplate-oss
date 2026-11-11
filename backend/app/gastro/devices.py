from __future__ import annotations

import hashlib
import json
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy import select

from app.gastro import cash
from app.gastro import service as svc
from app.gastro.cancellation_money_models import CancellationCheckoutAck
from app.gastro.cash_models import CashEntry
from app.gastro.cash_schemas import (
    BalanceRead,
    CheckoutCorrectionInput,
    CheckoutCorrectionRead,
    EntryRead,
    ExternalRefundInput,
)
from app.gastro.models import Device, DeviceReceipt, DiningTable, Event, Order, Venue
from app.gastro.router import DB, Actor, private_response
from app.gastro.schemas import (
    DeviceCreated,
    DeviceEventRead,
    DeviceInput,
    DeviceRead,
    MenuPublic,
    MessageRead,
    OrderInput,
    OrderRead,
    PaymentInput,
    StateInput,
    TableRead,
)

management = APIRouter(dependencies=[Depends(private_response)])
router = APIRouter(dependencies=[Depends(private_response)])


async def get_device(
    db: DB, key: Annotated[str | None, Header(alias="X-FlintPlate-Key")] = None
) -> Device:
    if key is None or len(key) > 200:
        raise HTTPException(401, "Geräteschlüssel erforderlich.")
    token_digest = hashlib.sha256(key.encode()).hexdigest()
    device = (
        await db.execute(
            select(Device).where(Device.token_digest == token_digest).with_for_update()
        )
    ).scalar_one_or_none()
    if device is None or not device.active or device.expires_at <= datetime.now(UTC):
        raise HTTPException(401, "Geräteschlüssel ungültig, abgelaufen oder widerrufen.")
    return device


DeviceAuth = Annotated[Device, Depends(get_device)]


@management.get(
    "/venues/{venue_id}/devices",
    response_model=list[DeviceRead],
    status_code=200,
    summary="Anbindungen und Geräte ohne Schlüssel auflisten",
)
async def devices(venue_id: uuid.UUID, user: Actor, db: DB) -> list[Device]:
    await svc.venue_access(db, user, venue_id, svc.MANAGERS)
    return list(
        (
            await db.execute(
                select(Device).where(Device.venue_id == venue_id).order_by(Device.created_at.desc())
            )
        ).scalars()
    )


@management.post(
    "/venues/{venue_id}/devices",
    response_model=DeviceCreated,
    status_code=201,
    summary="Gerätezugang mit einmaliger Schlüsselanzeige erstellen",
)
async def create_device(
    venue_id: uuid.UUID, data: DeviceInput, user: Actor, db: DB
) -> DeviceCreated:
    await svc.venue_access(db, user, venue_id, svc.MANAGERS)
    if "payments:write" in data.scopes and data.kind != "pos":
        raise HTTPException(422, "Zahlungsrückmeldungen sind nur für Kassenadapter erlaubt.")
    token = "fp_" + secrets.token_urlsafe(32)
    device = Device(
        venue_id=venue_id,
        name=data.name,
        kind=data.kind,
        scopes=sorted(set(data.scopes)),
        token_digest=hashlib.sha256(token.encode()).hexdigest(),
        expires_at=datetime.now(UTC) + timedelta(days=data.valid_days),
    )
    db.add(device)
    await db.flush()
    svc.event(
        db,
        venue_id,
        "device.created",
        device.id,
        {"kind": data.kind, "scopes": list(data.scopes)},
        user.id,
    )
    return DeviceCreated(device=DeviceRead.model_validate(device), token=token)


@management.delete(
    "/venues/{venue_id}/devices/{device_id}",
    response_model=MessageRead,
    status_code=200,
    summary="Gerätezugang sofort widerrufen",
)
async def revoke_device(
    venue_id: uuid.UUID, device_id: uuid.UUID, user: Actor, db: DB
) -> MessageRead:
    await svc.venue_access(db, user, venue_id, svc.MANAGERS)
    device = (
        await db.execute(
            select(Device)
            .where(Device.id == device_id, Device.venue_id == venue_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if device is None:
        raise HTTPException(404, "Gerät nicht gefunden.")
    device.active = False
    svc.event(db, venue_id, "device.revoked", device.id, {}, user.id)
    return MessageRead(message="Geräteschlüssel widerrufen.")


@router.get(
    "/catalog",
    response_model=list[MenuPublic],
    status_code=200,
    summary="Bestellkarte für autorisierte Geräte und Adapter",
)
async def device_catalog(device: DeviceAuth, db: DB) -> list[MenuPublic]:
    venue = await svc.device_venue(db, device, "menu:read")
    return await svc.catalog(db, venue.id)


@router.get(
    "/tables",
    response_model=list[TableRead],
    status_code=200,
    summary="Tische für autorisierte Geräte",
)
async def device_tables(device: DeviceAuth, db: DB) -> list[DiningTable]:
    venue = await svc.device_venue(db, device, "tables:read")
    return list(
        (
            await db.execute(
                select(DiningTable)
                .where(DiningTable.venue_id == venue.id)
                .order_by(DiningTable.name)
            )
        ).scalars()
    )


@router.post(
    "/orders",
    response_model=OrderRead,
    status_code=201,
    summary="Idempotente Bestellannahme von Handgeräten",
)
async def device_order(data: OrderInput, device: DeviceAuth, db: DB) -> Order:
    venue = await svc.device_venue(db, device, "orders:write")
    return await svc.create_order(db, venue, data, device=device)


@router.post(
    "/orders/{order_id}/status",
    response_model=OrderRead,
    status_code=200,
    summary="Küchenstatus von einem Display oder Adapter melden",
)
async def device_order_status(
    order_id: uuid.UUID, data: StateInput, device: DeviceAuth, db: DB
) -> Order:
    venue = await svc.device_venue(db, device, "kitchen:write")
    return await svc.transition_order(db, venue.id, order_id, data, "kitchen", device_id=device.id)


@router.get(
    "/events",
    response_model=list[DeviceEventRead],
    status_code=200,
    summary="Persistente Karten-, Bestell- und Kassenereignisse lesen",
)
async def device_events(
    device: DeviceAuth, db: DB, after: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=500)
) -> list[Event]:
    venue = await svc.device_venue(db, device, "events:read")
    return list(
        (
            await db.execute(
                select(Event)
                .where(
                    Event.venue_id == venue.id,
                    Event.sequence > after,
                    Event.kind.in_(
                        [
                            "menu.published",
                            "order.created",
                            "order.status_changed",
                            "order.appended",
                            "order.transferred",
                            "order.line_status_changed",
                            "pos.checkout_requested",
                            "pos.payment_confirmed",
                            "pos.payment_partially_confirmed",
                            "payment.confirmed",
                            "payment.partially_confirmed",
                            "payment.refunded",
                            "order.cancellation_requested",
                            "order.cancellation_executed",
                            "pos.cancellation_reconciled",
                        ]
                    ),
                )
                .order_by(Event.sequence)
                .limit(limit)
            )
        ).scalars()
    )


@router.get(
    "/orders/{order_id}",
    response_model=OrderRead,
    status_code=200,
    summary="Aktuellen Bon ausschließlich im Betrieb des Kassenadapters lesen",
)
async def device_order_read(order_id: uuid.UUID, device: DeviceAuth, db: DB) -> Order:
    venue = await svc.device_venue(db, device, "payments:write")
    if device.kind != "pos":
        raise HTTPException(403, "Ein Kassenadapter ist erforderlich.")
    return await svc.order_for_venue(db, venue.id, order_id)


@router.get(
    "/orders/{order_id}/balance",
    response_model=BalanceRead,
    status_code=200,
    summary="Aktuellen Restbetrag und Quellenbelege für den Kassenadapter lesen",
)
async def device_order_balance(order_id: uuid.UUID, device: DeviceAuth, db: DB) -> BalanceRead:
    from app.gastro.cancellation_money import pending_checkout

    venue = await svc.device_venue(db, device, "payments:write")
    if device.kind != "pos":
        raise HTTPException(403, "Ein Kassenadapter ist erforderlich.")
    # Keep the bill and its ledger at the same transaction point while another
    # terminal or a local till may be recording a partial tender/refund.
    order = await svc.order_for_venue(db, venue.id, order_id, lock=True)
    result = cash.balance_read(order, await cash.order_entries(db, order))
    result.checkout_blocked = await pending_checkout(db, order)
    return result


@router.post(
    "/payments",
    response_model=OrderRead,
    status_code=200,
    summary="Bereits extern erfolgte Kassenzahlung idempotent bestätigen",
)
async def confirm_payment(data: PaymentInput, device: DeviceAuth, db: DB) -> Order:
    venue = await svc.device_venue(db, device, "payments:write")
    await db.execute(select(Venue.id).where(Venue.id == venue.id).with_for_update(key_share=True))
    if device.kind != "pos":
        raise HTTPException(403, "Ein Kassenadapter ist erforderlich.")
    fingerprint = svc.digest(data)
    prior = (
        await db.execute(
            select(DeviceReceipt).where(
                DeviceReceipt.device_id == device.id, DeviceReceipt.request_key == data.request_key
            )
        )
    ).scalar_one_or_none()
    if prior:
        legacy_hash = None
        if "cancellation_version" not in data.model_fields_set:
            legacy_hash = hashlib.sha256(
                json.dumps(
                    data.model_dump(mode="json", exclude={"cancellation_version"}),
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode()
            ).hexdigest()
        if prior.request_hash not in {fingerprint, legacy_hash}:
            raise HTTPException(409, "Diese Zahlungs-ID wurde bereits mit anderen Daten verwendet.")
        return await svc.order_for_venue(db, venue.id, prior.order_id)
    order = await svc.order_for_venue(db, venue.id, data.order_id, lock=True)
    order = await cash.confirm_external_payment(db, venue, order, data, device)
    db.add(
        DeviceReceipt(
            device_id=device.id,
            request_key=data.request_key,
            request_hash=fingerprint,
            order_id=order.id,
        )
    )
    svc.event(
        db,
        venue.id,
        (
            "pos.payment_confirmed"
            if order.payment_status == "paid"
            else "pos.payment_partially_confirmed"
        ),
        order.id,
        {
            "reference": data.reference,
            "amount_cents": data.amount_cents,
            "currency": data.currency,
            "tip_cents": order.tip_cents,
        },
        device_id=device.id,
    )
    await db.flush()
    return order


@router.post(
    "/refunds",
    response_model=EntryRead,
    status_code=201,
    summary="Extern bestätigte Erstattung zur Originalzahlung protokollieren",
)
async def confirm_refund(data: ExternalRefundInput, device: DeviceAuth, db: DB) -> CashEntry:
    venue = await svc.device_venue(db, device, "payments:write")
    await db.execute(select(Venue.id).where(Venue.id == venue.id).with_for_update(key_share=True))
    return await cash.confirm_external_refund(db, venue, data, device)


@router.post(
    "/orders/{order_id}/checkout-corrections",
    response_model=CheckoutCorrectionRead,
    status_code=201,
    summary="Kassenkorrektur und fehlende offene Zahlungsaufträge ausdrücklich abgleichen",
)
async def confirm_checkout_correction(
    order_id: uuid.UUID, data: CheckoutCorrectionInput, device: DeviceAuth, db: DB
) -> CancellationCheckoutAck:
    from app.gastro.cancellation_money import acknowledge_checkout

    venue = await svc.device_venue(db, device, "payments:write")
    await db.execute(select(Venue.id).where(Venue.id == venue.id).with_for_update(key_share=True))
    return await acknowledge_checkout(db, venue, order_id, device, data)
