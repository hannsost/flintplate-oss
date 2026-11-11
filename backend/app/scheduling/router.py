"""Revocable interview slots with candidate authorization and conflict checking."""

from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated, cast

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import AwareDatetime, BaseModel, Field, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.applications.models import Application, ApplicationHistory, ApplicationStatus
from app.companies.workspace_access import workspace_user
from app.database import get_db
from app.integrations import providers
from app.integrations.models import CalendarDelivery, WorkspaceConnection
from app.integrations.router import active_connection
from app.interviews.models import InterviewSchedule
from app.pipeline.access import require_application
from app.scheduling.models import InterviewBooking
from app.security import get_current_user
from app.users.models import User

router = APIRouter(prefix="/workspace")
HR = Annotated[User, Depends(workspace_user)]
DB = Annotated[AsyncSession, Depends(get_db)]
CurrentUser = Annotated[User, Depends(get_current_user)]


class BookingCreate(BaseModel):
    application_id: uuid.UUID
    slots: list[AwareDatetime] = Field(min_length=1, max_length=12)
    duration_minutes: int = Field(default=30, ge=15, le=120)

    @model_validator(mode="after")
    def future_slots(self) -> BookingCreate:
        now = datetime.now(UTC)
        if any(
            slot <= now + timedelta(hours=1) or slot > now + timedelta(days=30)
            for slot in self.slots
        ):
            raise ValueError(
                "Termine müssen mindestens eine Stunde und höchstens 30 Tage in der Zukunft liegen."
            )
        self.slots = sorted(set(slot.astimezone(UTC) for slot in self.slots))
        return self


class BookingSecret(BaseModel):
    token: str = Field(min_length=32, max_length=128)


class BookingSelect(BookingSecret):
    scheduled_at: AwareDatetime


class BookingRead(BaseModel):
    id: uuid.UUID
    position: str
    slots: list[datetime]
    duration_minutes: int
    expires_at: datetime
    booked_at: datetime | None
    schedule_id: uuid.UUID | None


class BookingIssued(BookingRead):
    token: str


class BookingResult(BaseModel):
    schedule_id: uuid.UUID
    scheduled_at: datetime
    duration_minutes: int


class SyncRequest(BaseModel):
    provider: providers.Provider


class SyncRead(BaseModel):
    status: str


async def available_slots(db: AsyncSession, booking: InterviewBooking) -> list[datetime]:
    owner = await db.get(User, booking.owner_id)
    if (
        owner is None
        or not owner.is_active
        or owner.tenant_id != booking.tenant_id
        or owner.role not in {"admin", "recruiter"}
    ):
        return []
    now = datetime.now(UTC)
    slots = [slot for slot in booking.slots if slot > now]
    if not slots:
        return []
    begin, end = min(slots) - timedelta(hours=2), max(slots) + timedelta(
        minutes=booking.duration_minutes
    )
    scheduled = (
        (
            await db.execute(
                select(InterviewSchedule).where(
                    InterviewSchedule.proposed_by == booking.owner_id,
                    InterviewSchedule.status.in_(["proposed", "confirmed"]),
                    InterviewSchedule.scheduled_at >= begin,
                    InterviewSchedule.scheduled_at < end,
                )
            )
        )
        .scalars()
        .all()
    )
    busy = [
        (item.scheduled_at, item.scheduled_at + timedelta(minutes=item.duration_minutes))
        for item in scheduled
    ]
    connections = (
        (
            await db.execute(
                select(WorkspaceConnection).where(
                    WorkspaceConnection.user_id == owner.id,
                    WorkspaceConnection.tenant_id == owner.tenant_id,
                )
            )
        )
        .scalars()
        .all()
    )
    for connection in connections:
        provider = cast(providers.Provider, connection.provider)
        _, token = await active_connection(db, owner, provider)
        try:
            busy.extend(await providers.busy_intervals(provider, token, begin, end))
        except providers.IntegrationError as exc:
            raise HTTPException(503, str(exc)) from None
    return [
        slot
        for slot in slots
        if not any(
            slot < finish and slot + timedelta(minutes=booking.duration_minutes) > start
            for start, finish in busy
        )
    ]


async def load_booking(
    db: AsyncSession, token: str, user: User
) -> tuple[InterviewBooking, Application]:
    booking = (
        await db.execute(
            select(InterviewBooking).where(
                InterviewBooking.token_digest == hashlib.sha256(token.encode()).hexdigest()
            )
        )
    ).scalar_one_or_none()
    if booking is None or booking.revoked_at or booking.expires_at <= datetime.now(UTC):
        raise HTTPException(410, "Diese Terminbuchung ist abgelaufen oder wurde zurückgezogen.")
    application = await db.get(Application, booking.application_id)
    if application is None:
        raise HTTPException(410, "Die Bewerbung ist nicht mehr verfügbar.")
    if application.user_id != user.id:
        if user.role not in {"admin", "recruiter"}:
            raise HTTPException(403, "Bitte mit dem eingeladenen Konto anmelden.")
        await require_application(db, application.id, user)
    if application.status in {ApplicationStatus.REJECTED, ApplicationStatus.WITHDRAWN}:
        raise HTTPException(409, "Dieser Bewerbungsprozess ist abgeschlossen.")
    return booking, application


