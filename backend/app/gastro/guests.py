from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin.models import Customer
from app.gastro import service as svc
from app.gastro.cancellation_schemas import CancelledUnitRead
from app.gastro.models import (
    DiningTable,
    GuestAccount,
    GuestProfile,
    Order,
    Reservation,
    SupportTicket,
    UsageSession,
    Venue,
)
from app.gastro.router import DB, Actor, private_response
from app.gastro.schemas import (
    GuestAccountRead,
    GuestSettings,
    LineRead,
    MenuPublic,
    OrderInput,
    PaymentRequest,
    PublicVenue,
    ReadModel,
    ReservationInput,
    ReservationRead,
    TicketInput,
    TicketRead,
)

router = APIRouter(dependencies=[Depends(private_response)])
management = APIRouter(dependencies=[Depends(private_response)])


async def public_venue(db: DB, venue_id: uuid.UUID, *, lock: bool = False) -> Venue:
    query = (
        select(Venue)
        .join(Customer, Customer.id == Venue.tenant_id)
        .where(
            Venue.id == venue_id,
            Venue.guest_enabled.is_(True),
            Customer.status.in_(["active", "trial"]),
        )
    )
    if lock:
        query = query.with_for_update(of=Venue, key_share=True)
    venue = (await db.execute(query)).scalar_one_or_none()
    if venue is None:
        raise HTTPException(404, "Kunden-App für diesen Betrieb nicht freigegeben.")
    return venue


async def account_for(db: DB, venue_id: uuid.UUID, user_id: uuid.UUID) -> GuestAccount:
    await public_venue(db, venue_id, lock=True)
    account = (
        await db.execute(
            select(GuestAccount).where(
                GuestAccount.venue_id == venue_id, GuestAccount.user_id == user_id
            )
        )
    ).scalar_one_or_none()
    if account is None:
        account = GuestAccount(venue_id=venue_id, user_id=user_id)
        db.add(account)
        await db.flush()
    return account


class GuestOrder(ReadModel):
    cancelled_units: list[CancelledUnitRead] = Field(
        default_factory=list, validation_alias="cancellation_units"
    )
    number: str
    status: str
    lines: list[LineRead]
    total_cents: int
    voucher_cents: int
    fulfillment: str
    tip_cents: int = 0
    pos_requested: bool = False
    table_id: uuid.UUID | None = None
    created_at: datetime


class GuestResource(ReadModel):
    name: str
    kind: str
    seats: int
    hourly_rate_cents: int
    billing_minutes: int


class OccupiedSlot(BaseModel):
    table_id: uuid.UUID
    starts_at: datetime
    ends_at: datetime


@management.put(
    "/venues/{venue_id}/guest-app",
    response_model=GuestSettings,
    status_code=200,
    summary="Öffentliche Kunden-App ausdrücklich freigeben oder sperren",
)
async def guest_settings(
    venue_id: uuid.UUID, data: GuestSettings, user: Actor, db: DB
) -> GuestSettings:
    venue, _ = await svc.venue_access(db, user, venue_id, svc.MANAGERS, lock=True)
    venue.guest_enabled = data.enabled
    venue.guest_table_orders = data.guest_table_orders
    venue.guest_open_tables = data.guest_open_tables
    venue.tip_mode = data.tip_mode
    venue.tip_kitchen_bps = data.tip_kitchen_bps
    svc.event(db, venue_id, "guest_app.updated", venue_id, data.model_dump(mode="json"), user.id)
    return data


@router.get(
    "/{venue_id}",
    response_model=PublicVenue,
    status_code=200,
    summary="Öffentliche Betriebsinformationen",
)
async def venue(venue_id: uuid.UUID, db: DB) -> Venue:
    return await public_venue(db, venue_id)


@router.get(
    "/{venue_id}/catalog",
    response_model=list[MenuPublic],
    status_code=200,
    summary="Veröffentlichte Kundenkarte mit Verpackung und Pfand",
)
async def catalog(venue_id: uuid.UUID, db: DB) -> list[MenuPublic]:
    await public_venue(db, venue_id)
    return await svc.catalog(db, venue_id)


