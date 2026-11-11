"""Venue-scoped routing, immutable order snapshots and work competence mapping."""

from __future__ import annotations

import uuid
from collections.abc import Iterable

from fastapi import HTTPException
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.gastro.models import MenuItem, Shift
from app.gastro.schemas import MenuPayload, ShiftRead
from app.gastro.station_models import OperatingStation
from app.gastro.station_schemas import StationSnapshot

DEFAULT_STATIONS = (
    ("kitchen", "Küche", "kitchen", 10),
    ("bar", "Bar", "bar", 20),
    ("service", "Service", "service", 30),
    ("activities", "Aktivitäten", "activities", 40),
)
PREPARATION_KINDS = frozenset({"kitchen", "bar"})
LEGACY_CODES = {
    "küche": "kitchen",
    "kueche": "kitchen",
    "kitchen": "kitchen",
    "bar": "bar",
    "service": "service",
    "aktivitäten": "activities",
    "aktivitaeten": "activities",
    "activities": "activities",
}


async def ensure_defaults(db: AsyncSession, venue_id: uuid.UUID) -> None:
    """Creation/migration path only; reads never invent a missing station."""
    existing = set(
        (
            await db.execute(
                select(OperatingStation.code).where(OperatingStation.venue_id == venue_id)
            )
        ).scalars()
    )
    for code, name, kind, order in DEFAULT_STATIONS:
        if code not in existing:
            db.add(
                OperatingStation(
                    id=uuid.uuid5(venue_id, f"flintplate.station:{code}"),
                    venue_id=venue_id,
                    code=code,
                    name=name,
                    kind=kind,
                    sort_order=order,
                )
            )
    await db.flush()


async def resolve_stations(
    db: AsyncSession,
    venue_id: uuid.UUID,
    codes: Iterable[str],
    *,
    preparation: bool = False,
    active: bool = True,
) -> dict[str, OperatingStation]:
    requested = set(codes)
    if not requested:
        return {}
    rows = list(
        (
            await db.execute(
                select(OperatingStation).where(
                    OperatingStation.venue_id == venue_id, OperatingStation.code.in_(requested)
                )
            )
        ).scalars()
    )
    found = {row.code: row for row in rows}
    if set(found) != requested:
        raise HTTPException(422, "Eine Station ist in diesem Betrieb nicht konfiguriert.")
    if active and any(not row.active for row in rows):
        raise HTTPException(409, "Eine zugeordnete Station ist nicht mehr aktiv.")
    if preparation and any(row.kind not in PREPARATION_KINDS for row in rows):
        raise HTTPException(422, "Artikel benötigen eine konfigurierte Küchen- oder Barstation.")
    return found


def snapshot(station: OperatingStation) -> StationSnapshot:
    return StationSnapshot.model_validate(station, from_attributes=True)


async def menu_payload(db: AsyncSession, venue_id: uuid.UUID, payload: MenuPayload) -> MenuPayload:
    station = (await resolve_stations(db, venue_id, [payload.station], preparation=True))[
        payload.station
    ]
    # Client-supplied snapshot data is never authoritative.
    return payload.model_copy(update={"station_snapshot": snapshot(station)})


def order_snapshot(payload: MenuPayload, station: OperatingStation) -> StationSnapshot:
    saved = payload.station_snapshot
    if saved is None:
        # Pre-078 published menus only used these two well-defined identities.
        if station.code not in {"kitchen", "bar"}:
            raise HTTPException(409, "Stationszuordnung neu veröffentlichen, bevor bestellt wird.")
        return snapshot(station).model_copy(
            update={
                "name": "Küche" if station.code == "kitchen" else "Bar",
            }
        )
    if (saved.id, saved.code, saved.kind) != (station.id, station.code, station.kind):
        raise HTTPException(409, "Veröffentlichte Stationszuordnung ist nicht mehr konsistent.")
    # A later station rename must not alter the published routing snapshot.
    return saved


