"""Tips: recorded on the bill, distributed by a visible rule, never invented.

FlintPlate does not charge money. A guest states a tip when handing the bill to
the till; the till confirms what it actually collected. Distribution happens
afterwards on confirmed, paid tips only, and every share is written with the
minutes and the rule it came from.

Two rules per venue. `direct` gives a tip to the person who served that bill.
`pool_hours` collects the period into one pot and splits it by the minutes
people actually worked, with an optional kitchen share. Tips nobody can be
assigned to never disappear: they fall back into the pot and say so.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator
from sqlalchemy import and_, select, true
from sqlalchemy.ext.asyncio import AsyncSession

from app.gastro import service as svc
from app.gastro.models import Membership, Order, Shift, TipRun, TipShare, Venue
from app.gastro.payer_tip_models import PayerTipEntry, TipRunSource
from app.gastro.payer_tip_service import available_tips
from app.gastro.payment_service import digest
from app.gastro.router import DB, Actor, private_response
from app.gastro.schemas import OrderRead, TipInput
from app.gastro.station_service import station_names, work_kinds
from app.gastro.tip_models import TipTimeAttribution
from app.users.models import User
from app.worker.time_models import TimeEntry

router = APIRouter(dependencies=[Depends(private_response)])

SERVICE_POOL = "service"
KITCHEN_POOL = "kitchen"
DIRECT_POOL = "direkt"


class Period(BaseModel):
    model_config = ConfigDict(extra="forbid")
    period_start: date
    period_end: date

    @model_validator(mode="after")
    def sane_period(self) -> Period:
        if self.period_end < self.period_start:
            raise ValueError("Das Ende darf nicht vor dem Beginn liegen.")
        if (self.period_end - self.period_start).days > 92:
            raise ValueError("Ein Zeitraum von höchstens 92 Tagen ist zulässig.")
        return self


class RunInput(Period):
    note: str = Field(default="", max_length=300)


class ShareRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    worker_id: uuid.UUID
    full_name: str = ""
    pool: str
    minutes: int
    share_cents: int
    reason: str


class Distribution(BaseModel):
    period_start: date
    period_end: date
    mode: str
    kitchen_bps: int
    total_cents: int
    orders: int
    shares: list[ShareRead]
    notes: list[str]
    allocated_cents: int = 0
    open_cents: int = 0
    allocated_order_ids: list[uuid.UUID] = Field(default_factory=list, exclude=True)
    payer_tips: int = 0
    allocated_payer_tip_ids: list[uuid.UUID] = Field(default_factory=list, exclude=True)


class RunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    period_start: date
    period_end: date
    mode: str
    kitchen_bps: int
    total_cents: int
    orders: int
    note: str
    created_at: datetime
    shares: list[ShareRead] = []
    payer_tips: int = 0


class TimeAttributionRead(BaseModel):
    entry_id: uuid.UUID
    shift_id: uuid.UUID
    worker_id: uuid.UUID
    full_name: str
    starts_at: datetime
    ends_at: datetime
    station: str
    minutes: int
    attributed: bool


def split(total: int, weights: dict[uuid.UUID, int]) -> dict[uuid.UUID, int]:
    """Largest remainder, so the shares add up to the pot exactly."""
    overall = sum(weights.values())
    if total <= 0 or overall <= 0:
        return {key: 0 for key in weights}
    base = {key: total * value // overall for key, value in weights.items()}
    rest = total - sum(base.values())
    ranked = sorted(weights, key=lambda key: (-((total * weights[key]) % overall), str(key)))
    for key in ranked[:rest]:
        base[key] += 1
    return base


async def window(venue: Venue, data: Period) -> tuple[datetime, datetime]:
    zone = ZoneInfo(venue.timezone)
    start = datetime.combine(data.period_start, time.min, zone)
    end = datetime.combine(data.period_end + timedelta(days=1), time.min, zone)
    return start.astimezone(UTC), end.astimezone(UTC)


async def open_tips(
    db: AsyncSession, venue: Venue, data: Period, *, lock: bool = False
) -> list[Order]:
    start, end = await window(venue, data)
    query = (
        select(Order)
        .where(
            Order.venue_id == venue.id,
            Order.tip_cents > Order.tip_refunded_cents,
            Order.tip_run_id.is_(None),
            Order.paid_at.is_not(None),
            Order.paid_at >= start,
            Order.paid_at < end,
        )
        .order_by(Order.id)
        .execution_options(populate_existing=True)
    )
    if lock:
        query = query.with_for_update()
    return [order for order in (await db.execute(query)).scalars() if available_tip_cents(order)]


def available_tip_cents(order: Order) -> int:
    # Approval reserves the selected tip for its owner; it must not be paid to
    # staff while the compensating refund is still outstanding.
    if any(unit.kind == "tip" for unit in order.cancellation_units):
        return 0
    return order.tip_cents - order.tip_refunded_cents


def as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def time_hashes(entry: TimeEntry, shift: Shift) -> tuple[str, str]:
    """A corrected entry or changed shift needs renewed explicit attribution."""
    entry_values = [
        str(entry.worker_id),
        str(entry.tenant_id),
        str(entry.assignment_id),
        as_utc(entry.clock_in).isoformat(),
        as_utc(entry.clock_out).isoformat() if entry.clock_out else None,
        entry.break_minutes,
        entry.status,
    ]
    shift_values = [
        str(shift.worker_id),
        str(shift.venue_id),
        as_utc(shift.starts_at).isoformat(),
        as_utc(shift.ends_at).isoformat(),
        shift.station,
        shift.status,
    ]
    return (
        hashlib.sha256(json.dumps(entry_values).encode()).hexdigest(),
        hashlib.sha256(json.dumps(shift_values).encode()).hexdigest(),
    )


def attributed_minutes(entry: TimeEntry, shift: Shift, start: datetime, end: datetime) -> int:
    """Partition approved net minutes across actual shift/period overlap.

    Payroll stores a total pause, not pause intervals. Allocate that total
    proportionally. Cumulative integer boundaries conserve minutes when a time
    entry is split at midnight or across several non-overlapping shifts.
    """
    if entry.clock_out is None or entry.status != "approved":
        return 0
    clock_in, clock_out = as_utc(entry.clock_in), as_utc(entry.clock_out)
    lower = max(clock_in, as_utc(shift.starts_at), as_utc(start))
    upper = min(clock_out, as_utc(shift.ends_at), as_utc(end))
    duration = (clock_out - clock_in) // timedelta(microseconds=1)
    if lower >= upper or duration <= 0:
        return 0
    net = entry.net_minutes or 0
    before = (lower - clock_in) // timedelta(microseconds=1)
    after = (upper - clock_in) // timedelta(microseconds=1)
    return net * after // duration - net * before // duration


def time_attribution_read(
    entry: TimeEntry,
    shift: Shift,
    name: str | None,
    start: datetime,
    end: datetime,
    linked: bool,
    station_label: str | None = None,
) -> TimeAttributionRead:
    return TimeAttributionRead(
        entry_id=entry.id,
        shift_id=shift.id,
        worker_id=entry.worker_id,
        full_name=name or "Teammitglied",
        starts_at=max(as_utc(entry.clock_in), as_utc(shift.starts_at), as_utc(start)),
        ends_at=min(as_utc(entry.clock_out or entry.clock_in), as_utc(shift.ends_at), as_utc(end)),
        station=station_label or shift.station,
        minutes=attributed_minutes(entry, shift, start, end),
        attributed=linked,
    )


@router.get(
    "/venues/{venue_id}/tips/time-attributions",
    response_model=list[TimeAttributionRead],
    status_code=200,
    summary="Freigegebene Arbeitszeiten passenden Diensten zuordnen",
)
async def time_attributions(
    venue_id: uuid.UUID, period_start: date, period_end: date, user: Actor, db: DB
) -> list[TimeAttributionRead]:
    venue, _ = await svc.venue_access(db, user, venue_id, svc.MANAGERS)
    if period_end < period_start or (period_end - period_start).days > 92:
        raise HTTPException(422, "Ein Zeitraum von höchstens 92 Tagen ist erforderlich.")
    start, end = await window(venue, Period(period_start=period_start, period_end=period_end))
    rows = (
        await db.execute(
            select(TimeEntry, Shift, User.full_name, TipTimeAttribution)
            .join(Shift, Shift.worker_id == TimeEntry.worker_id)
            .join(User, User.id == TimeEntry.worker_id)
            .outerjoin(
                TipTimeAttribution,
                and_(
                    TipTimeAttribution.entry_id == TimeEntry.id,
                    TipTimeAttribution.shift_id == Shift.id,
                ),
            )
            .where(
                TimeEntry.tenant_id == venue.tenant_id,
                TimeEntry.status == "approved",
                TimeEntry.clock_in < end,
                TimeEntry.clock_out > start,
                Shift.venue_id == venue.id,
                Shift.status == "published",
                Shift.starts_at < end,
                Shift.ends_at > start,
                Shift.starts_at < TimeEntry.clock_out,
                Shift.ends_at > TimeEntry.clock_in,
                User.tenant_id == venue.tenant_id,
            )
            .order_by(TimeEntry.clock_in, TimeEntry.id, Shift.starts_at)
        )
    ).all()
    names = await station_names(db, venue_id, (shift.station for _, shift, _, _ in rows))
    return [
        time_attribution_read(
            entry,
            shift,
            name,
            start,
            end,
            linked is not None
            and time_hashes(entry, shift) == (linked.entry_hash, linked.shift_hash),
            station_label=names[shift.station],
        )
        for entry, shift, name, linked in rows
    ]


@router.put(
    "/venues/{venue_id}/tips/time-attributions/{entry_id}/{shift_id}",
    response_model=TimeAttributionRead,
    status_code=200,
    summary="Freigegebene Arbeitszeit ausdrücklich einem Dienst zuordnen",
)
async def attribute_time(
    venue_id: uuid.UUID, entry_id: uuid.UUID, shift_id: uuid.UUID, user: Actor, db: DB
) -> TimeAttributionRead:
    venue, _ = await svc.venue_access(db, user, venue_id, svc.MANAGERS, lock=True)
    shift = (
        await db.execute(select(Shift).where(Shift.id == shift_id, Shift.venue_id == venue.id))
    ).scalar_one_or_none()
    if shift is None:
        raise HTTPException(404, "Dienst nicht gefunden.")
    # Serialize this person's attribution across venues and distinct time entries.
    person = (
        await db.execute(
            select(User)
            .where(User.id == shift.worker_id, User.tenant_id == venue.tenant_id)
            .with_for_update(key_share=True)
        )
    ).scalar_one_or_none()
    entry = (
        await db.execute(
            select(TimeEntry)
            .where(
                TimeEntry.id == entry_id,
                TimeEntry.worker_id == shift.worker_id,
                TimeEntry.tenant_id == venue.tenant_id,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if person is None or entry is None:
        raise HTTPException(404, "Passende Arbeitszeit nicht gefunden.")
    if entry.status != "approved" or entry.clock_out is None or shift.status != "published":
        raise HTTPException(
            409, "Nur freigegebene Arbeitszeiten und veröffentlichte Dienste zählen."
        )
    start = max(as_utc(entry.clock_in), as_utc(shift.starts_at))
    end = min(as_utc(entry.clock_out), as_utc(shift.ends_at))
    if start >= end:
        raise HTTPException(422, "Arbeitszeit und Dienst überschneiden sich nicht.")
    existing = (
        await db.execute(
            select(TipTimeAttribution).where(
                TipTimeAttribution.entry_id == entry.id, TipTimeAttribution.shift_id == shift.id
            )
        )
    ).scalar_one_or_none()
    names = await station_names(db, venue_id, [shift.station])
    entry_hash, shift_hash = time_hashes(entry, shift)
    if existing is not None and (existing.entry_hash, existing.shift_hash) == (
        entry_hash,
        shift_hash,
    ):
        return time_attribution_read(
            entry, shift, person.full_name, start, end, True, station_label=names[shift.station]
        )
    overlaps = (
        await db.execute(
            select(TimeEntry, Shift)
            .join(TipTimeAttribution, TipTimeAttribution.entry_id == TimeEntry.id)
            .join(Shift, Shift.id == TipTimeAttribution.shift_id)
            .where(
                TimeEntry.worker_id == entry.worker_id,
                TimeEntry.tenant_id == venue.tenant_id,
                TimeEntry.clock_in < end,
                TimeEntry.clock_out > start,
                Shift.starts_at < end,
                Shift.ends_at > start,
                TipTimeAttribution.id != existing.id if existing else true(),
            )
        )
    ).all()
    for other_entry, other_shift in overlaps:
        if other_entry.clock_out is not None and max(
            start, as_utc(other_entry.clock_in), as_utc(other_shift.starts_at)
        ) < min(end, as_utc(other_entry.clock_out), as_utc(other_shift.ends_at)):
            raise HTTPException(
                409, "Diese Arbeitszeit ist bereits einem überlappenden Dienst zugeordnet."
            )
    link = existing or TipTimeAttribution(entry_id=entry.id, shift_id=shift.id, actor_id=user.id)
    link.entry_hash = entry_hash
    link.shift_hash = shift_hash
    link.actor_id = user.id
    db.add(link)
    await db.flush()
    svc.event(
        db,
        venue.id,
        "tips.time_attributed",
        link.id,
        {"entry_id": str(entry.id), "shift_id": str(shift.id), "worker_id": str(entry.worker_id)},
        user.id,
    )
    return time_attribution_read(
        entry, shift, person.full_name, start, end, True, station_label=names[shift.station]
    )


@dataclass
class WorkWeights:
    minutes: dict[uuid.UUID, int]
    groups: dict[str, dict[uuid.UUID, int]]
    names: dict[uuid.UUID, str]


async def worked_minutes(db: AsyncSession, venue: Venue, data: Period) -> WorkWeights:
    """Only approved entries explicitly attributed to this venue's shifts count."""
    start, end = await window(venue, data)
    rows = (
        await db.execute(
            select(TimeEntry, Shift, User.full_name, TipTimeAttribution)
            .join(TipTimeAttribution, TipTimeAttribution.entry_id == TimeEntry.id)
            .join(Shift, Shift.id == TipTimeAttribution.shift_id)
            .join(User, User.id == Shift.worker_id)
            .where(
                Shift.venue_id == venue.id,
                Shift.status == "published",
                Shift.starts_at < end,
                Shift.ends_at > start,
                TimeEntry.tenant_id == venue.tenant_id,
                TimeEntry.worker_id == Shift.worker_id,
                User.tenant_id == venue.tenant_id,
                TimeEntry.status == "approved",
                TimeEntry.clock_in < end,
                TimeEntry.clock_out > start,
            )
        )
    ).all()
    minutes: dict[uuid.UUID, int] = {}
    groups: dict[str, dict[uuid.UUID, int]] = {SERVICE_POOL: {}, KITCHEN_POOL: {}}
    names: dict[uuid.UUID, str] = {}
    kinds = await work_kinds(db, venue.id, (shift.station for _, shift, _, _ in rows))
    for entry, shift, name, attribution in rows:
        if time_hashes(entry, shift) != (attribution.entry_hash, attribution.shift_hash):
            continue
        net = attributed_minutes(entry, shift, start, end)
        if not net:
            continue
        names[shift.worker_id] = name or "Teammitglied"
        kind = kinds[shift.station]
        pool = KITCHEN_POOL if kind == "kitchen" else SERVICE_POOL
        group = groups[pool]
        group[shift.worker_id] = group.get(shift.worker_id, 0) + net
        minutes[shift.worker_id] = minutes.get(shift.worker_id, 0) + net
    return WorkWeights(minutes, groups, names)


