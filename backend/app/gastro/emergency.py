from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.gastro import service as svc
from app.gastro.models import Availability, Emergency, EmergencyOffer, Membership, Shift, Venue
from app.gastro.router import (
    DB,
    Actor,
    check_shift_person,
    create_shift,
    private_response,
    shift_status,
)
from app.gastro.schemas import (
    IntervalInput,
    MessageRead,
    ReadModel,
    ShiftInput,
    ShiftState,
    VersionInput,
)
from app.users.models import User
from app.worker.models import WorkerSettings

router = APIRouter(dependencies=[Depends(private_response)])


class SkillsInput(BaseModel):
    stations: list[Literal["service", "kitchen", "bar", "activities"]] = Field(max_length=4)
    competence: int = Field(ge=1, le=5)


class SkillsRead(SkillsInput):
    user_id: uuid.UUID
    emergency_opt_in: bool


class OptIn(BaseModel):
    enabled: bool


class AvailabilityRead(IntervalInput, ReadModel):
    worker_id: uuid.UUID


class RequestInput(BaseModel):
    request_key: uuid.UUID
    shift_id: uuid.UUID
    mode: Literal["broadcast", "sequential"] = "sequential"
    reason: str = Field(min_length=3, max_length=500)
    timeout_minutes: int = Field(default=10, ge=1, le=60)
    competence_weight: int = Field(default=50, ge=0, le=100)
    fairness_weight: int = Field(default=30, ge=0, le=100)
    capacity_weight: int = Field(default=20, ge=0, le=100)


class Candidate(BaseModel):
    worker_id: uuid.UUID
    name: str
    eligible: bool
    reasons: list[str]
    competence: int
    planned_minutes: int
    weekly_target_minutes: int | None
    prior_requests: int
    estimated_base_cents: int | None
    score: float


class EmergencyRead(ReadModel):
    shift_id: uuid.UUID
    replacement_shift_id: uuid.UUID | None
    mode: str
    reason: str
    status: str
    timeout_minutes: int
    version: int
    created_at: datetime


class OfferRead(ReadModel):
    emergency_id: uuid.UUID
    status: str
    expires_at: datetime | None
    station: str
    starts_at: datetime
    ends_at: datetime
    break_minutes: int
    venue_name: str


class Answer(BaseModel):
    accept: bool


def station_kind(value: str) -> str | None:
    value = value.lower()
    if any(w in value for w in ["küche", "kitchen", "koch"]):
        return "kitchen"
    if "bar" in value:
        return "bar"
    if any(w in value for w in ["boot", "aktiv", "activity", "bowling", "billard"]):
        return "activities"
    if any(w in value for w in ["service", "terrasse", "kellner", "bedienung"]):
        return "service"
    return None