@router.get(
    "/{venue_id}/resources",
    response_model=list[GuestResource],
    status_code=200,
    summary="Buchbare Tische und Aktivitäten ohne interne Grundrissdaten",
)
async def resources(venue_id: uuid.UUID, db: DB) -> list[DiningTable]:
    await public_venue(db, venue_id)
    return list(
        (
            await db.execute(
                select(DiningTable)
                .where(DiningTable.venue_id == venue_id)
                .order_by(DiningTable.name)
            )
        ).scalars()
    )


@router.get(
    "/{venue_id}/occupied",
    response_model=list[OccupiedSlot],
    status_code=200,
    summary="Belegte Zeitfenster ohne Gästedaten",
)
async def occupied(
    venue_id: uuid.UUID, start: datetime, end: datetime, db: DB
) -> list[OccupiedSlot]:
    await public_venue(db, venue_id)
    if (
        start.tzinfo is None
        or end.tzinfo is None
        or not timedelta(0) < end - start <= timedelta(days=7)
    ):
        raise HTTPException(
            422, "Zeitfenster mit Zeitzone von höchstens sieben Tagen erforderlich."
        )
    bookings = (
        await db.execute(
            select(Reservation).where(
                Reservation.venue_id == venue_id,
                Reservation.status.in_(["confirmed", "seated"]),
                Reservation.starts_at < end,
                Reservation.ends_at > start,
            )
        )
    ).scalars()
    usages = (
        await db.execute(
            select(UsageSession).where(
                UsageSession.venue_id == venue_id,
                UsageSession.ends_at.is_(None),
                UsageSession.starts_at < end,
                UsageSession.reserved_until > start,
            )
        )
    ).scalars()
    from app.gastro.booking_service import group_reads

    groups = await group_reads(db, list(bookings))
    return [
        OccupiedSlot(table_id=table_id, starts_at=row.starts_at, ends_at=row.ends_at)
        for row in groups
        for table_id in row.table_ids
    ] + [
        OccupiedSlot(table_id=row.table_id, starts_at=row.starts_at, ends_at=row.reserved_until)
        for row in usages
    ]


@router.get(
    "/{venue_id}/account",
    response_model=GuestAccountRead,
    status_code=200,
    summary="Eigenes Kundenkonto und Punktestand",
)
async def account(venue_id: uuid.UUID, user: Actor, db: DB) -> GuestAccount:
    return await account_for(db, venue_id, user.id)


@router.get(
    "/{venue_id}/orders",
    response_model=list[GuestOrder],
    status_code=200,
    summary="Nur eigene Kundenbestellungen",
)
async def orders(venue_id: uuid.UUID, user: Actor, db: DB) -> list[Order]:
    account = await account_for(db, venue_id, user.id)
    return list(
        (
            await db.execute(
                select(Order)
                .where(Order.venue_id == venue_id, Order.customer_id == account.id)
                .order_by(Order.created_at.desc())
                .limit(50)
            )
        ).scalars()
    )


async def check_channel(
    db: AsyncSession, venue: Venue, account: GuestAccount, data: OrderInput
) -> None:
    """Guests order for pickup, or to a table the venue opened for them."""
    if data.fulfillment == "takeaway":
        if data.table_id is not None:
            raise HTTPException(422, "Eine Abholbestellung hat keinen Tisch.")
        return
    if not venue.guest_table_orders:
        raise HTTPException(
            422, "Kunden bestellen hier zur Abholung. Tischbestellungen benötigen den Service."
        )
    if data.table_id is None:
        raise HTTPException(422, "Für eine Tischbestellung fehlt der Tisch.")
    await svc.table_for_venue(db, venue.id, data.table_id)
    if venue.guest_open_tables:
        return
    from app.gastro.booking_service import uses_resource

    seated = (
        await db.execute(
            select(Reservation.id).where(
                Reservation.venue_id == venue.id,
                uses_resource(data.table_id),
                Reservation.customer_id == account.id,
                Reservation.status == "seated",
            )
        )
    ).first()
    if not seated:
        raise HTTPException(
            403,
            "Dieser Tisch ist dir gerade nicht zugeordnet. Bitte kurz beim Service melden.",
        )