@dataclass
class DistributionSource:
    id: uuid.UUID
    kind: str
    amount: int
    recipient_id: uuid.UUID | None


async def distribute(
    db: AsyncSession,
    venue: Venue,
    data: Period,
    *,
    orders: list[Order] | None = None,
    payer_tips: list[tuple[PayerTipEntry, int]] | None = None,
) -> Distribution:
    if orders is None:
        orders = await open_tips(db, venue, data)
    if payer_tips is None:
        start, end = await window(venue, data)
        payer_tips = await available_tips(db, venue.id, start, end)
    sources = [
        DistributionSource(
            order.id, "order", available_tip_cents(order), order.tip_recipient_id or order.actor_id
        )
        for order in orders
    ]
    sources.extend(
        DistributionSource(entry.id, "payer_tip", cents, entry.recipient_id or entry.actor_id)
        for entry, cents in payer_tips
    )
    total = sum(source.amount for source in sources)
    notes: list[str] = []
    work = await worked_minutes(db, venue, data)
    minutes, names = work.minutes, work.names
    amounts: dict[uuid.UUID, int] = {}
    reasons: dict[uuid.UUID, str] = {}
    pools: dict[uuid.UUID, set[str]] = {}
    allocated_ids: list[uuid.UUID] = []
    pooled_sources: list[DistributionSource] = []
    allocated_payer_ids: list[uuid.UUID] = []

    if venue.tip_mode == "direct":
        unassigned = 0
        for source in sources:
            source_cents = source.amount
            recipient = source.recipient_id
            if recipient is None:
                unassigned += source_cents
                pooled_sources.append(source)
                continue
            amounts[recipient] = amounts.get(recipient, 0) + source_cents
            reasons[recipient] = "Direkt aus den selbst abgeschlossenen Bons."
            pools.setdefault(recipient, set()).add(DIRECT_POOL)
            (allocated_ids if source.kind == "order" else allocated_payer_ids).append(source.id)
        if unassigned:
            notes.append(
                f"{unassigned / 100:.2f} € stammen aus Bestellungen ohne erfasste Bedienung "
                "und werden nach geleisteten Stunden verteilt."
            )
        pot = unassigned
    else:
        pot = total
        pooled_sources = sources

    if pot:
        if not minutes:
            notes.append(
                "Für diesen Zeitraum gibt es keine freigegebenen, zugeordneten Arbeitszeiten; "
                "der Betrag bleibt offen und kann nicht verteilt werden."
            )
        else:
            kitchen = work.groups[KITCHEN_POOL]
            service = work.groups[SERVICE_POOL]
            kitchen_pot = pot * venue.tip_kitchen_bps // 10000
            if kitchen_pot and not any(kitchen.values()):
                notes.append(
                    "Kein Küchenanteil verteilbar: keine erfasste Küchenzeit. "
                    "Der Anteil bleibt im Servicetopf."
                )
                kitchen_pot = 0
            service_pot = pot - kitchen_pot
            # Keep each source whole. A missing service group must not silently
            # consume its residual while a kitchen share is written.
            if service_pot and not service:
                notes.append(
                    "Keine zugeordnete Servicezeit: der gesamte gemeinsame Topf bleibt offen."
                )
            else:
                for pool, group, group_pot in (
                    (KITCHEN_POOL, kitchen, kitchen_pot),
                    (SERVICE_POOL, service, service_pot),
                ):
                    for worker, share in split(group_pot, group).items():
                        if not share:
                            continue
                        amounts[worker] = amounts.get(worker, 0) + share
                        pools.setdefault(worker, set()).add(pool)
                        reasons[worker] = (
                            f"{minutes.get(worker, 0)} freigegebene, dienstbezogene Minuten."
                        )
                allocated_ids.extend(
                    source.id for source in pooled_sources if source.kind == "order"
                )
                allocated_payer_ids.extend(
                    source.id for source in pooled_sources if source.kind == "payer_tip"
                )

    allocated = sum(amounts.values())
    if allocated < total:
        notes.append(f"{(total - allocated) / 100:.2f} € bleiben für einen späteren Lauf offen.")
    if minutes:
        notes.append(
            "Pausen werden nach dem freigegebenen Gesamtwert zeitanteilig auf Dienste und Zeitraum verteilt."
        )

    shares = [
        ShareRead(
            worker_id=worker,
            full_name=names.get(worker, "Teammitglied"),
            pool=next(iter(pools[worker])) if len(pools[worker]) == 1 else "gemischt",
            minutes=minutes.get(worker, 0),
            share_cents=amount,
            reason=reasons.get(worker, ""),
        )
        for worker, amount in amounts.items()
    ]
    shares.sort(key=lambda row: (-row.share_cents, row.full_name))
    if not sources:
        notes.append("In diesem Zeitraum ist kein bestätigtes Trinkgeld erfasst.")
    return Distribution(
        period_start=data.period_start,
        period_end=data.period_end,
        mode=venue.tip_mode,
        kitchen_bps=venue.tip_kitchen_bps,
        total_cents=total,
        orders=len(orders),
        shares=shares,
        notes=notes,
        allocated_cents=allocated,
        open_cents=total - allocated,
        allocated_order_ids=allocated_ids,
        payer_tips=len(payer_tips),
        allocated_payer_tip_ids=allocated_payer_ids,
    )


