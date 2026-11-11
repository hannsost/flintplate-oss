"""Map View service – geocoding + map data assembly."""

from __future__ import annotations

import logging
import uuid
from decimal import Decimal

import httpx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.maps.schemas import MapAssignmentOut, MapDataResponse, MapWorkerOut
from app.users.models import User
from app.zeitarbeit.models import Disposition, TempWorkerAvailability, WorkAssignment

logger = logging.getLogger(__name__)

# ── Static fallback: German city coordinates ──────────────────────────────────
_CITY_COORDS: dict[str, tuple[float, float]] = {
    "berlin": (52.5200, 13.4050),
    "münchen": (48.1351, 11.5820),
    "munich": (48.1351, 11.5820),
    "hamburg": (53.5753, 10.0153),
    "köln": (50.9333, 6.9500),
    "cologne": (50.9333, 6.9500),
    "frankfurt": (50.1109, 8.6821),
    "stuttgart": (48.7758, 9.1829),
    "düsseldorf": (51.2217, 6.7762),
    "dortmund": (51.5138, 7.4653),
    "essen": (51.4556, 7.0116),
    "leipzig": (51.3397, 12.3731),
    "bremen": (53.0793, 8.8017),
    "dresden": (51.0504, 13.7373),
    "hannover": (52.3759, 9.7320),
    "nürnberg": (49.4521, 11.0767),
    "nuremberg": (49.4521, 11.0767),
    "duisburg": (51.4344, 6.7623),
    "bochum": (51.4818, 7.2162),
    "wuppertal": (51.2562, 7.1508),
    "bielefeld": (52.0302, 8.5325),
    "bonn": (50.7374, 7.0982),
    "münster": (51.9607, 7.6261),
    "karlsruhe": (49.0069, 8.4037),
    "mannheim": (49.4875, 8.4660),
    "augsburg": (48.3717, 10.8983),
    "wiesbaden": (50.0782, 8.2398),
    "mönchengladbach": (51.1805, 6.4428),
    "gelsenkirchen": (51.5177, 7.0857),
    "braunschweig": (52.2689, 10.5268),
    "kiel": (54.3233, 10.1394),
    "chemnitz": (50.8278, 12.9214),
    "aachen": (50.7762, 6.0838),
    "halle": (51.4969, 11.9695),
    "magdeburg": (52.1205, 11.6276),
    "freiburg": (47.9990, 7.8421),
    "krefeld": (51.3388, 6.5853),
    "lübeck": (53.8655, 10.6866),
    "oberhausen": (51.4796, 6.8614),
    "erfurt": (50.9776, 11.0287),
    "mainz": (49.9929, 8.2473),
    "rostock": (54.0924, 12.0991),
    "kassel": (51.3127, 9.4797),
    "hagen": (51.3671, 7.4631),
    "hamm": (51.6798, 7.8162),
    "saarbrücken": (49.2401, 6.9969),
    "potsdam": (52.3906, 13.0645),
    "osnabrück": (52.2799, 8.0472),
    "oldenburg": (53.1434, 8.2147),
    "heidelberg": (49.4093, 8.6942),
    "darmstadt": (49.8728, 8.6512),
    "regensburg": (49.0134, 12.1016),
    "ingolstadt": (48.7665, 11.4258),
    "würzburg": (49.7944, 9.9294),
    "ulm": (48.3984, 9.9916),
    "paderborn": (51.7189, 8.7575),
    "wolfsburg": (52.4227, 10.7865),
    "göttingen": (51.5338, 9.9352),
    "offenbach": (50.0956, 8.7761),
    "fürth": (49.4775, 10.9887),
    "heilbronn": (49.1427, 9.2109),
    "pforzheim": (48.8921, 8.6947),
    "recklinghausen": (51.6141, 7.1976),
    "bottrop": (51.5236, 6.9289),
    "remscheid": (51.1795, 7.1895),
}


async def geocode_location(
    location: str,
    api_key: str | None = None,
) -> tuple[float, float] | None:
    """Return (lat, lng) for a location string.

    Uses Google Geocoding API when api_key is set,
    otherwise falls back to static German city lookup.
    """
    if not location:
        return None

    # Try static lookup first (covers most German cities, fast + no cost)
    lower = location.lower().strip()
    for city, coords in _CITY_COORDS.items():
        if city in lower:
            return coords

    # If API key available, try Google Geocoding
    if api_key:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(
                    "https://maps.googleapis.com/maps/api/geocode/json",
                    params={"address": location, "key": api_key, "language": "de"},
                )
                data = resp.json()
                if data.get("status") == "OK":
                    loc = data["results"][0]["geometry"]["location"]
                    return float(loc["lat"]), float(loc["lng"])
        except Exception as exc:
            logger.warning("Geocoding failed for %r: %s", location, exc)

    return None