@router.post(
    "/{venue_id}/orders",
    response_model=GuestOrder,
    status_code=201,
    summary="Bestellung zur Abholung oder an den eigenen Tisch",
)
async def order(venue_id: uuid.UUID, data: OrderInput, user: Actor, db: DB) -> Order:
    venue = await public_venue(db, venue_id, lock=True)
    account = await account_for(db, venue_id, user.id)
    await check_channel(db, venue, account, data)
    from app.gastro.nutrition import guest_guard

    profile = (
        await db.execute(
            select(GuestProfile).where(
                GuestProfile.venue_id == venue_id, GuestProfile.account_id == account.id
            )
        )
    ).scalar_one_or_none()
    await guest_guard(
        db, venue_id, profile, [line.item_id for line in data.lines], data.accept_warnings
    )
    active = (
        await db.execute(
            select(Order.id).where(
                Order.customer_id == account.id,
                Order.status.in_(svc.ACTIVE_ORDER_STATES),
                Order.request_key != data.request_key,
            )
        )
    ).all()
    if len(active) >= 3:
        raise HTTPException(409, "Bitte zunächst deine offenen Bestellungen abholen.")
    return await svc.create_order(db, venue, data, user_id=user.id, customer_id=account.id)


@router.get(
    "/{venue_id}/reservations",
    response_model=list[ReservationRead],
    status_code=200,
    summary="Eigene Reservierungen",
)
async def reservations(venue_id: uuid.UUID, user: Actor, db: DB) -> list[Reservation]:
    account = await account_for(db, venue_id, user.id)
    return list(
        (
            await db.execute(
                select(Reservation)
                .where(Reservation.customer_id == account.id)
                .order_by(Reservation.starts_at.desc())
                .limit(50)
            )
        ).scalars()
    )


@router.post(
    "/{venue_id}/reservations",
    response_model=ReservationRead,
    status_code=201,
    summary="Tisch oder Aktivität im Kundenkonto reservieren",
)
async def reserve(venue_id: uuid.UUID, data: ReservationInput, user: Actor, db: DB) -> Reservation:
    account = await account_for(db, venue_id, user.id)
    now = datetime.now(UTC)
    if data.starts_at < now or data.starts_at > now + timedelta(days=90):
        raise HTTPException(422, "Bitte einen Termin innerhalb der nächsten 90 Tage wählen.")
    active = (
        await db.execute(
            select(Reservation.id).where(
                Reservation.customer_id == account.id,
                Reservation.status.in_(["confirmed", "seated"]),
                Reservation.ends_at > now,
            )
        )
    ).all()
    if len(active) >= 5:
        raise HTTPException(
            409, "Du hast bereits fünf aktive Reservierungen. Bitte den Betrieb kontaktieren."
        )
    table = await svc.table_for_venue(db, venue_id, data.table_id, lock=True)
    if data.guests > table.seats:
        raise HTTPException(422, "Die Kapazität reicht nicht aus.")
    await svc.check_resource_available(db, table.id, data.starts_at, data.ends_at)
    row = Reservation(venue_id=venue_id, customer_id=account.id, **data.model_dump())
    db.add(row)
    await db.flush()
    svc.event(
        db,
        venue_id,
        "reservation.created",
        row.id,
        {"table_id": str(table.id), "source": "guest_app"},
        user.id,
    )
    return row