async def member(db: DB, venue_id: uuid.UUID, user_id: uuid.UUID) -> Membership:
    row = (
        await db.execute(
            select(Membership)
            .join(User, User.id == Membership.user_id)
            .join(Venue, Venue.id == Membership.venue_id)
            .where(
                Membership.venue_id == venue_id,
                Membership.user_id == user_id,
                Membership.active.is_(True),
                User.tenant_id == Venue.tenant_id,
                User.is_active.is_(True),
            )
            .with_for_update(of=Membership)
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, "Aktive Mitgliedschaft nicht gefunden.")
    return row


@router.get(
    "/venues/{venue_id}/staff-skills",
    response_model=list[SkillsRead],
    status_code=200,
    summary="Stationsqualifikation und freiwillige Vertretungsbereitschaft",
)
async def skills(venue_id: uuid.UUID, user: Actor, db: DB) -> list[Membership]:
    await svc.venue_access(db, user, venue_id, svc.MANAGERS)
    return list(
        (
            await db.execute(
                select(Membership).where(
                    Membership.venue_id == venue_id, Membership.active.is_(True)
                )
            )
        ).scalars()
    )


@router.get(
    "/venues/{venue_id}/my-emergency-opt-in",
    response_model=OptIn,
    status_code=200,
    summary="Eigene freiwillige Vertretungsbereitschaft lesen",
)
async def read_opt_in(venue_id: uuid.UUID, user: Actor, db: DB) -> OptIn:
    await svc.venue_access(db, user, venue_id)
    row = await member(db, venue_id, user.id)
    return OptIn(enabled=row.emergency_opt_in)


@router.put(
    "/venues/{venue_id}/staff-skills/{worker_id}",
    response_model=SkillsRead,
    status_code=200,
    summary="Leitung dokumentiert Stationsqualifikation und Erfahrungsstufe",
)
async def update_skills(
    venue_id: uuid.UUID, worker_id: uuid.UUID, data: SkillsInput, user: Actor, db: DB
) -> Membership:
    await svc.venue_access(db, user, venue_id, svc.MANAGERS, lock=True)
    row = await member(db, venue_id, worker_id)
    row.stations = sorted(set(data.stations))
    row.competence = data.competence
    svc.event(
        db,
        venue_id,
        "staff.qualification_changed",
        row.id,
        data.model_dump(mode="json") | {"worker_id": str(worker_id)},
        user.id,
    )
    return row


@router.put(
    "/venues/{venue_id}/my-emergency-opt-in",
    response_model=OptIn,
    status_code=200,
    summary="Eigene freiwillige Bereitschaft zu Vertretungsanfragen setzen",
)
async def opt_in(venue_id: uuid.UUID, data: OptIn, user: Actor, db: DB) -> OptIn:
    await svc.venue_access(db, user, venue_id, lock=True)
    row = await member(db, venue_id, user.id)
    row.emergency_opt_in = data.enabled
    svc.event(db, venue_id, "staff.emergency_opt_in", row.id, {"enabled": data.enabled}, user.id)
    return data


@router.get(
    "/venues/{venue_id}/my-availability",
    response_model=list[AvailabilityRead],
    status_code=200,
    summary="Eigene angebotene Verfügbarkeit",
)
async def availability(venue_id: uuid.UUID, user: Actor, db: DB) -> list[Availability]:
    await svc.venue_access(db, user, venue_id)
    return list(
        (
            await db.execute(
                select(Availability)
                .where(
                    Availability.venue_id == venue_id,
                    Availability.worker_id == user.id,
                    Availability.ends_at > datetime.now(UTC),
                )
                .order_by(Availability.starts_at)
            )
        ).scalars()
    )


@router.post(
    "/venues/{venue_id}/my-availability",
    response_model=AvailabilityRead,
    status_code=201,
    summary="Eigenes Zeitfenster für freiwillige Vertretung anbieten",
)
async def add_availability(
    venue_id: uuid.UUID, data: IntervalInput, user: Actor, db: DB
) -> Availability:
    await svc.venue_access(db, user, venue_id, lock=True)
    if user.role != "worker":
        raise HTTPException(403, "Mitarbeiterkonto erforderlich.")
    if data.ends_at <= datetime.now(UTC):
        raise HTTPException(422, "Verfügbarkeit muss in der Zukunft liegen.")
    row = Availability(venue_id=venue_id, worker_id=user.id, **data.model_dump())
    db.add(row)
    await db.flush()
    svc.event(
        db, venue_id, "staff.availability_added", row.id, data.model_dump(mode="json"), user.id
    )
    return row


@router.delete(
    "/venues/{venue_id}/my-availability/{availability_id}",
    response_model=MessageRead,
    status_code=200,
    summary="Eigenes Verfügbarkeitsangebot zurückziehen",
)
async def remove_availability(
    venue_id: uuid.UUID, availability_id: uuid.UUID, user: Actor, db: DB
) -> MessageRead:
    await svc.venue_access(db, user, venue_id, lock=True)
    row = (
        await db.execute(
            select(Availability).where(
                Availability.id == availability_id,
                Availability.worker_id == user.id,
                Availability.venue_id == venue_id,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, "Angebot nicht gefunden.")
    await db.delete(row)
    svc.event(db, venue_id, "staff.availability_removed", availability_id, {}, user.id)
    return MessageRead(message="Verfügbarkeit zurückgezogen.")


async def target_shift(db: DB, venue_id: uuid.UUID, shift_id: uuid.UUID) -> Shift:
    row = (
        await db.execute(
            select(Shift).where(Shift.id == shift_id, Shift.venue_id == venue_id).with_for_update()
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, "Dienst nicht gefunden.")
    if row.status != "published" or row.starts_at <= datetime.now(UTC):
        raise HTTPException(
            422, "Ein veröffentlichter, noch nicht begonnener Dienst ist erforderlich."
        )
    return row


async def candidates(db: DB, venue: Venue, shift: Shift, data: RequestInput) -> list[Candidate]:
    rows = (
        await db.execute(
            select(Membership, User, WorkerSettings)
            .join(User, User.id == Membership.user_id)
            .join(WorkerSettings, WorkerSettings.user_id == User.id)
            .where(
                Membership.venue_id == venue.id,
                Membership.active.is_(True),
                User.tenant_id == venue.tenant_id,
                User.role == "worker",
                User.is_active.is_(True),
                WorkerSettings.tenant_id == venue.tenant_id,
                WorkerSettings.is_active.is_(True),
                User.id != shift.worker_id,
            )
            .order_by(User.id)
        )
    ).all()
    result = []
    start = shift.starts_at
    week = (start - timedelta(days=start.weekday())).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    from app.gastro.station_service import work_kinds

    kind = (await work_kinds(db, venue.id, [shift.station]))[shift.station]
    for membership, person, settings in rows:
        reasons = []
        if not membership.emergency_opt_in:
            reasons.append("Keine freiwillige Freigabe für Vertretungsanfragen.")
        if kind not in membership.stations:
            reasons.append("Stationsqualifikation nicht dokumentiert.")
        if settings.date_of_birth is None:
            reasons.append("Altersprüfung unvollständig.")
        window = (
            await db.execute(
                select(Availability.id).where(
                    Availability.venue_id == venue.id,
                    Availability.worker_id == person.id,
                    Availability.starts_at <= shift.starts_at,
                    Availability.ends_at >= shift.ends_at,
                )
            )
        ).first()
        if not window:
            reasons.append("Kein passendes angebotenes Zeitfenster.")
        try:
            await check_shift_person(
                db,
                venue,
                ShiftInput(
                    worker_id=person.id,
                    station=shift.station,
                    starts_at=shift.starts_at,
                    ends_at=shift.ends_at,
                    break_minutes=shift.break_minutes,
                ),
            )
        except HTTPException as exc:
            if exc.status_code in {404, 409, 422}:
                reasons.append(str(exc.detail))
            else:
                raise
        plans = (
            (
                await db.execute(
                    select(Shift).where(
                        Shift.worker_id == person.id,
                        Shift.status != "cancelled",
                        Shift.starts_at >= week,
                        Shift.starts_at < week + timedelta(days=7),
                    )
                )
            )
            .scalars()
            .all()
        )
        minutes = sum(
            int((s.ends_at - s.starts_at).total_seconds() / 60) - s.break_minutes for s in plans
        )
        count = (
            await db.execute(
                select(func.count())
                .select_from(EmergencyOffer)
                .where(
                    EmergencyOffer.worker_id == person.id,
                    EmergencyOffer.status != "queued",
                    EmergencyOffer.created_at >= datetime.now(UTC) - timedelta(days=30),
                )
            )
        ).scalar_one()
        target = settings.max_weekly_hours * 60 if settings.max_weekly_hours else None
        capacity = max(0, 1 - minutes / target) if target else 0
        score = (
            membership.competence / 5 * data.competence_weight
            + 1 / (count + 1) * data.fairness_weight
            + capacity * data.capacity_weight
        )
        net = int((shift.ends_at - shift.starts_at).total_seconds() / 60) - shift.break_minutes
        cost = (
            round(settings.hourly_rate * 100 * net / 60)
            if settings.hourly_rate is not None
            else None
        )
        result.append(
            Candidate(
                worker_id=person.id,
                name=person.full_name or "Teammitglied",
                eligible=not reasons,
                reasons=reasons,
                competence=membership.competence,
                planned_minutes=minutes,
                weekly_target_minutes=target,
                prior_requests=count,
                estimated_base_cents=cost,
                score=round(score, 2),
            )
        )
    return sorted(result, key=lambda row: (not row.eligible, -row.score, str(row.worker_id)))


@router.post(
    "/venues/{venue_id}/emergency-preview",
    response_model=list[Candidate],
    status_code=200,
    summary="Vertretung nach Eignung, Sollstunden und fairer Verteilung vergleichen",
)
async def preview(venue_id: uuid.UUID, data: RequestInput, user: Actor, db: DB) -> list[Candidate]:
    venue, _ = await svc.venue_access(db, user, venue_id, svc.MANAGERS, lock=True)
    shift = await target_shift(db, venue_id, data.shift_id)
    return await candidates(db, venue, shift, data)


async def advance(db: DB, emergency: Emergency) -> None:
    if emergency.status != "open":
        return
    now = datetime.now(UTC)
    shift = (await db.execute(select(Shift).where(Shift.id == emergency.shift_id))).scalar_one()
    offers = (
        (
            await db.execute(
                select(EmergencyOffer)
                .where(EmergencyOffer.emergency_id == emergency.id)
                .order_by(EmergencyOffer.position)
                .with_for_update()
            )
        )
        .scalars()
        .all()
    )
    for offer in offers:
        if offer.status in {"queued", "offered"}:
            ready = (
                await db.execute(
                    select(Membership.id)
                    .join(User, User.id == Membership.user_id)
                    .where(
                        Membership.venue_id == emergency.venue_id,
                        Membership.user_id == offer.worker_id,
                        Membership.active.is_(True),
                        Membership.emergency_opt_in.is_(True),
                        User.is_active.is_(True),
                    )
                )
            ).first()
            if ready is None:
                offer.status = "withdrawn"
                svc.event(
                    db, emergency.venue_id, "replacement.consent_withdrawn", offer.id, {}, None
                )
        if offer.status == "offered" and (
            offer.expires_at is None or offer.expires_at <= now or shift.starts_at <= now
        ):
            offer.status = "expired"
            svc.event(db, emergency.venue_id, "replacement.offer_expired", offer.id, {}, None)
    if shift.status != "published" or shift.starts_at <= now:
        emergency.status = "expired"
        emergency.version += 1
        for offer in offers:
            if offer.status in {"offered", "queued"}:
                offer.status = "expired"
        await db.flush()
        return
    if emergency.mode == "sequential" and any(o.status == "offered" for o in offers):
        return
    pending = [o for o in offers if o.status == "queued"]
    chosen = pending if emergency.mode == "broadcast" else pending[:1]
    for offer in chosen:
        offer.status = "offered"
        offer.expires_at = min(shift.starts_at, now + timedelta(minutes=emergency.timeout_minutes))
        svc.event(
            db,
            emergency.venue_id,
            "replacement.in_app_offered",
            offer.id,
            {"worker_id": str(offer.worker_id), "expires_at": offer.expires_at.isoformat()},
        )
    if not any(o.status in {"offered", "queued"} for o in offers):
        emergency.status = "unfilled"
        emergency.version += 1
    await db.flush()


@router.get(
    "/venues/{venue_id}/emergencies",
    response_model=list[EmergencyRead],
    status_code=200,
    summary="Aktuelle Vertretungssuchen und Antworten",
)
async def requests(venue_id: uuid.UUID, user: Actor, db: DB) -> list[Emergency]:
    await svc.venue_access(db, user, venue_id, svc.MANAGERS, lock=True)
    rows = list(
        (
            await db.execute(
                select(Emergency)
                .where(Emergency.venue_id == venue_id)
                .order_by(Emergency.created_at.desc())
                .limit(100)
            )
        ).scalars()
    )
    for row in rows:
        await advance(db, row)
    return rows


@router.post(
    "/venues/{venue_id}/emergencies",
    response_model=EmergencyRead,
    status_code=201,
    summary="Vertretungssuche als Broadcast oder hierarchische Folge starten",
)
async def start_request(venue_id: uuid.UUID, data: RequestInput, user: Actor, db: DB) -> Emergency:
    venue, _ = await svc.venue_access(db, user, venue_id, svc.MANAGERS, lock=True)
    prior = (
        await db.execute(
            select(Emergency).where(
                Emergency.venue_id == venue_id, Emergency.request_key == data.request_key
            )
        )
    ).scalar_one_or_none()
    if prior:
        if prior.request_hash != svc.digest(data):
            raise HTTPException(409, "Vorgangs-ID bereits anders verwendet.")
        return prior
    shift = await target_shift(db, venue_id, data.shift_id)
    if (
        await db.execute(
            select(Emergency.id).where(Emergency.shift_id == shift.id, Emergency.status == "open")
        )
    ).first():
        raise HTTPException(409, "Für diesen Dienst läuft bereits eine Suche.")
    ranked = await candidates(db, venue, shift, data)
    suitable = [c for c in ranked if c.eligible]
    if not suitable:
        raise HTTPException(
            422, "Keine geeignete Person mit Freigabe und Verfügbarkeit gefunden. Vorschau prüfen."
        )
    row = Emergency(
        venue_id=venue_id,
        shift_id=shift.id,
        actor_id=user.id,
        mode=data.mode,
        reason=data.reason,
        timeout_minutes=data.timeout_minutes,
        ranking=[c.model_dump(mode="json") for c in ranked],
        request_key=data.request_key,
        request_hash=svc.digest(data),
    )
    db.add(row)
    await db.flush()
    for position, candidate in enumerate(suitable):
        db.add(
            EmergencyOffer(emergency_id=row.id, worker_id=candidate.worker_id, position=position)
        )
    await db.flush()
    await advance(db, row)
    svc.event(
        db,
        venue_id,
        "replacement.started",
        row.id,
        {
            "mode": data.mode,
            "reason": data.reason,
            "shift_id": str(shift.id),
            "ranking": [entry for entry in row.ranking],
        },
        user.id,
    )
    return row


@router.post(
    "/venues/{venue_id}/emergencies/{request_id}/cancel",
    response_model=EmergencyRead,
    status_code=200,
    summary="Offene Vertretungssuche zurückziehen",
)
async def cancel_request(
    venue_id: uuid.UUID, request_id: uuid.UUID, data: VersionInput, user: Actor, db: DB
) -> Emergency:
    await svc.venue_access(db, user, venue_id, svc.MANAGERS, lock=True)
    row = (
        await db.execute(
            select(Emergency)
            .where(Emergency.id == request_id, Emergency.venue_id == venue_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, "Suche nicht gefunden.")
    svc.check_version(row.version, data.version)
    if row.status != "open":
        raise HTTPException(409, "Suche nicht mehr offen.")
    row.status = "cancelled"
    row.version += 1
    offers = (
        await db.execute(select(EmergencyOffer).where(EmergencyOffer.emergency_id == row.id))
    ).scalars()
    for offer in offers:
        if offer.status in {"queued", "offered"}:
            offer.status = "cancelled"
    svc.event(db, venue_id, "replacement.cancelled", row.id, {}, user.id)
    return row


@router.get(
    "/venues/{venue_id}/my-replacement-offers",
    response_model=list[OfferRead],
    status_code=200,
    summary="Nur eigene aktuell angebotene Vertretungen",
)
async def my_offers(venue_id: uuid.UUID, user: Actor, db: DB) -> list[OfferRead]:
    venue, _ = await svc.venue_access(db, user, venue_id, lock=True)
    emergencies = (
        (
            await db.execute(
                select(Emergency).where(Emergency.venue_id == venue_id, Emergency.status == "open")
            )
        )
        .scalars()
        .all()
    )
    for emergency in emergencies:
        await advance(db, emergency)
    rows = (
        await db.execute(
            select(EmergencyOffer, Shift)
            .join(Emergency, Emergency.id == EmergencyOffer.emergency_id)
            .join(Shift, Shift.id == Emergency.shift_id)
            .where(
                Emergency.venue_id == venue_id,
                Emergency.status == "open",
                EmergencyOffer.worker_id == user.id,
                EmergencyOffer.status == "offered",
            )
        )
    ).all()
    from app.gastro.station_service import station_names

    names = await station_names(db, venue_id, (shift.station for _, shift in rows))
    return [
        OfferRead(
            id=o.id,
            emergency_id=o.emergency_id,
            status=o.status,
            expires_at=o.expires_at,
            station=names[s.station],
            starts_at=s.starts_at,
            ends_at=s.ends_at,
            break_minutes=s.break_minutes,
            venue_name=venue.name,
        )
        for o, s in rows
    ]


@router.post(
    "/venues/{venue_id}/my-replacement-offers/{offer_id}",
    response_model=MessageRead,
    status_code=200,
    summary="Eigene Vertretung nach erneuter Eignungsprüfung verbindlich annehmen oder ablehnen",
)
async def answer(
    venue_id: uuid.UUID, offer_id: uuid.UUID, data: Answer, user: Actor, db: DB
) -> MessageRead:
    venue, _ = await svc.venue_access(db, user, venue_id, lock=True)
    offer = (
        await db.execute(
            select(EmergencyOffer)
            .join(Emergency, Emergency.id == EmergencyOffer.emergency_id)
            .where(
                EmergencyOffer.id == offer_id,
                EmergencyOffer.worker_id == user.id,
                Emergency.venue_id == venue_id,
            )
            .with_for_update(of=EmergencyOffer)
        )
    ).scalar_one_or_none()
    if offer is None:
        raise HTTPException(404, "Anfrage nicht gefunden.")
    emergency = (
        await db.execute(
            select(Emergency).where(Emergency.id == offer.emergency_id).with_for_update()
        )
    ).scalar_one()
    if offer.status == "accepted" and data.accept:
        return MessageRead(message="Du hast diesen Dienst bereits übernommen.")
    if (
        emergency.status != "open"
        or offer.status != "offered"
        or offer.expires_at is None
        or offer.expires_at <= datetime.now(UTC)
    ):
        raise HTTPException(409, "Angebot abgelaufen oder bereits vergeben.")
    if not data.accept:
        offer.status = "declined"
        offer.responded_at = datetime.now(UTC)
        svc.event(db, venue_id, "replacement.declined", offer.id, {}, user.id)
        await advance(db, emergency)
        return MessageRead(
            message="Absage gespeichert. Die nächste geeignete Person wird angefragt."
        )
    shift = await target_shift(db, venue_id, emergency.shift_id)
    membership = await member(db, venue_id, user.id)
    window = (
        await db.execute(
            select(Availability.id).where(
                Availability.venue_id == venue_id,
                Availability.worker_id == user.id,
                Availability.starts_at <= shift.starts_at,
                Availability.ends_at >= shift.ends_at,
            )
        )
    ).first()
    from app.gastro.station_service import work_kinds

    kind = (await work_kinds(db, venue_id, [shift.station]))[shift.station]
    if not membership.emergency_opt_in or kind not in membership.stations or not window:
        raise HTTPException(
            409, "Bereitschaft, Qualifikation oder Verfügbarkeit hat sich geändert."
        )
    from app.gastro.station_service import replacement_station

    station = await replacement_station(db, venue_id, shift.station)
    proposal = ShiftInput(
        worker_id=user.id,
        station=station.code,
        starts_at=shift.starts_at,
        ends_at=shift.ends_at,
        break_minutes=shift.break_minutes,
    )
    birth_date = (
        await db.execute(
            select(WorkerSettings.date_of_birth).where(WorkerSettings.user_id == user.id)
        )
    ).scalar_one_or_none()
    if birth_date is None:
        raise HTTPException(409, "Altersprüfung ist nicht mehr vollständig. Leitung kontaktieren.")
    await check_shift_person(db, venue, proposal)
    manager = (
        await db.execute(
            select(User)
            .join(Membership, Membership.user_id == User.id)
            .where(
                User.id == emergency.actor_id,
                User.tenant_id == venue.tenant_id,
                User.is_active.is_(True),
                Membership.venue_id == venue_id,
                Membership.active.is_(True),
                Membership.role == "manager",
            )
        )
    ).scalar_one_or_none()
    if manager is None:
        raise HTTPException(
            409, "Die freigebende Betriebsleitung ist nicht mehr aktiv. Neue Freigabe erforderlich."
        )
    replacement = await create_shift(venue_id, proposal, manager, db)
    await shift_status(
        venue_id,
        replacement.id,
        ShiftState(version=replacement.version, status="published"),
        manager,
        db,
    )
    await shift_status(
        venue_id, shift.id, ShiftState(version=shift.version, status="cancelled"), manager, db
    )
    emergency.status = "filled"
    emergency.replacement_shift_id = replacement.id
    emergency.version += 1
    offer.status = "accepted"
    offer.responded_at = datetime.now(UTC)
    others = (
        await db.execute(
            select(EmergencyOffer).where(
                EmergencyOffer.emergency_id == emergency.id, EmergencyOffer.id != offer.id
            )
        )
    ).scalars()
    for other in others:
        if other.status in {"offered", "queued"}:
            other.status = "closed"
    svc.event(
        db,
        venue_id,
        "replacement.accepted",
        offer.id,
        {
            "replacement_shift_id": str(replacement.id),
            "replaced_shift_id": str(shift.id),
            "authorized_by": str(manager.id),
        },
        user.id,
    )
    return MessageRead(
        message="Dienst übernommen. Der Plan ist aktualisiert; weitere Angebote wurden geschlossen."
    )