@router.post(
    "/venues/{venue_id}/orders/{order_id}/tip",
    response_model=OrderRead,
    status_code=200,
    summary="Trinkgeld auf einem Bon festhalten",
)
async def set_tip(
    venue_id: uuid.UUID, order_id: uuid.UUID, data: TipInput, user: Actor, db: DB
) -> Order:
    await svc.venue_access(db, user, venue_id, svc.SERVICE)
    order = await svc.order_for_venue(db, venue_id, order_id, lock=True)
    svc.check_version(order.version, data.version)
    if order.cancellation_units:
        raise HTTPException(
            409,
            "Der Originalbon hat Stornobelege; Trinkgeld und begünstigte Person bleiben unverändert.",
        )
    if order.paid_at or order.pos_requested or order.status not in svc.ACTIVE_ORDER_STATES:
        raise HTTPException(
            409, "Der Bon ist bereits an der Kasse oder abgeschlossen; Trinkgeld ist gesperrt."
        )
    if data.recipient_id is not None:
        member = (
            await db.execute(
                select(Membership.id).where(
                    Membership.venue_id == venue_id,
                    Membership.user_id == data.recipient_id,
                    Membership.active.is_(True),
                )
            )
        ).first()
        if not member:
            raise HTTPException(
                404, "Die begünstigte Person arbeitet nicht in dieser Betriebsstätte."
            )
    order.tip_cents = data.tip_cents
    order.tip_recipient_id = data.recipient_id
    order.version += 1
    svc.event(
        db,
        venue_id,
        "order.tip_recorded",
        order.id,
        {
            "tip_cents": data.tip_cents,
            "recipient_id": str(data.recipient_id) if data.recipient_id else None,
        },
        user.id,
    )
    await db.flush()
    return order