@router.post(
    "/bookings",
    response_model=BookingIssued,
    status_code=201,
    summary="Terminauswahl für eine Bewerbung erstellen",
)
async def create(data: BookingCreate, user: HR, db: DB, response: Response) -> BookingIssued:
    application = await require_application(db, data.application_id, user)
    await db.refresh(application, with_for_update=True)
    if application.status in {ApplicationStatus.REJECTED, ApplicationStatus.WITHDRAWN}:
        raise HTTPException(409, "Dieser Bewerbungsprozess ist abgeschlossen.")
    token = secrets.token_urlsafe(32)
    booking = InterviewBooking(
        tenant_id=user.tenant_id,
        application_id=application.id,
        owner_id=user.id,
        slots=data.slots,
        duration_minutes=data.duration_minutes,
        token_digest=hashlib.sha256(token.encode()).hexdigest(),
        expires_at=min(datetime.now(UTC) + timedelta(days=7), max(data.slots)),
    )
    db.add(booking)
    await db.flush()
    slots = await available_slots(db, booking)
    if not slots:
        raise HTTPException(409, "Alle vorgeschlagenen Zeiten sind bereits belegt.")
    booking.slots = slots
    previous = (
        await db.execute(
            select(InterviewBooking).where(
                InterviewBooking.application_id == application.id,
                InterviewBooking.id != booking.id,
                InterviewBooking.booked_at.is_(None),
                InterviewBooking.revoked_at.is_(None),
            )
        )
    ).scalars()
    for old in previous:
        old.revoked_at = datetime.now(UTC)
    await db.flush()
    response.headers["Cache-Control"] = "no-store"
    return BookingIssued(
        id=booking.id,
        token=token,
        position=application.position,
        slots=slots,
        duration_minutes=booking.duration_minutes,
        expires_at=booking.expires_at,
        booked_at=None,
        schedule_id=None,
    )


@router.get(
    "/bookings",
    response_model=list[BookingRead],
    status_code=200,
    summary="Terminauswahlen einer Bewerbung verwalten",
)
async def list_bookings(application_id: uuid.UUID, user: HR, db: DB) -> list[BookingRead]:
    application = await require_application(db, application_id, user)
    records = (
        await db.execute(
            select(InterviewBooking)
            .where(
                InterviewBooking.application_id == application.id,
                InterviewBooking.tenant_id == user.tenant_id,
                InterviewBooking.revoked_at.is_(None),
                InterviewBooking.expires_at > datetime.now(UTC),
            )
            .order_by(InterviewBooking.created_at.desc())
            .limit(30)
        )
    ).scalars()
    return [
        BookingRead(
            id=item.id,
            position=application.position,
            slots=item.slots,
            duration_minutes=item.duration_minutes,
            expires_at=item.expires_at,
            booked_at=item.booked_at,
            schedule_id=item.schedule_id,
        )
        for item in records
    ]


@router.post(
    "/bookings/preview",
    response_model=BookingRead,
    status_code=200,
    summary="Freigegebene Interviewzeiten ansehen",
)
async def preview(data: BookingSecret, user: CurrentUser, db: DB) -> BookingRead:
    booking, application = await load_booking(db, data.token, user)
    slots = await available_slots(db, booking) if booking.booked_at is None else []
    return BookingRead(
        id=booking.id,
        position=application.position,
        slots=slots,
        duration_minutes=booking.duration_minutes,
        expires_at=booking.expires_at,
        booked_at=booking.booked_at,
        schedule_id=booking.schedule_id,
    )