async def get_map_data(db: AsyncSession, tenant_id: uuid.UUID | None = None) -> MapDataResponse:
    settings = get_settings()
    api_key = settings.google_maps_api_key

    # ── Load assignments ──────────────────────────────────────────────────────
    stmt = select(WorkAssignment)
    if tenant_id:
        stmt = stmt.where(WorkAssignment.tenant_id == tenant_id)
    result = await db.execute(stmt)
    assignments_db = result.scalars().all()

    # Count active dispositions per assignment (only for current tenant)
    disp_counts_stmt = (
        select(Disposition.assignment_id, func.count().label("cnt"))
        .join(WorkAssignment, Disposition.assignment_id == WorkAssignment.id)
        .where(Disposition.status == "active")
    )
    if tenant_id:
        disp_counts_stmt = disp_counts_stmt.where(WorkAssignment.tenant_id == tenant_id)
    disp_counts_stmt = disp_counts_stmt.group_by(Disposition.assignment_id)
    disp_counts_result = await db.execute(disp_counts_stmt)
    active_counts: dict[str, int] = {str(row.assignment_id): row.cnt for row in disp_counts_result}

    # Geocode and persist missing coordinates
    assignment_outs: list[MapAssignmentOut] = []
    for a in assignments_db:
        lat, lng = a.lat, a.lng
        if (lat is None or lng is None) and a.location:
            coords = await geocode_location(a.location, api_key)
            if coords:
                lat, lng = coords
                a.lat = lat
                a.lng = lng
                db.add(a)

        assignment_outs.append(
            MapAssignmentOut(
                id=str(a.id),
                title=a.title,
                location=a.location,
                lat=lat,
                lng=lng,
                status=a.status,
                required_skills=list(a.required_skills or []),
                worker_count=active_counts.get(str(a.id), 0),
            )
        )

    # ── Load pool workers ─────────────────────────────────────────────────────
    pool_stmt = (
        select(TempWorkerAvailability, User)
        .join(User, User.id == TempWorkerAvailability.user_id)
        .where(TempWorkerAvailability.is_in_pool == True)  # noqa: E712
    )
    if tenant_id:
        pool_stmt = pool_stmt.where(User.tenant_id == tenant_id)
    pool_result = await db.execute(pool_stmt)
    pool_rows = pool_result.all()

    # Find current assignment per worker (most recent active disposition for this tenant)
    active_disp_stmt = (
        select(Disposition)
        .join(WorkAssignment, Disposition.assignment_id == WorkAssignment.id)
        .where(Disposition.status == "active")
    )
    if tenant_id:
        active_disp_stmt = active_disp_stmt.where(WorkAssignment.tenant_id == tenant_id)
    active_disp_result = await db.execute(active_disp_stmt)
    active_disps = active_disp_result.scalars().all()

    # Map worker_id → (assignment_id, assignment_title)
    assignment_map = {str(a.id): a for a in assignments_db}
    worker_to_assignment: dict[str, tuple[str, str | None]] = {}
    for d in active_disps:
        wid = str(d.worker_id)
        if wid not in worker_to_assignment:
            aid = str(d.assignment_id)
            title = assignment_map.get(aid)
            worker_to_assignment[wid] = (aid, title.title if title else None)

    worker_outs: list[MapWorkerOut] = []
    for avail, user in pool_rows:
        lat, lng = avail.lat, avail.lng
        location_str = avail.preferred_location
        if (lat is None or lng is None) and location_str:
            coords = await geocode_location(location_str, api_key)
            if coords:
                lat, lng = coords
                avail.lat = lat
                avail.lng = lng
                db.add(avail)

        placed_months = float(avail.total_placed_months or Decimal("0"))
        remaining = max(0.0, 18.0 - placed_months)
        if remaining <= 0:
            aueg_status = "red"
        elif remaining <= 3:
            aueg_status = "yellow"
        else:
            aueg_status = "green"

        cur_aid, cur_title = worker_to_assignment.get(str(user.id), (None, None))
        worker_outs.append(
            MapWorkerOut(
                user_id=str(user.id),
                full_name=user.full_name,
                preferred_location=location_str,
                lat=lat,
                lng=lng,
                is_in_pool=avail.is_in_pool,
                aueg_status=aueg_status,
                aueg_remaining_months=remaining,
                current_assignment_id=cur_aid,
                current_assignment_title=cur_title,
            )
        )

    await db.commit()
    return MapDataResponse(assignments=assignment_outs, workers=worker_outs)