@router.post(
    "/venues/{venue_id}/tips/preview",
    response_model=Distribution,
    status_code=200,
    summary="Vorschau der Trinkgeldverteilung, ohne etwas festzuschreiben",
)
async def preview(venue_id: uuid.UUID, data: Period, user: Actor, db: DB) -> Distribution:
    venue, _ = await svc.venue_access(db, user, venue_id, svc.MANAGERS)
    return await distribute(db, venue, data)


@router.post(
    "/venues/{venue_id}/tips/runs",
    response_model=RunRead,
    status_code=201,
    summary="Verteilung verbindlich festschreiben",
)
async def confirm(venue_id: uuid.UUID, data: RunInput, user: Actor, db: DB) -> RunRead:
    venue, _ = await svc.venue_access(db, user, venue_id, svc.MANAGERS, lock=True)
    orders = await open_tips(db, venue, data, lock=True)
    start, end = await window(venue, data)
    payer_tips = await available_tips(db, venue.id, start, end)
    if not orders and not payer_tips:
        raise HTTPException(409, "In diesem Zeitraum ist kein bestätigtes Trinkgeld erfasst.")
    # Use this exact locked source set; a payment arriving during calculation
    # belongs to the next run, never to an unmarked second query result.
    result = await distribute(db, venue, data, orders=orders, payer_tips=payer_tips)
    if not any(share.share_cents for share in result.shares):
        raise HTTPException(409, "Es gibt niemanden, dem dieser Betrag zugeordnet werden kann.")
    run = TipRun(
        venue_id=venue_id,
        period_start=data.period_start,
        period_end=data.period_end,
        mode=result.mode,
        kitchen_bps=result.kitchen_bps,
        total_cents=sum(share.share_cents for share in result.shares),
        orders=len(result.allocated_order_ids),
        actor_id=user.id,
        note=data.note,
    )
    db.add(run)
    await db.flush()
    for share in result.shares:
        db.add(
            TipShare(
                run_id=run.id,
                worker_id=share.worker_id,
                pool=share.pool,
                minutes=share.minutes,
                share_cents=share.share_cents,
                reason=share.reason,
            )
        )
    allocated_ids = set(result.allocated_order_ids)
    for order in orders:
        if order.id in allocated_ids:
            order.tip_run_id = run.id
            snapshot: dict[str, JsonValue] = {
                "order_id": str(order.id),
                "timezone": venue.timezone,
                "tip_cents": order.tip_cents,
                "refunded_cents": order.tip_refunded_cents,
                "amount_cents": available_tip_cents(order),
            }
            db.add(
                TipRunSource(
                    venue_id=venue.id,
                    run_id=run.id,
                    kind="order",
                    order_id=order.id,
                    amount_cents=available_tip_cents(order),
                    source_hash=digest(snapshot),
                    source_snapshot=snapshot,
                )
            )
    for payer_tip, cents in payer_tips:
        if payer_tip.id in result.allocated_payer_tip_ids:
            tip_snapshot: dict[str, JsonValue] = {
                "payer_tip_id": str(payer_tip.id),
                "timezone": venue.timezone,
                "amount_cents": cents,
                "received_cents": payer_tip.amount_cents,
                "payment_group_id": str(payer_tip.payment_group_id),
            }
            db.add(
                TipRunSource(
                    venue_id=venue.id,
                    run_id=run.id,
                    kind="payer_tip",
                    payer_tip_id=payer_tip.id,
                    amount_cents=cents,
                    source_hash=digest(tip_snapshot),
                    source_snapshot=tip_snapshot,
                )
            )
    svc.event(
        db,
        venue_id,
        "tips.distributed",
        run.id,
        {
            "period": [data.period_start.isoformat(), data.period_end.isoformat()],
            "mode": result.mode,
            "total_cents": run.total_cents,
            "orders": run.orders,
            "order_ids": [str(order_id) for order_id in result.allocated_order_ids],
            "open_cents": result.open_cents,
            "payer_tip_ids": [str(source_id) for source_id in result.allocated_payer_tip_ids],
            "shares": [
                {"worker_id": str(s.worker_id), "share_cents": s.share_cents}
                for s in result.shares
                if s.share_cents
            ],
        },
        user.id,
    )
    await db.flush()
    return RunRead(
        id=run.id,
        period_start=run.period_start,
        period_end=run.period_end,
        mode=run.mode,
        kitchen_bps=run.kitchen_bps,
        total_cents=run.total_cents,
        orders=run.orders,
        note=run.note,
        created_at=run.created_at,
        shares=result.shares,
        payer_tips=len(result.allocated_payer_tip_ids),
    )


