from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import and_, func, or_, select, true
from sqlalchemy.ext.asyncio import AsyncSession

from app.absences.models import Absence
from app.admin.models import Customer
from app.gastro import service as svc
from app.gastro.dependencies import DB as DB
from app.gastro.dependencies import Actor as Actor
from app.gastro.models import (
    DiningTable,
    Event,
    Membership,
    MenuItem,
    Order,
    Reservation,
    Shift,
    Venue,
)
from app.gastro.reporting import ReportingDB
from app.gastro.schemas import (
    EventRead,
    MemberInput,
    MemberRead,
    MenuInput,
    MenuPublic,
    MenuRead,
    MenuUpdate,
    OrderInput,
    OrderRead,
    Overview,
    ReservationInput,
    ReservationRead,
    ReservationState,
    ShiftInput,
    ShiftRead,
    ShiftState,
    StateInput,
    TableInput,
    TableRead,
    VenueInput,
    VenueRead,
    VersionInput,
)
from app.users.models import User
from app.worker.assignment_models import WorkerAssignment
from app.worker.models import WorkerSettings


def private_response(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"


router = APIRouter(dependencies=[Depends(private_response)])


@router.get(
    "/venues",
    response_model=list[VenueRead],
    status_code=200,
    summary="Eigene FlintPlate-Betriebsstätten",
)
async def venues(user: Actor, db: DB) -> list[VenueRead]:
    rows = (
        await db.execute(
            select(Venue, Membership.role)
            .join(Membership, Membership.venue_id == Venue.id)
            .join(Customer, Customer.id == Venue.tenant_id)
            .where(
                Venue.tenant_id == user.tenant_id,
                Membership.user_id == user.id,
                Membership.active.is_(True),
                Customer.status.in_(["active", "trial"]),
            )
            .order_by(Venue.name)
        )
    ).all()
    return [
        VenueRead(
            id=v.id,
            name=v.name,
            timezone=v.timezone,
            currency=v.currency,
            guest_enabled=v.guest_enabled,
            role=role,
        )
        for v, role in rows
    ]


@router.post(
    "/venues",
    response_model=VenueRead,
    status_code=201,
    summary="Betriebsstätte im FlintPlate-Mandanten anlegen",
)
async def create_venue(data: VenueInput, user: Actor, db: DB) -> VenueRead:
    if user.role not in {"admin", "recruiter"} or user.tenant_id is None:
        raise HTTPException(403, "Eine Firmenadministration oder HR-Rolle ist erforderlich.")
    customer = (
        await db.execute(
            select(Customer).where(
                Customer.id == user.tenant_id, Customer.status.in_(["active", "trial"])
            )
        )
    ).scalar_one_or_none()
    if customer is None:
        raise HTTPException(403, "Der Firmenarbeitsbereich ist nicht aktiv.")
    venue = Venue(tenant_id=user.tenant_id, **data.model_dump())
    db.add(venue)
    await db.flush()
    from app.gastro.station_service import ensure_defaults

    await ensure_defaults(db, venue.id)
    db.add(Membership(venue_id=venue.id, user_id=user.id, role="manager"))
    svc.event(db, venue.id, "venue.created", venue.id, {"name": venue.name}, user.id)
    return VenueRead(id=venue.id, **data.model_dump(), role="manager")


@router.get(
    "/venues/{venue_id}/members",
    response_model=list[MemberRead],
    status_code=200,
    summary="Team dieser Betriebsstätte",
)
async def members(venue_id: uuid.UUID, user: Actor, db: DB) -> list[MemberRead]:
    await svc.venue_access(db, user, venue_id)
    rows = (
        await db.execute(
            select(Membership, User.full_name)
            .join(User, User.id == Membership.user_id)
            .where(Membership.venue_id == venue_id, User.tenant_id == user.tenant_id)
            .order_by(User.full_name)
        )
    ).all()
    return [
        MemberRead(
            id=m.id,
            user_id=m.user_id,
            full_name=name or "Teammitglied",
            role=m.role,
            active=m.active,
        )
        for m, name in rows
    ]


@router.put(
    "/venues/{venue_id}/members",
    response_model=MemberRead,
    status_code=200,
    summary="FlintPlate-Person für die Betriebsstätte berechtigen",
)
async def set_member(venue_id: uuid.UUID, data: MemberInput, user: Actor, db: DB) -> MemberRead:
    await svc.venue_access(db, user, venue_id, svc.MANAGERS, lock=True)
    person = (
        await db.execute(
            select(User).where(
                User.id == data.user_id,
                User.tenant_id == user.tenant_id,
                User.is_active.is_(True),
                User.role.in_(["worker", "recruiter", "admin"]),
            )
        )
    ).scalar_one_or_none()
    if person is None:
        raise HTTPException(404, "Person nicht im PalmScout-Arbeitsbereich gefunden.")
    member = (
        await db.execute(
            select(Membership).where(
                Membership.venue_id == venue_id, Membership.user_id == person.id
            )
        )
    ).scalar_one_or_none()
    if (
        member
        and member.role == "manager"
        and member.active
        and (not data.active or data.role != "manager")
    ):
        managers = (
            await db.execute(
                select(func.count())
                .select_from(Membership)
                .where(
                    Membership.venue_id == venue_id,
                    Membership.role == "manager",
                    Membership.active.is_(True),
                )
            )
        ).scalar_one()
        if managers <= 1:
            raise HTTPException(
                409, "Die letzte aktive Betriebsleitung kann nicht entfernt werden."
            )
    if member is None:
        member = Membership(venue_id=venue_id, user_id=person.id)
        db.add(member)
    member.role = data.role
    member.active = data.active
    await db.flush()
    svc.event(
        db,
        venue_id,
        "member.updated",
        member.id,
        {"user_id": str(person.id), "role": member.role, "active": member.active},
        user.id,
    )
    return MemberRead(
        id=member.id,
        user_id=person.id,
        full_name=person.full_name or "Teammitglied",
        role=data.role,
        active=member.active,
    )


@router.get(
    "/venues/{venue_id}/tables",
    response_model=list[TableRead],
    status_code=200,
    summary="Tischplan laden",
)
async def tables(venue_id: uuid.UUID, user: Actor, db: DB) -> list[DiningTable]:
    await svc.venue_access(db, user, venue_id)
    return list(
        (
            await db.execute(
                select(DiningTable)
                .where(DiningTable.venue_id == venue_id)
                .order_by(DiningTable.area, DiningTable.name)
            )
        ).scalars()
    )


@router.post(
    "/venues/{venue_id}/tables", response_model=TableRead, status_code=201, summary="Tisch anlegen"
)
async def create_table(venue_id: uuid.UUID, data: TableInput, user: Actor, db: DB) -> DiningTable:
    await svc.venue_access(db, user, venue_id, svc.MANAGERS, lock=True)
    exists = (
        await db.execute(
            select(DiningTable.id).where(
                DiningTable.venue_id == venue_id, DiningTable.name == data.name
            )
        )
    ).first()
    if exists:
        raise HTTPException(409, "Dieser Tischname ist bereits vergeben.")
    from app.gastro.models import Room

    if (
        data.room_id
        and not (
            await db.execute(
                select(Room.id).where(Room.id == data.room_id, Room.venue_id == venue_id)
            )
        ).first()
    ):
        raise HTTPException(404, "Raum nicht in diesem Betrieb gefunden.")
    await svc.validate_combinable(db, venue_id, data.combinable_with)
    table = DiningTable(venue_id=venue_id, **data.model_dump())
    db.add(table)
    await db.flush()
    svc.event(db, venue_id, "table.created", table.id, data.model_dump(mode="json"), user.id)
    return table


@router.get(
    "/venues/{venue_id}/menu",
    response_model=list[MenuRead],
    status_code=200,
    summary="Kartenentwürfe und veröffentlichte Stände",
)
async def menu(venue_id: uuid.UUID, user: Actor, db: DB) -> list[MenuItem]:
    await svc.venue_access(db, user, venue_id, svc.MANAGERS)
    return list(
        (
            await db.execute(
                select(MenuItem).where(MenuItem.venue_id == venue_id).order_by(MenuItem.sku)
            )
        ).scalars()
    )


@router.get(
    "/venues/{venue_id}/catalog",
    response_model=list[MenuPublic],
    status_code=200,
    summary="Veröffentlichte Bestellkarte ohne interne Kosten",
)
async def catalog(venue_id: uuid.UUID, user: Actor, db: DB) -> list[MenuPublic]:
    await svc.venue_access(db, user, venue_id)
    return await svc.catalog(db, venue_id)


@router.post(
    "/venues/{venue_id}/menu",
    response_model=MenuRead,
    status_code=201,
    summary="Artikelentwurf anlegen",
)
async def create_item(venue_id: uuid.UUID, data: MenuInput, user: Actor, db: DB) -> MenuItem:
    await svc.venue_access(db, user, venue_id, svc.MANAGERS, lock=True)
    exists = (
        await db.execute(
            select(MenuItem.id).where(MenuItem.venue_id == venue_id, MenuItem.sku == data.sku)
        )
    ).first()
    if exists:
        raise HTTPException(409, "Diese Artikelnummer existiert bereits.")
    from app.gastro.station_service import menu_payload

    payload = await menu_payload(db, venue_id, data.data)
    item = MenuItem(venue_id=venue_id, sku=data.sku, draft=payload.model_dump(mode="json"))
    db.add(item)
    await db.flush()
    svc.event(
        db, venue_id, "menu.created", item.id, {"sku": item.sku, "version": item.version}, user.id
    )
    return item


@router.put(
    "/venues/{venue_id}/menu/{item_id}",
    response_model=MenuRead,
    status_code=200,
    summary="Artikelentwurf mit Versionsprüfung ändern",
)
async def update_item(
    venue_id: uuid.UUID, item_id: uuid.UUID, data: MenuUpdate, user: Actor, db: DB
) -> MenuItem:
    await svc.venue_access(db, user, venue_id, svc.MANAGERS, lock=True)
    item = await svc.menu_for_venue(db, venue_id, item_id, lock=True)
    svc.check_version(item.version, data.version)
    from app.gastro.recipes import validate_menu_recipe

    await validate_menu_recipe(db, item, data.data)
    from app.gastro.station_service import menu_payload

    payload = await menu_payload(db, venue_id, data.data)
    item.draft = payload.model_dump(mode="json")
    item.version += 1
    svc.event(db, venue_id, "menu.draft_saved", item.id, {"version": item.version}, user.id)
    await db.flush()
    return item


@router.post(
    "/venues/{venue_id}/menu/{item_id}/publish",
    response_model=MenuRead,
    status_code=200,
    summary="Artikel für neue Bestellungen veröffentlichen",
)
async def publish_item(
    venue_id: uuid.UUID, item_id: uuid.UUID, data: VersionInput, user: Actor, db: DB
) -> MenuItem:
    await svc.venue_access(db, user, venue_id, svc.MANAGERS, lock=True)
    item = await svc.menu_for_venue(db, venue_id, item_id, lock=True)
    svc.check_version(item.version, data.version)
    if item.published_version != item.version:
        from app.gastro.schemas import MenuPayload
        from app.gastro.station_service import menu_payload

        payload = await menu_payload(db, venue_id, MenuPayload.model_validate(item.draft))
        item.published = payload.model_dump(mode="json")
        item.published_version = item.version
        public_data = {
            k: v for k, v in item.published.items() if k not in {"cost_cents", "station_snapshot"}
        }
        svc.event(
            db,
            venue_id,
            "menu.published",
            item.id,
            {"id": str(item.id), "sku": item.sku, "version": item.version, "data": public_data},
            user.id,
        )
    await db.flush()
    return item


@router.get(
    "/venues/{venue_id}/orders",
    response_model=list[OrderRead],
    status_code=200,
    summary="Bestellungen und Küchenbons laden",
)
async def orders(
    venue_id: uuid.UUID,
    user: Actor,
    db: DB,
    include_closed: bool = False,
    limit: int = Query(100, ge=1, le=500),
    before: uuid.UUID | None = None,
) -> list[Order]:
    await svc.venue_access(db, user, venue_id)
    query = select(Order).where(Order.venue_id == venue_id)
    if not include_closed:
        query = query.where(Order.status.in_(svc.ACTIVE_ORDER_STATES))
    if before is not None:
        anchor = await svc.order_for_venue(db, venue_id, before)
        query = query.where(
            or_(
                Order.created_at < anchor.created_at,
                and_(Order.created_at == anchor.created_at, Order.id < anchor.id),
            )
        )
    return list(
        (
            await db.execute(query.order_by(Order.created_at.desc(), Order.id.desc()).limit(limit))
        ).scalars()
    )


@router.post(
    "/venues/{venue_id}/orders",
    response_model=OrderRead,
    status_code=201,
    summary="Bestellung mit Preissnapshot und Idempotenz aufnehmen",
)
async def create_order(venue_id: uuid.UUID, data: OrderInput, user: Actor, db: DB) -> Order:
    venue, _ = await svc.venue_access(db, user, venue_id, svc.SERVICE)
    return await svc.create_order(db, venue, data, user_id=user.id)


@router.post(
    "/venues/{venue_id}/orders/{order_id}/status",
    response_model=OrderRead,
    status_code=200,
    summary="Küchen- oder Servicestatus ändern",
)
async def order_status(
    venue_id: uuid.UUID, order_id: uuid.UUID, data: StateInput, user: Actor, db: DB
) -> Order:
    _, role = await svc.venue_access(db, user, venue_id, svc.KITCHEN)
    return await svc.transition_order(db, venue_id, order_id, data, role, user_id=user.id)


@router.post(
    "/venues/{venue_id}/orders/{order_id}/checkout",
    response_model=OrderRead,
    status_code=200,
    summary="Bestellung an angebundene Kasse übergeben",
)
async def checkout(
    venue_id: uuid.UUID, order_id: uuid.UUID, data: VersionInput, user: Actor, db: DB
) -> Order:
    await svc.venue_access(db, user, venue_id, svc.SERVICE)
    return await svc.request_pos(db, venue_id, order_id, data.version, user.id)


@router.get(
    "/venues/{venue_id}/reservations",
    response_model=list[ReservationRead],
    status_code=200,
    summary="Reservierungen eines Zeitraums",
)
async def reservations(
    venue_id: uuid.UUID,
    user: Actor,
    db: DB,
    start: datetime | None = None,
    end: datetime | None = None,
) -> list[Reservation]:
    await svc.venue_access(db, user, venue_id, svc.SERVICE)
    lower = start or datetime.now(UTC) - timedelta(days=1)
    upper = end or lower + timedelta(days=32)
    if (
        lower.tzinfo is None
        or upper.tzinfo is None
        or not timedelta(0) < upper - lower <= timedelta(days=93)
    ):
        raise HTTPException(
            422, "Ein Zeitraum mit Zeitzone von höchstens 93 Tagen ist erforderlich."
        )
    return list(
        (
            await db.execute(
                select(Reservation)
                .where(
                    Reservation.venue_id == venue_id,
                    Reservation.starts_at < upper,
                    Reservation.ends_at > lower,
                )
                .order_by(Reservation.starts_at)
            )
        ).scalars()
    )


@router.post(
    "/venues/{venue_id}/reservations",
    response_model=ReservationRead,
    status_code=201,
    summary="Reservierung ohne Doppelbelegung anlegen",
)
async def create_reservation(
    venue_id: uuid.UUID, data: ReservationInput, user: Actor, db: DB
) -> Reservation:
    await svc.venue_access(db, user, venue_id, svc.SERVICE)
    table = await svc.table_for_venue(db, venue_id, data.table_id, lock=True)
    if data.guests > table.seats:
        raise HTTPException(422, "Der Tisch bietet nicht genug Sitzplätze.")
    await svc.check_resource_available(db, table.id, data.starts_at, data.ends_at)
    reservation = Reservation(venue_id=venue_id, **data.model_dump())
    db.add(reservation)
    await db.flush()
    svc.event(
        db,
        venue_id,
        "reservation.created",
        reservation.id,
        {"table_id": str(table.id), "guests": data.guests},
        user.id,
    )
    return reservation


@router.post(
    "/venues/{venue_id}/reservations/{reservation_id}/status",
    response_model=ReservationRead,
    status_code=200,
    summary="Reservierung einchecken oder abschließen",
)
async def reservation_status(
    venue_id: uuid.UUID, reservation_id: uuid.UUID, data: ReservationState, user: Actor, db: DB
) -> Reservation:
    await svc.venue_access(db, user, venue_id, svc.SERVICE)
    from app.gastro.booking_service import transition

    return await transition(db, venue_id, reservation_id, data.version, data.status, user.id)


@router.get(
    "/venues/{venue_id}/shifts",
    response_model=list[ShiftRead],
    status_code=200,
    summary="Gastro-Dienstplan aus der FlintPlate-Personalbasis",
)
async def shifts(
    venue_id: uuid.UUID,
    user: Actor,
    db: DB,
    start: datetime | None = None,
    end: datetime | None = None,
) -> list[ShiftRead]:
    _, role = await svc.venue_access(db, user, venue_id)
    lower = start or datetime.now(UTC) - timedelta(days=1)
    upper = end or lower + timedelta(days=32)
    if (
        lower.tzinfo is None
        or upper.tzinfo is None
        or not timedelta(0) < upper - lower <= timedelta(days=93)
    ):
        raise HTTPException(
            422, "Ein Zeitraum mit Zeitzone von höchstens 93 Tagen ist erforderlich."
        )
    query = select(Shift).where(
        Shift.venue_id == venue_id, Shift.starts_at < upper, Shift.ends_at > lower
    )
    if role != "manager":
        query = query.where(Shift.status == "published")
    from app.gastro.station_service import read_shifts

    rows = list((await db.execute(query.order_by(Shift.starts_at))).scalars())
    return await read_shifts(db, venue_id, rows)


async def check_shift_person(
    db: AsyncSession, venue: Venue, data: ShiftInput, exclude_id: uuid.UUID | None = None
) -> User:
    # Serialize all new shifts for a person, including across venues.
    person = (
        await db.execute(
            select(User)
            .join(Membership, Membership.user_id == User.id)
            .join(WorkerSettings, WorkerSettings.user_id == User.id)
            .where(
                User.id == data.worker_id,
                User.tenant_id == venue.tenant_id,
                User.role == "worker",
                User.is_active.is_(True),
                Membership.venue_id == venue.id,
                Membership.active.is_(True),
                WorkerSettings.tenant_id == venue.tenant_id,
                WorkerSettings.is_active.is_(True),
            )
            .with_for_update(of=User, key_share=True)
        )
    ).scalar_one_or_none()
    if person is None:
        raise HTTPException(404, "Aktive PalmScout-Mitarbeitende mit Betriebszugang erforderlich.")
    existing = (
        await db.execute(
            select(Shift.id).where(
                Shift.worker_id == person.id,
                Shift.id != exclude_id if exclude_id else true(),
                Shift.status != "cancelled",
                Shift.starts_at < data.ends_at,
                Shift.ends_at > data.starts_at,
            )
        )
    ).first()
    if existing:
        raise HTTPException(409, "Diese Person hat bereits eine überlappende Schicht.")
    zone = ZoneInfo(venue.timezone)
    start = data.starts_at.astimezone(zone)
    end = data.ends_at.astimezone(zone)
    absence = (
        await db.execute(
            select(Absence.id).where(
                Absence.worker_id == person.id,
                Absence.tenant_id == venue.tenant_id,
                Absence.status == "approved",
                Absence.start_date <= (end - timedelta(microseconds=1)).date(),
                Absence.end_date >= start.date(),
            )
        )
    ).first()
    if absence:
        raise HTTPException(409, "Eine genehmigte Abwesenheit überschneidet sich mit der Schicht.")
    # Respect existing PalmScout assignments, without counting our own bridge twice.
    legacy = (
        (
            await db.execute(
                select(WorkerAssignment)
                .outerjoin(Shift, Shift.assignment_id == WorkerAssignment.id)
                .where(
                    WorkerAssignment.worker_id == person.id,
                    WorkerAssignment.tenant_id == venue.tenant_id,
                    WorkerAssignment.status != "cancelled",
                    WorkerAssignment.start_date <= end.date(),
                    WorkerAssignment.end_date >= start.date(),
                    Shift.id.is_(None),
                )
            )
        )
        .scalars()
        .all()
    )
    for assignment in legacy:
        if assignment.shift_start is None or assignment.shift_end is None:
            raise HTTPException(
                409, "Eine PalmScout-Einsatzplanung belegt diesen Zeitraum bereits."
            )
        day = max(assignment.start_date, start.date() - timedelta(days=1))
        while day <= min(assignment.end_date, end.date()):
            a = datetime.combine(day, assignment.shift_start, zone)
            b = datetime.combine(day, assignment.shift_end, zone)
            if b <= a:
                b += timedelta(days=1)
            if a < end and b > start:
                raise HTTPException(
                    409, "Eine PalmScout-Einsatzplanung überschneidet sich mit der Schicht."
                )
            day += timedelta(days=1)
    from app.gastro.planning import assess_worker

    assessment = await assess_worker(db, venue, data, exclude_id)
    if assessment.blockers:
        raise HTTPException(422, " ".join(assessment.blockers))
    return person


@router.post(
    "/venues/{venue_id}/shifts",
    response_model=ShiftRead,
    status_code=201,
    summary="Schicht und FlintPlate-Einsatz zusammen anlegen",
)
async def create_shift(venue_id: uuid.UUID, data: ShiftInput, user: Actor, db: DB) -> ShiftRead:
    venue, _ = await svc.venue_access(db, user, venue_id, svc.MANAGERS, lock=True)
    from app.gastro.station_service import shift_station

    station = await shift_station(db, venue_id, data.station)
    data = data.model_copy(update={"station": station.code})
    await check_shift_person(db, venue, data)
    zone = ZoneInfo(venue.timezone)
    start, end = data.starts_at.astimezone(zone), data.ends_at.astimezone(zone)
    assignment = WorkerAssignment(
        worker_id=data.worker_id,
        tenant_id=venue.tenant_id,
        created_by=user.id,
        start_date=start.date(),
        end_date=start.date(),
        shift_start=start.time(),
        shift_end=end.time(),
        customer_company=venue.name,
        location=venue.name,
        role_description=station.name,
        notes="FlintPlate-Dienstplan",
        status="planned",
    )
    db.add(assignment)
    await db.flush()
    shift = Shift(venue_id=venue.id, assignment_id=assignment.id, **data.model_dump())
    db.add(shift)
    await db.flush()
    svc.event(
        db, venue_id, "shift.created", shift.id, {"assignment_id": str(assignment.id)}, user.id
    )
    from app.gastro.station_service import read_shifts

    return (await read_shifts(db, venue_id, [shift]))[0]


@router.post(
    "/venues/{venue_id}/shifts/{shift_id}/status",
    response_model=ShiftRead,
    status_code=200,
    summary="Schicht veröffentlichen oder absagen",
)
async def shift_status(
    venue_id: uuid.UUID, shift_id: uuid.UUID, data: ShiftState, user: Actor, db: DB
) -> ShiftRead:
    venue, _ = await svc.venue_access(db, user, venue_id, svc.MANAGERS, lock=True)
    row = (
        await db.execute(
            select(Shift).where(Shift.id == shift_id, Shift.venue_id == venue_id).with_for_update()
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, "Schicht nicht gefunden.")
    svc.check_version(row.version, data.version)
    if row.status == "cancelled" or (data.status == "published" and row.status != "draft"):
        raise HTTPException(409, "Diese Schicht kann so nicht geändert werden.")
    if data.status == "published":
        from app.gastro.station_service import validate_shift_publication

        await validate_shift_publication(db, venue_id, row.station)
        await check_shift_person(
            db, venue, ShiftInput.model_validate(row, from_attributes=True), exclude_id=row.id
        )
    assignment = (
        await db.execute(
            select(WorkerAssignment)
            .where(
                WorkerAssignment.id == row.assignment_id,
                WorkerAssignment.tenant_id == user.tenant_id,
            )
            .with_for_update()
        )
    ).scalar_one()
    row.status = data.status
    row.version += 1
    assignment.status = "confirmed" if data.status == "published" else "cancelled"
    svc.event(db, venue_id, "shift.status_changed", row.id, {"status": row.status}, user.id)
    await db.flush()
    from app.gastro.station_service import read_shifts

    return (await read_shifts(db, venue_id, [row]))[0]


@router.get(
    "/venues/{venue_id}/overview",
    response_model=Overview,
    status_code=200,
    summary="Betriebsübersicht und nachvollziehbare Hinweise",
)
async def overview(venue_id: uuid.UUID, db: ReportingDB, user: Actor) -> Overview:
    from app.gastro.cash import units_for
    from app.gastro.cash_models import CashEntry

    venue, _ = await svc.venue_access(db, user, venue_id)
    now = datetime.now(ZoneInfo(venue.timezone))
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=1)
    rows = list(
        (
            await db.execute(
                select(Order).where(
                    Order.venue_id == venue_id,
                    (Order.created_at >= start) | Order.status.in_(svc.ACTIVE_ORDER_STATES),
                )
            )
        ).scalars()
    )
    active = [r for r in rows if r.status in svc.ACTIVE_ORDER_STATES]
    reservations_count = (
        await db.execute(
            select(func.count())
            .select_from(Reservation)
            .where(
                Reservation.venue_id == venue_id,
                Reservation.starts_at >= start,
                Reservation.starts_at < end,
                Reservation.status.in_(["confirmed", "seated"]),
            )
        )
    ).scalar_one()
    staff_count = (
        await db.execute(
            select(func.count(func.distinct(Shift.worker_id))).where(
                Shift.venue_id == venue_id,
                Shift.starts_at < end,
                Shift.ends_at > start,
                Shift.status == "published",
            )
        )
    ).scalar_one()
    catalog_items = await svc.catalog(db, venue_id)
    hints = []
    waiting = [
        r
        for r in active
        if r.status == "sent" and datetime.now(UTC) - r.created_at > timedelta(minutes=15)
    ]
    if waiting:
        hints.append(
            f"{len(waiting)} Bestellungen warten seit mehr als 15 Minuten auf Zubereitung."
        )
    unavailable = sum(not item.available for item in catalog_items)
    if unavailable:
        hints.append(f"{unavailable} Artikel sind auf der Bestellkarte derzeit nicht verfügbar.")
    if reservations_count and not staff_count:
        hints.append(
            "Für heute liegen Reservierungen vor, aber noch keine veröffentlichten Schichten."
        )
    if not hints:
        hints.append("Aktuell keine Auffälligkeiten in Bestellungen, Karte und Dienstplan erkannt.")
    day_entries = list(
        (
            await db.execute(
                select(CashEntry).where(
                    CashEntry.venue_id == venue_id,
                    CashEntry.created_at >= start,
                    CashEntry.created_at < end,
                    CashEntry.kind.in_(["sale", "refund"]),
                )
            )
        ).scalars()
    )
    # Payment dates and actual ledger entries remain authoritative even when a
    # corrected receipt is covered by a waiver without a new payment timestamp.
    settled = sum(
        (1 if entry.kind == "sale" else -1)
        * sum(
            int(str(allocation["amount_cents"]))
            for allocation in entry.allocations
            if allocation.get("kind") != "tip"
        )
        for entry in day_entries
    )
    legacy_settled = (
        await db.execute(
            select(func.coalesce(func.sum(Order.total_cents), 0)).where(
                Order.venue_id == venue_id,
                Order.paid_at >= start,
                Order.paid_at < end,
                ~select(CashEntry.id)
                .where(CashEntry.order_id == Order.id, CashEntry.kind == "sale")
                .exists(),
            )
        )
    ).scalar_one()
    active_entries = list(
        (
            await db.execute(
                select(CashEntry).where(
                    CashEntry.venue_id == venue_id,
                    CashEntry.order_id.in_([order.id for order in active]),
                )
            )
        ).scalars()
    )
    entries_by_order: dict[uuid.UUID, list[CashEntry]] = {}
    for entry in active_entries:
        if entry.order_id is not None:
            entries_by_order.setdefault(entry.order_id, []).append(entry)
    return Overview(
        active_orders=len(active),
        open_total_cents=sum(
            unit.remaining
            for order in active
            for unit in units_for(order, entries_by_order.get(order.id, []))
        ),
        settled_total_cents=settled + int(legacy_settled),
        reserved_today=reservations_count,
        staff_today=staff_count,
        available_items=sum(item.available for item in catalog_items),
        hints=hints,
    )


@router.get(
    "/venues/{venue_id}/events",
    response_model=list[EventRead],
    status_code=200,
    summary="Betriebsjournal mit fortlaufenden Ereignissen",
)
async def events(
    venue_id: uuid.UUID,
    user: Actor,
    db: DB,
    after: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
) -> list[Event]:
    await svc.venue_access(db, user, venue_id, svc.MANAGERS)
    return list(
        (
            await db.execute(
                select(Event)
                .where(Event.venue_id == venue_id, Event.sequence > after)
                .order_by(Event.sequence)
                .limit(limit)
            )
        ).scalars()
    )
