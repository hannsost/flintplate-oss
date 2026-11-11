"""Staff visit contexts, audited assignments and atomic independent guest receipts."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Literal, cast

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, JsonValue
from sqlalchemy import func, inspect, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstanceState, class_mapper

from app.gastro import service as svc
from app.gastro.dependencies import DB, Actor
from app.gastro.models import DiningTable, Order, Reservation, Venue
from app.gastro.reporting import ReportingDB
from app.gastro.router import private_response
from app.gastro.schemas import LineInput, OrderInput, OrderRead
from app.gastro.service_models import (
    GuestTab,
    ServiceCommand,
    ServiceRound,
    ServiceRoundChild,
    ServiceSettings,
    ServiceUnitAssignment,
    ServiceVisit,
)
from app.gastro.service_schemas import (
    AssignedUnitRead,
    AssignmentCommit,
    AssignmentInput,
    AssignmentPreview,
    AssignmentResult,
    CommandRead,
    HistoryPage,
    OrderServiceContextRead,
    RoundChildRead,
    RoundInput,
    RoundPage,
    RoundRead,
    SettingsInput,
    SettingsRead,
    TabContext,
    TabCreate,
    TablePresenceRead,
    TabRead,
    TabSpec,
    VisitCreate,
    VisitEnd,
    VisitPage,
    VisitRead,
)
from app.users.models import User

router = APIRouter(dependencies=[Depends(private_response)])
StateRow = ServiceVisit | GuestTab | ServiceSettings


async def state(db: AsyncSession, row: StateRow) -> dict[str, JsonValue]:
    columns = class_mapper(type(row)).column_attrs
    instance = cast(InstanceState[StateRow], inspect(row))
    unloaded = [column.key for column in columns if column.key in instance.unloaded]
    if unloaded:
        # SQL expressions such as updated_at=now() expire after UPDATE. Load them
        # explicitly in the async context rather than hiding IO inside getattr.
        await db.refresh(row, attribute_names=unloaded)
    return cast(
        dict[str, JsonValue],
        json.loads(
            json.dumps(
                {column.key: getattr(row, column.key) for column in columns},
                default=str,
            )
        ),
    )


async def snapshot(
    db: AsyncSession, row: StateRow, before: dict[str, JsonValue] | None = None
) -> dict[str, JsonValue]:
    return {"entity": row.__tablename__, "state": await state(db, row), "before": before}


def fingerprint(kind: str, target: uuid.UUID, data: BaseModel) -> str:
    return hashlib.sha256(
        json.dumps(
            [kind, str(target), data.model_dump(mode="json")], sort_keys=True, separators=(",", ":")
        ).encode()
    ).hexdigest()


async def replay(
    db: AsyncSession,
    venue_id: uuid.UUID,
    user: User,
    kind: str,
    target: uuid.UUID,
    data: BaseModel,
    key: uuid.UUID,
) -> ServiceCommand | None:
    prior = (
        await db.execute(
            select(ServiceCommand).where(
                ServiceCommand.venue_id == venue_id, ServiceCommand.request_key == key
            )
        )
    ).scalar_one_or_none()
    if prior and (
        prior.actor_id != user.id or prior.request_hash != fingerprint(kind, target, data)
    ):
        raise HTTPException(409, "Diese Vorgangs-ID wurde bereits anders verwendet.")
    return prior


async def record(
    db: AsyncSession,
    venue_id: uuid.UUID,
    actor: User,
    kind: str,
    target: uuid.UUID,
    data: BaseModel,
    key: uuid.UUID,
    command_id: uuid.UUID,
    result: BaseModel,
    snapshots: list[dict[str, JsonValue]],
    reason: str = "",
) -> None:
    command = ServiceCommand(
        id=command_id,
        venue_id=venue_id,
        request_key=key,
        request_hash=fingerprint(kind, target, data),
        actor_id=actor.id,
        kind=kind,
        target_id=target,
        reason=reason,
        snapshots=snapshots,
        result=result.model_dump(mode="json"),
    )
    db.add(command)
    svc.event(
        db,
        venue_id,
        "service." + kind,
        target,
        {"command_id": str(command_id), "reason": reason, "snapshots": cast(JsonValue, snapshots)},
        actor.id,
    )
    await db.flush()


async def visit_for(
    db: AsyncSession,
    venue_id: uuid.UUID,
    visit_id: uuid.UUID,
    *,
    lock: bool = False,
    active: bool = False,
) -> ServiceVisit:
    query = (
        select(ServiceVisit)
        .where(ServiceVisit.venue_id == venue_id, ServiceVisit.id == visit_id)
        .execution_options(populate_existing=True)
    )
    if lock:
        query = query.with_for_update()
    row = (await db.execute(query)).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, "Besuch nicht gefunden.")
    if active and row.ended_at is not None:
        raise HTTPException(409, "Dieser Besuch ist beendet. Einen neuen Aufenthalt eröffnen.")
    return row


async def tab_for(
    db: AsyncSession, venue_id: uuid.UUID, tab_id: uuid.UUID, *, lock: bool = False
) -> GuestTab:
    query = (
        select(GuestTab)
        .where(GuestTab.venue_id == venue_id, GuestTab.id == tab_id)
        .execution_options(populate_existing=True)
    )
    if lock:
        query = query.with_for_update()
    row = (await db.execute(query)).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, "Gastkonto nicht gefunden.")
    return row


async def visit_read(db: AsyncSession, visit: ServiceVisit) -> VisitRead:
    tabs = (
        await db.execute(
            select(GuestTab)
            .where(GuestTab.visit_id == visit.id)
            .order_by(GuestTab.kind, GuestTab.number)
        )
    ).scalars()
    return VisitRead(
        **{
            key: getattr(visit, key)
            for key in (
                "id",
                "venue_id",
                "number",
                "label",
                "version",
                "ended_at",
                "created_at",
                "reservation_id",
            )
        },
        tabs=[TabRead.model_validate(tab) for tab in tabs],
    )


async def assignment_map(
    db: AsyncSession, venue_id: uuid.UUID, order_ids: list[uuid.UUID]
) -> dict[tuple[uuid.UUID, str, int], ServiceUnitAssignment]:
    if not order_ids:
        return {}
    rows = (
        await db.execute(
            select(ServiceUnitAssignment)
            .where(
                ServiceUnitAssignment.venue_id == venue_id,
                ServiceUnitAssignment.order_id.in_(order_ids),
            )
            .distinct(
                ServiceUnitAssignment.order_id,
                ServiceUnitAssignment.line_id,
                ServiceUnitAssignment.unit,
            )
            .order_by(
                ServiceUnitAssignment.order_id,
                ServiceUnitAssignment.line_id,
                ServiceUnitAssignment.unit,
                ServiceUnitAssignment.version.desc(),
            )
        )
    ).scalars()
    return {(row.order_id, str(row.line_id), row.unit): row for row in rows}


async def context_bound_order_ids(
    db: AsyncSession, venue_id: uuid.UUID, order_ids: list[uuid.UUID]
) -> set[uuid.UUID]:
    if not order_ids:
        return set()
    from app.gastro import cash

    bound = set(
        (
            await db.execute(
                select(ServiceRoundChild.order_id).where(
                    ServiceRoundChild.venue_id == venue_id,
                    ServiceRoundChild.order_id.in_(order_ids),
                )
            )
        ).scalars()
    )
    assignments = await assignment_map(db, venue_id, order_ids)
    orders = (
        await db.execute(
            select(Order).where(Order.venue_id == venue_id, Order.id.in_(set(order_ids) - bound))
        )
    ).scalars()
    for order in orders:
        active = [
            unit
            for unit in cash.units_for(order, [])
            if unit.kind == "product" and not unit.cancelled
        ]
        if active and all((order.id, u.line_id, u.unit) in assignments for u in active):
            bound.add(order.id)
    return bound


async def presence(db: AsyncSession, venue_id: uuid.UUID) -> list[TablePresenceRead]:
    tabs = (
        await db.execute(
            select(GuestTab)
            .join(ServiceVisit, ServiceVisit.id == GuestTab.visit_id)
            .where(
                GuestTab.venue_id == venue_id,
                GuestTab.kind == "guest",
                GuestTab.present.is_(True),
                GuestTab.current_table_id.is_not(None),
                ServiceVisit.ended_at.is_(None),
            )
            .order_by(GuestTab.current_table_id, GuestTab.id)
        )
    ).scalars()
    grouped: dict[uuid.UUID, list[GuestTab]] = {}
    for tab in tabs:
        assert tab.current_table_id is not None
        grouped.setdefault(tab.current_table_id, []).append(tab)
    return [
        TablePresenceRead(
            table_id=key,
            visit_ids=sorted({t.visit_id for t in rows}),
            guest_tab_ids=[t.id for t in rows],
            guest_count=len(rows),
        )
        for key, rows in grouped.items()
    ]


async def order_contexts(
    db: AsyncSession, venue_id: uuid.UUID, order_ids: list[uuid.UUID]
) -> list[OrderServiceContextRead]:
    assignments = await assignment_map(db, venue_id, order_ids)
    children = {
        row.order_id: row
        for row in (
            await db.execute(
                select(ServiceRoundChild).where(
                    ServiceRoundChild.venue_id == venue_id,
                    ServiceRoundChild.order_id.in_(order_ids),
                )
            )
        ).scalars()
    }
    tab_ids = {row.guest_tab_id for row in assignments.values()} | {
        row.guest_tab_id for row in children.values()
    }
    tabs = {
        row.id: row
        for row in (
            await db.execute(
                select(GuestTab).where(GuestTab.venue_id == venue_id, GuestTab.id.in_(tab_ids))
            )
        ).scalars()
    }
    visits = {
        row.id: row
        for row in (
            await db.execute(
                select(ServiceVisit).where(ServiceVisit.id.in_({t.visit_id for t in tabs.values()}))
            )
        ).scalars()
    }
    rounds = {
        row.id: row
        for row in (
            await db.execute(
                select(ServiceRound).where(
                    ServiceRound.id.in_({c.round_id for c in children.values()})
                )
            )
        ).scalars()
    }
    result: list[OrderServiceContextRead] = []
    for order_id in order_ids:
        selected = [row for key, row in assignments.items() if key[0] == order_id]
        child = children.get(order_id)
        selected_ids = {a.guest_tab_id for a in selected} | (
            {child.guest_tab_id} if child else set()
        )
        if not selected_ids:
            continue
        selected_tabs = [tabs[key] for key in sorted(selected_ids)]
        visit = visits[selected_tabs[0].visit_id]
        round_ = rounds[child.round_id] if child else None
        result.append(
            OrderServiceContextRead(
                order_id=order_id,
                round_id=round_.id if round_ else None,
                round_number=round_.number if round_ else None,
                visit_id=visit.id,
                visit_number=visit.number,
                tabs=[TabRead.model_validate(t) for t in selected_tabs],
                assignments=[AssignedUnitRead.model_validate(a) for a in selected],
            )
        )
    return result


async def placement(
    db: AsyncSession,
    venue: Venue,
    specs: list[TabSpec],
    reservation_id: uuid.UUID | None = None,
    previous_tables: list[uuid.UUID] | None = None,
    *,
    exclude_tab_id: uuid.UUID | None = None,
    initial_reservation: bool = False,
) -> None:
    from app.gastro.booking_service import conflicting_resources, table_ids_for

    table_ids = sorted(
        {s.current_table_id for s in specs if s.current_table_id} | set(previous_tables or [])
    )
    if table_ids:
        tables = list(
            (
                await db.execute(
                    select(DiningTable)
                    .where(DiningTable.venue_id == venue.id, DiningTable.id.in_(table_ids))
                    .order_by(DiningTable.id)
                    .with_for_update()
                )
            ).scalars()
        )
        if {t.id for t in tables} != set(table_ids) or any(t.kind != "table" for t in tables):
            raise HTTPException(422, "Für Gäste nur Tische desselben Betriebs auswählen.")
        active = (
            await db.execute(
                select(GuestTab)
                .join(ServiceVisit, ServiceVisit.id == GuestTab.visit_id)
                .where(
                    GuestTab.venue_id == venue.id,
                    GuestTab.current_table_id.in_(table_ids),
                    GuestTab.kind == "guest",
                    GuestTab.present.is_(True),
                    ServiceVisit.ended_at.is_(None),
                )
            )
        ).scalars()
        existing = [tab for tab in active if tab.id != exclude_tab_id]
        for table in tables:
            candidates = [
                spec
                for spec in specs
                if spec.current_table_id == table.id and spec.present and spec.kind == "guest"
            ]
            kept = [tab for tab in existing if tab.current_table_id == table.id]
            if candidates and len(kept) + len(candidates) > table.seats:
                raise HTTPException(
                    409, f"{table.name}: nicht genügend freie Plätze für diese anwesenden Gäste."
                )
            people: list[GuestTab | TabSpec] = [*kept, *candidates]
            labels = [person.seat_label.casefold() for person in people if person.seat_label]
            if len(set(labels)) != len(labels):
                raise HTTPException(
                    409,
                    f"{table.name}: dieser Sitzplatz ist bereits einer anwesenden Person zugeordnet.",
                )
    if reservation_id:
        reservation = (
            await db.execute(
                select(Reservation).where(
                    Reservation.venue_id == venue.id, Reservation.id == reservation_id
                )
            )
        ).scalar_one_or_none()
        if reservation is None or initial_reservation and reservation.status != "seated":
            raise HTTPException(
                422,
                "Nur eine ausdrücklich ausgewählte, bereits eingecheckte Reservierung zuordnen.",
            )
        reserved = set(await table_ids_for(db, reservation))
        if initial_reservation and not {
            s.current_table_id for s in specs if s.current_table_id
        }.issubset(reserved):
            raise HTTPException(422, "Der Gastort gehört nicht zur ausgewählten Reservierung.")
    occupied = [
        s.current_table_id for s in specs if s.current_table_id and s.present and s.kind == "guest"
    ]
    now = datetime.now(UTC)
    if occupied and await conflicting_resources(
        db,
        occupied,
        now,
        now + timedelta(minutes=venue.default_stay_minutes),
        exclude_reservation_id=reservation_id,
        live=True,
        ignore_order_occupancy=True,
    ):
        raise HTTPException(
            409,
            "Dieser Tisch ist reserviert oder als Aktivität in Nutzung. Vorher im Reservierungsablauf klären oder einen anderen Tisch wählen.",
        )


def new_tab(
    venue_id: uuid.UUID, visit_id: uuid.UUID, number: int, spec: TabSpec, command_id: uuid.UUID
) -> GuestTab:
    return GuestTab(
        id=uuid.uuid4(),
        venue_id=venue_id,
        visit_id=visit_id,
        number=number,
        **spec.model_dump(),
        version=1,
        last_command_id=command_id,
    )


@router.get(
    "/venues/{venue_id}/service-settings",
    response_model=SettingsRead,
    status_code=200,
    summary="Arbeitsweise des Gastservices lesen",
)
async def get_settings(venue_id: uuid.UUID, db: ReportingDB, user: Actor) -> SettingsRead:
    await svc.venue_access(db, user, venue_id, svc.SERVICE)
    row = (
        await db.execute(select(ServiceSettings).where(ServiceSettings.venue_id == venue_id))
    ).scalar_one_or_none()
    return SettingsRead.model_validate(row, from_attributes=True) if row else SettingsRead()


@router.put(
    "/venues/{venue_id}/service-settings",
    response_model=SettingsRead,
    status_code=201,
    summary="Darstellungsstandard ändern, offene Bons erhalten",
)
async def put_settings(
    venue_id: uuid.UUID, data: SettingsInput, user: Actor, db: DB
) -> SettingsRead:
    await svc.venue_access(db, user, venue_id, svc.MANAGERS, lock=True)
    prior = await replay(db, venue_id, user, "settings", venue_id, data, data.request_key)
    if prior:
        return SettingsRead.model_validate(prior.result)
    row = (
        await db.execute(select(ServiceSettings).where(ServiceSettings.venue_id == venue_id))
    ).scalar_one_or_none()
    svc.check_version(row.version if row else 0, data.version)
    old = await state(db, row) if row else None
    cid = uuid.uuid4()
    if row is None:
        row = ServiceSettings(id=uuid.uuid4(), venue_id=venue_id, version=0)
        db.add(row)
    row.workflow, row.guest_label_mode = data.workflow, data.guest_label_mode
    row.version += 1
    row.last_command_id = cid
    await db.flush()
    result = SettingsRead.model_validate(row, from_attributes=True)
    await record(
        db,
        venue_id,
        user,
        "settings",
        venue_id,
        data,
        data.request_key,
        cid,
        result,
        [await snapshot(db, row, old)],
    )
    return result


@router.post(
    "/venues/{venue_id}/service-visits",
    response_model=VisitRead,
    status_code=201,
    summary="Besuch mit Gästen ohne Registrierung eröffnen",
)
async def create_visit(venue_id: uuid.UUID, data: VisitCreate, user: Actor, db: DB) -> VisitRead:
    venue, _ = await svc.venue_access(db, user, venue_id, svc.SERVICE, lock=True)
    prior = await replay(db, venue_id, user, "visit_created", venue_id, data, data.request_key)
    if prior:
        return VisitRead.model_validate(prior.result)
    await placement(db, venue, data.tabs, data.reservation_id, initial_reservation=True)
    if (
        data.reservation_id
        and (
            await db.execute(
                select(ServiceVisit.id).where(ServiceVisit.reservation_id == data.reservation_id)
            )
        ).first()
    ):
        raise HTTPException(409, "Für diese Reservierung besteht bereits ein Besuch.")
    cid = uuid.uuid4()
    number = (
        int(
            (
                await db.execute(
                    select(func.count())
                    .select_from(ServiceVisit)
                    .where(ServiceVisit.venue_id == venue_id)
                )
            ).scalar_one()
        )
        + 1
    )
    visit = ServiceVisit(
        id=uuid.uuid4(),
        venue_id=venue_id,
        number=f"V-{number}",
        label=data.label,
        reservation_id=data.reservation_id,
        version=1,
        last_command_id=cid,
    )
    db.add(visit)
    await db.flush()
    counters = {"guest": 0, "shared": 0}
    tabs = []
    for spec in data.tabs:
        counters[spec.kind] += 1
        tabs.append(new_tab(venue_id, visit.id, counters[spec.kind], spec, cid))
    db.add_all(tabs)
    await db.flush()
    result = await visit_read(db, visit)
    await record(
        db,
        venue_id,
        user,
        "visit_created",
        venue_id,
        data,
        data.request_key,
        cid,
        result,
        [await snapshot(db, visit), *[await snapshot(db, t) for t in tabs]],
    )
    return result


@router.get(
    "/venues/{venue_id}/service-visits",
    response_model=VisitPage,
    status_code=200,
    summary="Besuche mit expliziter Fortsetzung lesen",
)
async def list_visits(
    venue_id: uuid.UUID,
    db: ReportingDB,
    user: Actor,
    active: bool = True,
    table_id: uuid.UUID | None = None,
    before: uuid.UUID | None = None,
    limit: int = Query(default=50, ge=1, le=100),
) -> VisitPage:
    await svc.venue_access(db, user, venue_id, svc.SERVICE)
    query = select(ServiceVisit).where(ServiceVisit.venue_id == venue_id)
    if active:
        query = query.where(ServiceVisit.ended_at.is_(None))
    if table_id:
        query = query.where(
            ServiceVisit.id.in_(
                select(GuestTab.visit_id).where(
                    GuestTab.current_table_id == table_id, GuestTab.venue_id == venue_id
                )
            )
        )
    if before:
        cursor = await visit_for(db, venue_id, before)
        query = query.where(
            tuple_(ServiceVisit.created_at, ServiceVisit.id) < (cursor.created_at, cursor.id)
        )
    rows = list(
        (
            await db.execute(
                query.order_by(ServiceVisit.created_at.desc(), ServiceVisit.id.desc()).limit(
                    limit + 1
                )
            )
        ).scalars()
    )
    more = len(rows) > limit
    rows = rows[:limit]
    return VisitPage(
        items=[await visit_read(db, row) for row in rows],
        has_more=more,
        next_before=rows[-1].id if more else None,
    )


@router.get(
    "/venues/{venue_id}/service-visits/{visit_id}",
    response_model=VisitRead,
    status_code=200,
    summary="Besuch und aktuelle Gäste lesen",
)
async def get_visit(
    venue_id: uuid.UUID, visit_id: uuid.UUID, db: ReportingDB, user: Actor
) -> VisitRead:
    await svc.venue_access(db, user, venue_id, svc.SERVICE)
    return await visit_read(db, await visit_for(db, venue_id, visit_id))


@router.get(
    "/venues/{venue_id}/guest-tabs/{tab_id}",
    response_model=TabRead,
    status_code=200,
    summary="Betriebliches Gastkonto lesen",
)
async def get_tab(venue_id: uuid.UUID, tab_id: uuid.UUID, db: ReportingDB, user: Actor) -> TabRead:
    await svc.venue_access(db, user, venue_id, svc.SERVICE)
    return TabRead.model_validate(await tab_for(db, venue_id, tab_id))


@router.post(
    "/venues/{venue_id}/service-visits/{visit_id}/guest-tabs",
    response_model=TabRead,
    status_code=201,
    summary="Einen weiteren Gast zum Besuch hinzufügen",
)
async def create_tab(
    venue_id: uuid.UUID, visit_id: uuid.UUID, data: TabCreate, user: Actor, db: DB
) -> TabRead:
    venue, _ = await svc.venue_access(db, user, venue_id, svc.SERVICE, lock=True)
    prior = await replay(db, venue_id, user, "tab_created", visit_id, data, data.request_key)
    if prior:
        return TabRead.model_validate(prior.result)
    visit = await visit_for(db, venue_id, visit_id, active=True)
    svc.check_version(visit.version, data.visit_version)
    spec = TabSpec.model_validate(data.model_dump(exclude={"request_key", "visit_version"}))
    await placement(db, venue, [spec], visit.reservation_id)
    tabs = list((await db.execute(select(GuestTab).where(GuestTab.visit_id == visit.id))).scalars())
    if len(tabs) >= 100 or data.kind == "shared" and any(t.kind == "shared" for t in tabs):
        raise HTTPException(409, "Gastgrenze erreicht oder Gemeinsam besteht bereits.")
    old = await state(db, visit)
    cid = uuid.uuid4()
    visit.version += 1
    visit.last_command_id = cid
    tab = new_tab(
        venue_id,
        visit.id,
        max((t.number for t in tabs if t.kind == data.kind), default=0) + 1,
        spec,
        cid,
    )
    db.add(tab)
    await db.flush()
    result = TabRead.model_validate(tab)
    await record(
        db,
        venue_id,
        user,
        "tab_created",
        visit_id,
        data,
        data.request_key,
        cid,
        result,
        [await snapshot(db, visit, old), await snapshot(db, tab)],
    )
    return result


@router.post(
    "/venues/{venue_id}/guest-tabs/{tab_id}/context",
    response_model=TabRead,
    status_code=201,
    summary="Gast umbenennen, umsetzen oder Anwesenheit ändern",
)
async def change_context(
    venue_id: uuid.UUID, tab_id: uuid.UUID, data: TabContext, user: Actor, db: DB
) -> TabRead:
    venue, _ = await svc.venue_access(db, user, venue_id, svc.SERVICE, lock=True)
    prior = await replay(db, venue_id, user, "tab_context", tab_id, data, data.request_key)
    if prior:
        return TabRead.model_validate(prior.result)
    tab = await tab_for(db, venue_id, tab_id)
    visit = await visit_for(db, venue_id, tab.visit_id, active=True)
    svc.check_version(tab.version, data.version)
    if tab.kind == "shared" and data.present:
        raise HTTPException(422, "Gemeinsam zählt nicht als anwesende Person.")
    spec = TabSpec(
        kind=cast(Literal["guest", "shared"], tab.kind),
        label=data.label,
        current_table_id=data.current_table_id,
        seat_label=data.seat_label,
        present=data.present,
    )
    await placement(
        db,
        venue,
        [spec],
        visit.reservation_id,
        [tab.current_table_id] if tab.current_table_id else [],
        exclude_tab_id=tab.id,
    )
    old = await state(db, tab)
    cid = uuid.uuid4()
    for field in ("label", "current_table_id", "seat_label", "present"):
        setattr(tab, field, getattr(data, field))
    tab.version += 1
    tab.last_command_id = cid
    await db.flush()
    result = TabRead.model_validate(tab)
    await record(
        db,
        venue_id,
        user,
        "tab_context",
        tab_id,
        data,
        data.request_key,
        cid,
        result,
        [await snapshot(db, tab, old)],
        data.reason,
    )
    return result


@router.post(
    "/venues/{venue_id}/service-visits/{visit_id}/end",
    response_model=VisitRead,
    status_code=201,
    summary="Anwesenheit ausdrücklich beenden und offene Belege erhalten",
)
async def end_visit(
    venue_id: uuid.UUID, visit_id: uuid.UUID, data: VisitEnd, user: Actor, db: DB
) -> VisitRead:
    venue, _ = await svc.venue_access(db, user, venue_id, svc.SERVICE, lock=True)
    prior = await replay(db, venue_id, user, "visit_ended", visit_id, data, data.request_key)
    if prior:
        return VisitRead.model_validate(prior.result)
    visit = await visit_for(db, venue_id, visit_id, active=True)
    svc.check_version(visit.version, data.version)
    tabs = list((await db.execute(select(GuestTab).where(GuestTab.visit_id == visit_id))).scalars())
    await placement(
        db, venue, [], previous_tables=[t.current_table_id for t in tabs if t.current_table_id]
    )
    cid = uuid.uuid4()
    old = await state(db, visit)
    visit.ended_at = datetime.now(UTC)
    visit.version += 1
    visit.last_command_id = cid
    snapshots = []
    for tab in tabs:
        if tab.present:
            old_tab = await state(db, tab)
            tab.present = False
            tab.version += 1
            tab.last_command_id = cid
            snapshots.append((tab, old_tab))
    await db.flush()
    result = await visit_read(db, visit)
    await record(
        db,
        venue_id,
        user,
        "visit_ended",
        visit_id,
        data,
        data.request_key,
        cid,
        result,
        [
            await snapshot(db, visit, old),
            *[await snapshot(db, tab, prior_state) for tab, prior_state in snapshots],
        ],
        data.reason,
    )
    return result


async def round_read(db: AsyncSession, round_: ServiceRound) -> RoundRead:
    rows = (
        await db.execute(
            select(ServiceRoundChild, Order)
            .join(Order, Order.id == ServiceRoundChild.order_id)
            .where(ServiceRoundChild.round_id == round_.id)
            .order_by(ServiceRoundChild.guest_tab_id)
        )
    ).all()
    return RoundRead(
        id=round_.id,
        visit_id=round_.visit_id,
        number=round_.number,
        created_at=round_.created_at,
        children=[
            RoundChildRead(
                guest_tab_id=child.guest_tab_id,
                order_id=order.id,
                number=order.number,
                label_snapshot=child.label_snapshot,
                order=OrderRead.model_validate(order),
            )
            for child, order in rows
        ],
    )


@router.post(
    "/venues/{venue_id}/service-visits/{visit_id}/rounds",
    response_model=RoundRead,
    status_code=201,
    summary="Eine Runde atomar als unabhängige Gastbons senden",
)
async def create_round(
    venue_id: uuid.UUID, visit_id: uuid.UUID, data: RoundInput, user: Actor, db: DB
) -> RoundRead:
    venue, _ = await svc.venue_access(db, user, venue_id, svc.SERVICE, lock=True)
    prior = await replay(db, venue_id, user, "round_created", visit_id, data, data.request_key)
    if prior:
        return RoundRead.model_validate(prior.result)
    visit = await visit_for(db, venue_id, visit_id, active=True)
    svc.check_version(visit.version, data.visit_version)
    selected = sorted(tv.guest_tab_id for tv in data.tab_versions)
    tabs = {
        tab.id: tab
        for tab in (
            await db.execute(
                select(GuestTab).where(
                    GuestTab.venue_id == venue_id,
                    GuestTab.visit_id == visit_id,
                    GuestTab.id.in_(selected),
                )
            )
        ).scalars()
    }
    if set(tabs) != set(selected):
        raise HTTPException(404, "Ein Gast gehört nicht zu diesem Besuch.")
    for expected in data.tab_versions:
        svc.check_version(tabs[expected.guest_tab_id].version, expected.version)
    if any(tab.kind == "guest" and not tab.present for tab in tabs.values()):
        raise HTTPException(
            409, "Eine Person ist bereits gegangen; Anwesenheit zuerst ausdrücklich ändern."
        )
    cid = uuid.uuid4()
    number = (
        int(
            (
                await db.execute(
                    select(func.count())
                    .select_from(ServiceRound)
                    .where(ServiceRound.visit_id == visit_id)
                )
            ).scalar_one()
        )
        + 1
    )
    round_ = ServiceRound(
        id=uuid.uuid4(),
        venue_id=venue_id,
        visit_id=visit_id,
        number=number,
        command_id=cid,
        expected_tab_ids=[str(key) for key in selected],
    )
    db.add(round_)
    await db.flush()
    for tab_id in selected:
        tab = tabs[tab_id]
        inputs = []
        sources = []
        for row in data.rows:
            assignment = next((a for a in row.assignments if a.guest_tab_id == tab_id), None)
            if assignment is None:
                continue
            inputs.append(
                LineInput(
                    item_id=row.item_id,
                    menu_version=row.menu_version,
                    quantity=len(assignment.units),
                    course=row.course,
                    note=row.note,
                )
            )
            sources.append((row.cart_row_id, sorted(assignment.units)))
        child_key = uuid.uuid5(data.request_key, str(tab_id))
        if (
            await db.execute(
                select(Order.id).where(Order.venue_id == venue_id, Order.request_key == child_key)
            )
        ).first():
            raise HTTPException(409, "Ein abgeleiteter Bestellschlüssel ist bereits belegt.")
        source_rows: dict[str, int] = {}
        order = await svc.create_order(
            db,
            venue,
            OrderInput(
                request_key=child_key,
                table_id=tab.current_table_id if data.fulfillment == "dine_in" else None,
                guests=1,
                fulfillment=data.fulfillment,
                lines=inputs,
                note=data.note,
                accept_warnings=data.accept_warnings,
            ),
            user_id=user.id,
            source_rows=source_rows,
        )
        db.add(
            ServiceRoundChild(
                venue_id=venue_id,
                round_id=round_.id,
                guest_tab_id=tab.id,
                order_id=order.id,
                label_snapshot=tab.label
                or ("Gemeinsam" if tab.kind == "shared" else f"Gast {tab.number}"),
            )
        )
        for line in order.lines:
            line_id = str(line["line_id"])
            cart_id, cart_units = sources[source_rows[line_id]]
            for local_unit in range(int(str(line["quantity"]))):
                db.add(
                    ServiceUnitAssignment(
                        venue_id=venue_id,
                        order_id=order.id,
                        line_id=uuid.UUID(line_id),
                        unit=local_unit,
                        guest_tab_id=tab.id,
                        version=1,
                        command_id=cid,
                        cart_row_id=cart_id,
                        cart_unit=cart_units[local_unit],
                    )
                )
    old = await state(db, visit)
    visit.version += 1
    visit.last_command_id = cid
    await db.flush()
    result = await round_read(db, round_)
    await record(
        db,
        venue_id,
        user,
        "round_created",
        visit_id,
        data,
        data.request_key,
        cid,
        result,
        [await snapshot(db, visit, old)],
    )
    return result


@router.get(
    "/venues/{venue_id}/service-visits/{visit_id}/rounds",
    response_model=RoundPage,
    status_code=200,
    summary="Runden eines Besuchs mit unveränderten Originalverweisen lesen",
)
async def rounds(
    venue_id: uuid.UUID,
    visit_id: uuid.UUID,
    db: ReportingDB,
    user: Actor,
    before: uuid.UUID | None = None,
    limit: int = Query(default=50, ge=1, le=100),
) -> RoundPage:
    await svc.venue_access(db, user, venue_id, svc.SERVICE)
    await visit_for(db, venue_id, visit_id)
    query = select(ServiceRound).where(
        ServiceRound.venue_id == venue_id, ServiceRound.visit_id == visit_id
    )
    if before:
        cursor = (
            await db.execute(
                select(ServiceRound).where(
                    ServiceRound.venue_id == venue_id,
                    ServiceRound.visit_id == visit_id,
                    ServiceRound.id == before,
                )
            )
        ).scalar_one_or_none()
        if cursor is None:
            raise HTTPException(404, "Rundengrenze nicht gefunden.")
        query = query.where(ServiceRound.number < cursor.number)
    rows = list(
        (await db.execute(query.order_by(ServiceRound.number.desc()).limit(limit + 1))).scalars()
    )
    more = len(rows) > limit
    rows = rows[:limit]
    return RoundPage(
        items=[await round_read(db, row) for row in rows],
        next_before=rows[-1].id if more else None,
        has_more=more,
    )


@router.get(
    "/venues/{venue_id}/service-rounds/{round_id}",
    response_model=RoundRead,
    status_code=200,
    summary="Eine gemeinsame Runde mit unabhängigen aktuellen Kindbons lesen",
)
async def get_round(
    venue_id: uuid.UUID, round_id: uuid.UUID, db: ReportingDB, user: Actor
) -> RoundRead:
    await svc.venue_access(db, user, venue_id, svc.SERVICE)
    row = (
        await db.execute(
            select(ServiceRound).where(
                ServiceRound.venue_id == venue_id, ServiceRound.id == round_id
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, "Runde nicht gefunden.")
    return await round_read(db, row)


async def assignment_preview(
    db: AsyncSession, venue_id: uuid.UUID, data: AssignmentInput
) -> AssignmentPreview:
    from app.gastro import cash

    tab = await tab_for(db, venue_id, data.guest_tab_id)
    await visit_for(db, venue_id, tab.visit_id, active=True)
    svc.check_version(tab.version, data.tab_version)
    ids = sorted({u.order_id for u in data.units})
    if len(ids) > 50:
        raise HTTPException(422, "Höchstens 50 Originalbons je Zuordnung.")
    orders = {
        row.id: row
        for row in (
            await db.execute(
                select(Order)
                .where(Order.venue_id == venue_id, Order.id.in_(ids))
                .order_by(Order.id)
                .with_for_update()
            )
        ).scalars()
    }
    if set(orders) != set(ids):
        raise HTTPException(404, "Originalbon nicht gefunden.")
    assignments = await assignment_map(db, venue_id, ids)
    assigned_tabs = {a.guest_tab_id for a in assignments.values()}
    if (
        await db.execute(
            select(GuestTab.id).where(
                GuestTab.id.in_(assigned_tabs), GuestTab.visit_id != tab.visit_id
            )
        )
    ).first():
        raise HTTPException(409, "Die Originale sind einem anderen Besuch zugeordnet.")
    units: dict[tuple[uuid.UUID, str, int], cash.Unit] = {}
    source: list[object] = []
    blockers: list[str] = []
    for order in orders.values():
        entries = await cash.order_entries(db, order)
        source.append(
            [str(order.id), order.version, [(str(e.id), e.amount_cents) for e in entries]]
        )
        for cash_unit in cash.units_for(order, entries):
            units[(order.id, cash_unit.line_id, cash_unit.unit)] = cash_unit
        if order.pos_requested or order.paid_at or order.voucher_cents:
            blockers.append(
                f"{order.number}: an die Kasse übergeben, bezahlt oder durch Gutschein gebunden."
            )
    for requested in data.units:
        key = (requested.order_id, str(requested.line_id), requested.unit)
        unit = units.get(key)
        if unit is None or unit.kind == "tip":
            raise HTTPException(422, "Bestehende Waren-/Gebühreneinheit auswählen.")
        previous = assignments.get(key)
        if unit.paid or unit.cancelled:
            blockers.append(f"{unit.name}: bereits finanziell gebunden oder storniert.")
        if previous and previous.guest_tab_id == tab.id:
            blockers.append(f"{unit.name}: bereits diesem Gast zugeordnet.")
        source.append(
            [
                str(requested.order_id),
                str(requested.line_id),
                requested.unit,
                str(previous.id) if previous else None,
            ]
        )
    h = hashlib.sha256(
        json.dumps(
            [data.model_dump(mode="json"), source], sort_keys=True, separators=(",", ":")
        ).encode()
    ).hexdigest()
    return AssignmentPreview(
        guest_tab_id=tab.id, units=data.units, preview_hash=h, blockers=sorted(set(blockers))
    )


@router.post(
    "/venues/{venue_id}/guest-unit-assignments/preview",
    response_model=AssignmentPreview,
    status_code=200,
    summary="Genaue Stückzuordnung prüfen ohne finanzielle Originale zu verändern",
)
async def preview_assignment(
    venue_id: uuid.UUID, data: AssignmentInput, user: Actor, db: DB
) -> AssignmentPreview:
    await svc.venue_access(db, user, venue_id, svc.SERVICE, lock=True)
    return await assignment_preview(db, venue_id, data)


@router.post(
    "/venues/{venue_id}/guest-unit-assignments/commit",
    response_model=AssignmentResult,
    status_code=201,
    summary="Unbezahlte Originalstücke nachvollziehbar einem Gast zuordnen",
)
async def assign_units(
    venue_id: uuid.UUID, data: AssignmentCommit, user: Actor, db: DB
) -> AssignmentResult:
    await svc.venue_access(db, user, venue_id, svc.SERVICE, lock=True)
    prior = await replay(
        db, venue_id, user, "units_assigned", data.guest_tab_id, data, data.request_key
    )
    if prior:
        return AssignmentResult.model_validate(prior.result)
    preview = await assignment_preview(
        db,
        venue_id,
        AssignmentInput.model_validate(data.model_dump(exclude={"request_key", "preview_hash"})),
    )
    if preview.blockers or preview.preview_hash != data.preview_hash:
        raise HTTPException(
            409,
            "Zuordnung geändert oder gesperrt. Vorschau erneut prüfen: "
            + " ".join(preview.blockers),
        )
    current = await assignment_map(db, venue_id, sorted({u.order_id for u in data.units}))
    cid = uuid.uuid4()
    rows = []
    for unit in data.units:
        old = current.get((unit.order_id, str(unit.line_id), unit.unit))
        row = ServiceUnitAssignment(
            venue_id=venue_id,
            order_id=unit.order_id,
            line_id=unit.line_id,
            unit=unit.unit,
            guest_tab_id=data.guest_tab_id,
            version=old.version + 1 if old else 1,
            command_id=cid,
            before_tab_id=old.guest_tab_id if old else None,
            cart_row_id=old.cart_row_id if old else None,
            cart_unit=old.cart_unit if old else None,
        )
        db.add(row)
        rows.append(row)
    await db.flush()
    result = AssignmentResult(assignments=[AssignedUnitRead.model_validate(row) for row in rows])
    await record(
        db,
        venue_id,
        user,
        "units_assigned",
        data.guest_tab_id,
        data,
        data.request_key,
        cid,
        result,
        [],
        data.reason,
    )
    return result


@router.get(
    "/venues/{venue_id}/order-service-contexts",
    response_model=list[OrderServiceContextRead],
    status_code=200,
    summary="Gast-/Rundenkontext für mehrere Originalbons gemeinsam lesen",
)
async def get_order_contexts(
    venue_id: uuid.UUID,
    db: ReportingDB,
    user: Actor,
    order_id: list[uuid.UUID] = Query(min_length=1, max_length=100),
) -> list[OrderServiceContextRead]:
    await svc.venue_access(db, user, venue_id, svc.KITCHEN)
    return await order_contexts(db, venue_id, list(dict.fromkeys(order_id)))


@router.get(
    "/venues/{venue_id}/service-presence",
    response_model=list[TablePresenceRead],
    status_code=200,
    summary="Aktuelle Anwesenheit unabhängig von Bons und Zahlung lesen",
)
async def get_presence(
    venue_id: uuid.UUID, db: ReportingDB, user: Actor
) -> list[TablePresenceRead]:
    await svc.venue_access(db, user, venue_id, svc.KITCHEN)
    return await presence(db, venue_id)


@router.get(
    "/venues/{venue_id}/service-visits/{visit_id}/history",
    response_model=HistoryPage,
    status_code=200,
    summary="Besuchs- und Gaständerungen unveränderlich nachvollziehen",
)
async def history(
    venue_id: uuid.UUID,
    visit_id: uuid.UUID,
    db: ReportingDB,
    user: Actor,
    before: uuid.UUID | None = None,
    limit: int = Query(default=50, ge=1, le=100),
) -> HistoryPage:
    await svc.venue_access(db, user, venue_id, svc.SERVICE)
    await visit_for(db, venue_id, visit_id)
    tabs = list(
        (await db.execute(select(GuestTab.id).where(GuestTab.visit_id == visit_id))).scalars()
    )
    # Initial create targets venue so its immutable result identifies the visit.
    query = select(ServiceCommand).where(
        ServiceCommand.venue_id == venue_id,
        (ServiceCommand.target_id.in_([visit_id, *tabs]))
        | (
            (ServiceCommand.kind == "visit_created")
            & (ServiceCommand.result["id"].astext == str(visit_id))
        ),
    )
    if before:
        cursor = (await db.execute(query.where(ServiceCommand.id == before))).scalar_one_or_none()
        if cursor is None:
            raise HTTPException(404, "Verlaufsgrenze nicht gefunden.")
        query = query.where(
            tuple_(ServiceCommand.created_at, ServiceCommand.id) < (cursor.created_at, cursor.id)
        )
    rows = list(
        (
            await db.execute(
                query.order_by(ServiceCommand.created_at.desc(), ServiceCommand.id.desc()).limit(
                    limit + 1
                )
            )
        ).scalars()
    )
    more = len(rows) > limit
    rows = rows[:limit]
    return HistoryPage(
        items=[CommandRead.model_validate(row) for row in rows],
        next_before=rows[-1].id if more else None,
        has_more=more,
    )