@router.get(
    "/venues/{venue_id}/tips/runs",
    response_model=list[RunRead],
    status_code=200,
    summary="Bisherige Verteilungen mit ihren Anteilen",
)
async def runs(venue_id: uuid.UUID, user: Actor, db: DB) -> list[RunRead]:
    await svc.venue_access(db, user, venue_id, svc.MANAGERS)
    rows = (
        (
            await db.execute(
                select(TipRun)
                .where(TipRun.venue_id == venue_id)
                .order_by(TipRun.period_start.desc(), TipRun.created_at.desc(), TipRun.id)
                .limit(50)
            )
        )
        .scalars()
        .all()
    )
    if not rows:
        return []
    shares = (
        await db.execute(
            select(TipShare, User.full_name)
            .join(User, User.id == TipShare.worker_id)
            .where(TipShare.run_id.in_([row.id for row in rows]))
            .order_by(TipShare.share_cents.desc())
        )
    ).all()
    grouped: dict[uuid.UUID, list[ShareRead]] = {}
    for share, name in shares:
        grouped.setdefault(share.run_id, []).append(
            ShareRead(
                worker_id=share.worker_id,
                full_name=name or "Teammitglied",
                pool=share.pool,
                minutes=share.minutes,
                share_cents=share.share_cents,
                reason=share.reason,
            )
        )
    source_counts: dict[uuid.UUID, int] = {}
    for run_id in (
        await db.execute(
            select(TipRunSource.run_id).where(
                TipRunSource.run_id.in_([row.id for row in rows]), TipRunSource.kind == "payer_tip"
            )
        )
    ).scalars():
        source_counts[run_id] = source_counts.get(run_id, 0) + 1
    return [
        RunRead(
            id=row.id,
            period_start=row.period_start,
            period_end=row.period_end,
            mode=row.mode,
            kitchen_bps=row.kitchen_bps,
            total_cents=row.total_cents,
            orders=row.orders,
            note=row.note,
            created_at=row.created_at,
            shares=grouped.get(row.id, []),
            payer_tips=source_counts.get(row.id, 0),
        )
        for row in rows
    ]