async def require_unused(db: AsyncSession, station: OperatingStation) -> None:
    published = list(
        (
            await db.execute(
                select(MenuItem.sku)
                .where(
                    MenuItem.venue_id == station.venue_id,
                    MenuItem.published.is_not(None),
                    func.coalesce(MenuItem.published["station"].astext, "kitchen") == station.code,
                    func.coalesce(MenuItem.published["available"].as_boolean(), True).is_(True),
                )
                .order_by(MenuItem.sku)
                .limit(6)
            )
        ).scalars()
    )
    if published:
        raise HTTPException(
            409,
            "Erst veröffentlichte Artikel anders zuordnen oder deaktivieren: "
            + ", ".join(published),
        )
    in_progress = await db.scalar(
        text(
            "SELECT EXISTS(SELECT 1 FROM fp_orders o CROSS JOIN LATERAL jsonb_array_elements(o.lines) l "
            "WHERE o.venue_id=:venue AND o.status NOT IN ('settled','cancelled') "
            "AND coalesce(l->>'kind','product')='product' AND l->>'station'=:code "
            "AND coalesce(l->>'preparation_status','sent') NOT IN ('served','cancelled'))"
        ),
        {"venue": station.venue_id, "code": station.code},
    )
    if in_progress:
        raise HTTPException(
            409, "Offene Positionen dieser Station zuerst fertigstellen und servieren."
        )


async def shift_station(db: AsyncSession, venue_id: uuid.UUID, value: str) -> OperatingStation:
    code = LEGACY_CODES.get(value.strip().casefold(), value)
    return (await resolve_stations(db, venue_id, [code]))[code]


async def replacement_station(
    db: AsyncSession, venue_id: uuid.UUID, value: str
) -> OperatingStation:
    """Retain old free-text shifts while routing their replacement explicitly."""
    configured = (
        await db.execute(
            select(OperatingStation).where(
                OperatingStation.venue_id == venue_id, OperatingStation.code == value
            )
        )
    ).scalar_one_or_none()
    if configured is not None:
        return await shift_station(db, venue_id, value)
    kind = (await work_kinds(db, venue_id, [value]))[value]
    if kind is None:
        raise HTTPException(409, "Der bisherige Dienst benötigt zuerst eine Stationszuordnung.")
    return await shift_station(db, venue_id, kind)


async def station_names(
    db: AsyncSession, venue_id: uuid.UUID, values: Iterable[str]
) -> dict[str, str]:
    requested = set(values)
    if not requested:
        return {}
    rows = (
        await db.execute(
            select(OperatingStation.code, OperatingStation.name).where(
                OperatingStation.venue_id == venue_id, OperatingStation.code.in_(requested)
            )
        )
    ).all()
    configured = {code: name for code, name in rows}
    return {value: configured.get(value, value) for value in requested}


async def read_shifts(db: AsyncSession, venue_id: uuid.UUID, rows: list[Shift]) -> list[ShiftRead]:
    labels = await station_names(db, venue_id, (row.station for row in rows))
    return [
        ShiftRead.model_validate(row).model_copy(update={"station_label": labels[row.station]})
        for row in rows
    ]


async def validate_shift_publication(db: AsyncSession, venue_id: uuid.UUID, value: str) -> None:
    configured = (
        await db.execute(
            select(OperatingStation).where(
                OperatingStation.venue_id == venue_id, OperatingStation.code == value
            )
        )
    ).scalar_one_or_none()
    if configured is not None and not configured.active:
        raise HTTPException(409, "Die zugeordnete Station ist nicht mehr aktiv.")
    if configured is None and (
        value.startswith("s_") or value in {row[0] for row in DEFAULT_STATIONS}
    ):
        raise HTTPException(409, "Die konfigurierte Dienststation fehlt.")
    # Existing free-text shifts keep their legacy behavior; new shifts cannot
    # enter this path because creation requires a registry row.


async def work_kinds(
    db: AsyncSession, venue_id: uuid.UUID, values: Iterable[str]
) -> dict[str, str | None]:
    """Inactive registry rows retain their classification for historical work."""
    from app.gastro.emergency import station_kind as legacy_kind

    requested = set(values)
    if not requested:
        return {}
    rows = (
        await db.execute(
            select(OperatingStation.code, OperatingStation.kind).where(
                OperatingStation.venue_id == venue_id, OperatingStation.code.in_(requested)
            )
        )
    ).all()
    configured = {code: kind for code, kind in rows}
    if any(value.startswith("s_") and value not in configured for value in requested):
        raise HTTPException(
            409, "Die konfigurierte Dienststation fehlt. Zuordnung vor der Abrechnung prüfen."
        )
    return {
        value: configured[value] if value in configured else legacy_kind(value)
        for value in requested
    }