@router.delete(
    "/{venue_id}/reservations/{reservation_id}",
    response_model=ReservationRead,
    status_code=200,
    summary="Eigene bevorstehende Reservierung stornieren",
)
async def cancel(
    venue_id: uuid.UUID, reservation_id: uuid.UUID, user: Actor, db: DB
) -> Reservation:
    account = await account_for(db, venue_id, user.id)
    row = (
        await db.execute(
            select(Reservation)
            .where(Reservation.id == reservation_id, Reservation.customer_id == account.id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, "Reservierung nicht gefunden.")
    if row.status != "confirmed" or row.starts_at <= datetime.now(UTC):
        raise HTTPException(409, "Bitte für diese Änderung den Betrieb kontaktieren.")
    row.status = "cancelled"
    row.version += 1
    svc.event(db, venue_id, "reservation.status_changed", row.id, {"status": "cancelled"}, user.id)
    return row


@management.get(
    "/venues/{venue_id}/tickets",
    response_model=list[TicketRead],
    status_code=200,
    summary="Betreuungsaufträge für Website, Hardware, Branding und Support",
)
async def tickets(venue_id: uuid.UUID, user: Actor, db: DB) -> list[SupportTicket]:
    await svc.venue_access(db, user, venue_id, svc.MANAGERS)
    return list(
        (
            await db.execute(
                select(SupportTicket)
                .where(SupportTicket.venue_id == venue_id)
                .order_by(SupportTicket.created_at.desc())
                .limit(100)
            )
        ).scalars()
    )


@management.post(
    "/venues/{venue_id}/tickets",
    response_model=TicketRead,
    status_code=201,
    summary="Betreuungsauftrag lokal erfassen",
)
async def ticket(venue_id: uuid.UUID, data: TicketInput, user: Actor, db: DB) -> SupportTicket:
    await svc.venue_access(db, user, venue_id, svc.MANAGERS)
    row = SupportTicket(venue_id=venue_id, actor_id=user.id, **data.model_dump())
    db.add(row)
    await db.flush()
    svc.event(db, venue_id, "support.created", row.id, {"category": data.category}, user.id)
    return row


@router.post(
    "/{venue_id}/orders/{order_id}/payment-request",
    response_model=GuestOrder,
    status_code=200,
    summary="Zahlung mit optionalem Trinkgeld anfordern",
)
async def request_payment(
    venue_id: uuid.UUID, order_id: uuid.UUID, data: PaymentRequest, user: Actor, db: DB
) -> Order:
    """Hands the bill to the till. FlintPlate does not charge money itself."""
    venue = await public_venue(db, venue_id, lock=True)
    account = await account_for(db, venue_id, user.id)
    order = await svc.order_for_venue(db, venue.id, order_id, lock=True)
    if order.customer_id != account.id:
        raise HTTPException(404, "Bestellung nicht gefunden.")
    if order.paid_at or order.status != "served":
        raise HTTPException(
            409, "Die Bestellung ist noch nicht servierbereit abgeschlossen oder bereits bezahlt."
        )
    if order.cancellation_units and order.tip_cents != data.tip_cents:
        raise HTTPException(
            409, "Dieser Bon enthält Stornobelege. Das ursprüngliche Trinkgeld ist gesperrt."
        )
    if order.pos_requested:
        if order.tip_cents != data.tip_cents:
            raise HTTPException(
                409, "Die Rechnung ist bereits an der Kasse. Trinkgeld ist gesperrt."
            )
        return order
    order.tip_cents = data.tip_cents
    await svc.handoff_checkout(db, order, user.id)
    return order


@router.delete(
    "/{venue_id}/orders/{order_id}",
    status_code=204,
    summary="Eigene Bestellung zurücknehmen, solange die Küche sie nicht angenommen hat",
)
async def cancel_order(venue_id: uuid.UUID, order_id: uuid.UUID, user: Actor, db: DB) -> None:
    venue = await public_venue(db, venue_id, lock=True)
    account = await account_for(db, venue_id, user.id)
    order = await svc.order_for_venue(db, venue.id, order_id, lock=True)
    if order.customer_id != account.id:
        raise HTTPException(404, "Bestellung nicht gefunden.")
    from app.gastro.cancellation import guest_cancel

    await guest_cancel(db, order, user.id)


@router.post(
    "/{venue_id}/suggestions",
    status_code=200,
    summary="Vorschläge für diesen Gast, ohne was seine Merkmale ausschließen",
)
async def suggestions(venue_id: uuid.UUID, data: dict[str, object], user: Actor, db: DB) -> object:
    from app.gastro.suggestions import SuggestInput, for_guest

    venue = await public_venue(db, venue_id)
    account = await account_for(db, venue_id, user.id)
    payload = SuggestInput.model_validate({k: v for k, v in data.items() if k != "profile_id"})
    return await for_guest(db, venue.id, account.id, payload)