@router.post(
    "/bookings/reserve",
    response_model=BookingResult,
    status_code=201,
    summary="Ausgewählten Interviewtermin verbindlich buchen",
)
async def reserve(data: BookingSelect, user: CurrentUser, db: DB) -> BookingResult:
    booking, application = await load_booking(db, data.token, user)
    if application.user_id != user.id:
        raise HTTPException(403, "Nur die eingeladene Person kann einen Termin buchen.")
    # Serialize all bookings for one interviewer before checking calendar conflicts.
    await db.execute(select(User.id).where(User.id == booking.owner_id).with_for_update())
    await db.refresh(application, with_for_update=True)
    await db.refresh(booking, with_for_update=True)
    if application.status in {ApplicationStatus.REJECTED, ApplicationStatus.WITHDRAWN}:
        raise HTTPException(409, "Dieser Bewerbungsprozess ist abgeschlossen.")
    if booking.booked_at or booking.revoked_at or booking.expires_at <= datetime.now(UTC):
        raise HTTPException(409, "Diese Auswahl ist nicht mehr verfügbar.")
    if data.scheduled_at not in await available_slots(db, booking):
        raise HTTPException(
            409, "Diese Zeit ist nicht mehr frei. Bitte einen anderen Termin wählen."
        )
    schedule = InterviewSchedule(
        application_id=application.id,
        proposed_by=booking.owner_id,
        tenant_id=booking.tenant_id,
        scheduled_at=data.scheduled_at,
        duration_minutes=booking.duration_minutes,
        status="confirmed",
    )
    db.add(schedule)
    await db.flush()
    booking.booked_at, booking.schedule_id = datetime.now(UTC), schedule.id
    if application.status != ApplicationStatus.INTERVIEW:
        db.add(
            ApplicationHistory(
                application_id=application.id,
                from_status=application.status,
                to_status=ApplicationStatus.INTERVIEW,
                note="Interviewtermin von der eingeladenen Person gebucht.",
            )
        )
        application.status = ApplicationStatus.INTERVIEW
    from app.notifications.service import create_and_push

    await create_and_push(
        db=db,
        user_id=booking.owner_id,
        type_="interview.confirmed",
        title="Interviewtermin gebucht",
        body=f"Ein Termin für {application.position} wurde bestätigt.",
        meta={"application_id": str(application.id), "schedule_id": str(schedule.id)},
    )
    await db.flush()
    return BookingResult(
        schedule_id=schedule.id,
        scheduled_at=schedule.scheduled_at,
        duration_minutes=schedule.duration_minutes,
    )


@router.delete(
    "/bookings/{booking_id}",
    response_model=None,
    status_code=204,
    summary="Terminauswahl zurückziehen",
)
async def revoke(booking_id: uuid.UUID, user: HR, db: DB) -> None:
    booking = (
        await db.execute(
            select(InterviewBooking)
            .where(InterviewBooking.id == booking_id, InterviewBooking.tenant_id == user.tenant_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if booking is None:
        raise HTTPException(404, "Terminauswahl nicht gefunden.")
    await require_application(db, booking.application_id, user)
    booking.revoked_at = datetime.now(UTC)
    await db.flush()


@router.post(
    "/calendar/{schedule_id}/sync",
    response_model=SyncRead,
    status_code=200,
    summary="Eigenen Kalendereintrag übernehmen, aktualisieren oder nach Absage entfernen",
)
async def sync(schedule_id: uuid.UUID, data: SyncRequest, user: HR, db: DB) -> SyncRead:
    schedule = await db.get(InterviewSchedule, schedule_id)
    if schedule is None:
        raise HTTPException(404, "Termin nicht gefunden.")
    application = await require_application(db, schedule.application_id, user)
    active = schedule.status in {"confirmed", "proposed"}
    connection, token = await active_connection(db, user, data.provider)
    # Serialize calendar delivery independently of the short credential transaction.
    present = await db.scalar(
        select(WorkspaceConnection.id)
        .where(WorkspaceConnection.id == connection.id)
        .with_for_update()
    )
    if present is None:
        raise HTTPException(409, "Die Kalenderverbindung wurde zwischenzeitlich getrennt.")
    delivery = (
        await db.execute(
            select(CalendarDelivery).where(
                CalendarDelivery.connection_id == connection.id,
                CalendarDelivery.schedule_id == schedule.id,
            )
        )
    ).scalar_one_or_none()
    if delivery:
        if delivery.status in {"sending", "unknown", "removed"}:
            return SyncRead(status=delivery.status)
        if delivery.external_id is None:
            raise HTTPException(
                409, "Der vorhandene Kalendereintrag muss beim Anbieter geprüft werden."
            )
        delivery.status = "sending"
        await db.commit()
        try:
            if active:
                await providers.update_event(
                    data.provider,
                    token,
                    delivery.external_id,
                    f"Interview: {application.position}",
                    schedule.scheduled_at.astimezone(UTC),
                    (
                        schedule.scheduled_at + timedelta(minutes=schedule.duration_minutes)
                    ).astimezone(UTC),
                )
            else:
                await providers.delete_event(data.provider, token, delivery.external_id)
        except providers.IntegrationError:
            delivery.status = "unknown"
        else:
            delivery.status = "confirmed" if active else "removed"
        await db.commit()
        return SyncRead(status=delivery.status)
    if not active:
        return SyncRead(status="not_exported")
    delivery = CalendarDelivery(
        connection_id=connection.id, schedule_id=schedule.id, status="sending"
    )
    db.add(delivery)
    await db.flush()
    await db.commit()
    try:
        delivery.external_id = await providers.create_event(
            data.provider,
            token,
            str(delivery.id),
            f"Interview: {application.position}",
            schedule.scheduled_at.astimezone(UTC),
            (schedule.scheduled_at + timedelta(minutes=schedule.duration_minutes)).astimezone(UTC),
        )
    except providers.IntegrationError:
        delivery.status = "unknown"
    else:
        delivery.status = "confirmed"
    await db.commit()
    return SyncRead(status=delivery.status)
