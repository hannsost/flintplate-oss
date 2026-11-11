"""Guest book: remember regulars without turning the team into an archive.

The venue is the controller of every entry here, including the ones a person
marks as personal. `private` is a visibility inside the house, never a promise
that the record is beyond reach: an access request is answered from the export,
and management can delete any entry. The wording in the interface says so.

Three guard rails carry the rest. Notes that touch health, diet or belief are
refused unless the guest's consent is recorded, and revoking that consent deletes
exactly those notes. Every note carries an expiry derived from the venue's
retention period; expired notes stop being shown and can be purged for real.
Opening a person's record writes into the venue journal, so looking someone up
is as traceable as changing a price.
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.gastro import service as svc
from app.gastro.models import GuestAccount, GuestNote, GuestProfile
from app.gastro.router import DB, Actor, private_response
from app.users.models import User

router = APIRouter(dependencies=[Depends(private_response)])

Category = Literal["vorliebe", "anlass", "gespraech", "hinweis", "gesundheit", "ernaehrung"]
# Health and diet reach into Article 9 territory, so they need recorded consent.
SPECIAL: frozenset[str] = frozenset({"gesundheit", "ernaehrung"})
BIRTHDAY = re.compile(r"^(0[1-9]|[12][0-9]|3[01])\.(0[1-9]|1[0-2])$")


class ProfileInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    display_name: str = Field(min_length=2, max_length=120)
    reference: str = Field(default="", max_length=160)
    birthday: str | None = Field(default=None, max_length=5)
    account_id: uuid.UUID | None = None

    @field_validator("birthday")
    @classmethod
    def day_and_month_only(cls, value: str | None) -> str | None:
        if value in (None, ""):
            return None
        if not BIRTHDAY.match(value or ""):
            raise ValueError(
                "Geburtstag als TT.MM angeben; ein Geburtsjahr wird nicht gespeichert."
            )
        return value


class ProfileUpdate(ProfileInput):
    version: int = Field(ge=1)


class ConsentInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: int = Field(ge=1)
    granted: bool


class NoteInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=2, max_length=1000)
    category: Category = "hinweis"
    visibility: Literal["team", "private"] = "team"


class NoteRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    text: str
    category: str
    visibility: str
    sensitive: bool
    author_id: uuid.UUID
    author_name: str = ""
    mine: bool = False
    created_at: datetime
    expires_at: datetime


class ProfileRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    display_name: str
    reference: str
    birthday: str | None
    account_id: uuid.UUID | None
    consent_special: bool
    consent_at: datetime | None
    markers: list[str] = []
    version: int
    created_at: datetime
    notes: int = 0


class ProfileDetail(ProfileRead):
    entries: list[NoteRead] = []
    retention_days: int = 365


class Export(BaseModel):
    """Everything stored about this person, for an access request."""

    profile: ProfileRead
    entries: list[NoteRead]
    exported_at: datetime
    hint: str


async def profile_for(
    db: AsyncSession, venue_id: uuid.UUID, profile_id: uuid.UUID, *, lock: bool = False
) -> GuestProfile:
    query = select(GuestProfile).where(
        GuestProfile.id == profile_id, GuestProfile.venue_id == venue_id
    )
    if lock:
        query = query.with_for_update()
    row = (await db.execute(query)).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, "Eintrag nicht gefunden.")
    return row


def visible(note: GuestNote, user_id: uuid.UUID) -> bool:
    return note.visibility != "private" or note.author_id == user_id


async def entries_for(
    db: AsyncSession, profile: GuestProfile, user_id: uuid.UUID, *, everything: bool = False
) -> list[NoteRead]:
    rows = (
        await db.execute(
            select(GuestNote, User.full_name)
            .join(User, User.id == GuestNote.author_id)
            .where(
                GuestNote.profile_id == profile.id,
                *([] if everything else [GuestNote.expires_at > datetime.now(UTC)]),
            )
            .order_by(GuestNote.created_at.desc())
        )
    ).all()
    return [
        NoteRead(
            id=note.id,
            text=note.text,
            category=note.category,
            visibility=note.visibility,
            sensitive=note.sensitive,
            author_id=note.author_id,
            author_name=name or "Teammitglied",
            mine=note.author_id == user_id,
            created_at=note.created_at,
            expires_at=note.expires_at,
        )
        for note, name in rows
        if everything or visible(note, user_id)
    ]


@router.get(
    "/venues/{venue_id}/guestbook",
    response_model=list[ProfileRead],
    status_code=200,
    summary="Gäste im Kundenbuch suchen",
)
async def profiles(venue_id: uuid.UUID, user: Actor, db: DB, query: str = "") -> list[ProfileRead]:
    await svc.venue_access(db, user, venue_id, svc.SERVICE)
    term = query.strip()
    statement = select(GuestProfile).where(GuestProfile.venue_id == venue_id)
    if term:
        pattern = f"%{term}%"
        statement = statement.where(
            or_(GuestProfile.display_name.ilike(pattern), GuestProfile.reference.ilike(pattern))
        )
    rows = (
        (await db.execute(statement.order_by(GuestProfile.display_name).limit(100))).scalars().all()
    )
    counted = (
        await db.execute(
            select(GuestNote.profile_id, func.count())
            .where(
                GuestNote.venue_id == venue_id,
                GuestNote.expires_at > datetime.now(UTC),
                or_(GuestNote.visibility == "team", GuestNote.author_id == user.id),
            )
            .group_by(GuestNote.profile_id)
        )
    ).all()
    counts: dict[uuid.UUID, int] = {row[0]: row[1] for row in counted}
    return [
        ProfileRead.model_validate(row).model_copy(update={"notes": counts.get(row.id, 0)})
        for row in rows
    ]


@router.post(
    "/venues/{venue_id}/guestbook",
    response_model=ProfileRead,
    status_code=201,
    summary="Gast ins Kundenbuch aufnehmen",
)
async def create_profile(
    venue_id: uuid.UUID, data: ProfileInput, user: Actor, db: DB
) -> ProfileRead:
    await svc.venue_access(db, user, venue_id, svc.SERVICE)
    if data.account_id is not None:
        account = (
            await db.execute(
                select(GuestAccount.id).where(
                    GuestAccount.id == data.account_id, GuestAccount.venue_id == venue_id
                )
            )
        ).first()
        if not account:
            raise HTTPException(404, "Dieses Gastkonto gehört nicht zu der Betriebsstätte.")
    row = GuestProfile(venue_id=venue_id, created_by=user.id, **data.model_dump())
    db.add(row)
    await db.flush()
    svc.event(
        db, venue_id, "guestbook.profile_created", row.id, {"name": row.display_name}, user.id
    )
    return ProfileRead.model_validate(row)


@router.get(
    "/venues/{venue_id}/guestbook/{profile_id}",
    response_model=ProfileDetail,
    status_code=200,
    summary="Eintrag öffnen; der Zugriff wird im Journal festgehalten",
)
async def detail(venue_id: uuid.UUID, profile_id: uuid.UUID, user: Actor, db: DB) -> ProfileDetail:
    venue, _ = await svc.venue_access(db, user, venue_id, svc.SERVICE)
    profile = await profile_for(db, venue_id, profile_id)
    entries = await entries_for(db, profile, user.id)
    svc.event(
        db,
        venue_id,
        "guestbook.viewed",
        profile.id,
        {"entries": len(entries)},
        user.id,
    )
    await db.flush()
    return ProfileDetail.model_validate(profile).model_copy(
        update={
            "notes": len(entries),
            "entries": entries,
            "retention_days": venue.guestbook_retention_days,
        }
    )


@router.put(
    "/venues/{venue_id}/guestbook/{profile_id}",
    response_model=ProfileRead,
    status_code=200,
    summary="Angaben zu einem Gast berichtigen",
)
async def update_profile(
    venue_id: uuid.UUID, profile_id: uuid.UUID, data: ProfileUpdate, user: Actor, db: DB
) -> ProfileRead:
    await svc.venue_access(db, user, venue_id, svc.SERVICE)
    profile = await profile_for(db, venue_id, profile_id, lock=True)
    svc.check_version(profile.version, data.version)
    for field, value in data.model_dump(exclude={"version"}).items():
        setattr(profile, field, value)
    profile.version += 1
    svc.event(
        db, venue_id, "guestbook.profile_changed", profile.id, {"fields": "stammdaten"}, user.id
    )
    await db.flush()
    return ProfileRead.model_validate(profile)


@router.put(
    "/venues/{venue_id}/guestbook/{profile_id}/consent",
    response_model=ProfileRead,
    status_code=200,
    summary="Einwilligung für Gesundheits- und Ernährungshinweise setzen oder widerrufen",
)
async def consent(
    venue_id: uuid.UUID, profile_id: uuid.UUID, data: ConsentInput, user: Actor, db: DB
) -> ProfileRead:
    await svc.venue_access(db, user, venue_id, svc.SERVICE)
    profile = await profile_for(db, venue_id, profile_id, lock=True)
    svc.check_version(profile.version, data.version)
    removed = 0
    if not data.granted:
        # A revocation removes the basis, so the notes that relied on it go too.
        removed = (
            await db.execute(
                select(func.count())
                .select_from(GuestNote)
                .where(GuestNote.profile_id == profile.id, GuestNote.sensitive.is_(True))
            )
        ).scalar_one()
        await db.execute(
            delete(GuestNote).where(
                GuestNote.profile_id == profile.id, GuestNote.sensitive.is_(True)
            )
        )
    profile.consent_special = data.granted
    profile.consent_at = datetime.now(UTC) if data.granted else None
    profile.consent_by = user.id if data.granted else None
    profile.version += 1
    svc.event(
        db,
        venue_id,
        "guestbook.consent_changed",
        profile.id,
        {"granted": data.granted, "removed_notes": removed},
        user.id,
    )
    await db.flush()
    return ProfileRead.model_validate(profile)


@router.post(
    "/venues/{venue_id}/guestbook/{profile_id}/notes",
    response_model=NoteRead,
    status_code=201,
    summary="Notiz anlegen, für das Team oder nur für mich",
)
async def add_note(
    venue_id: uuid.UUID, profile_id: uuid.UUID, data: NoteInput, user: Actor, db: DB
) -> NoteRead:
    venue, _ = await svc.venue_access(db, user, venue_id, svc.SERVICE)
    profile = await profile_for(db, venue_id, profile_id)
    sensitive = data.category in SPECIAL
    if sensitive and not profile.consent_special:
        raise HTTPException(
            409,
            "Hinweise zu Gesundheit oder Ernährung brauchen die ausdrückliche Einwilligung "
            "des Gastes. Bitte zuerst dort eintragen.",
        )
    note = GuestNote(
        profile_id=profile.id,
        venue_id=venue_id,
        author_id=user.id,
        text=data.text.strip(),
        category=data.category,
        visibility=data.visibility,
        sensitive=sensitive,
        expires_at=datetime.now(UTC) + timedelta(days=venue.guestbook_retention_days),
    )
    db.add(note)
    await db.flush()
    svc.event(
        db,
        venue_id,
        "guestbook.note_added",
        profile.id,
        {"category": note.category, "visibility": note.visibility, "sensitive": sensitive},
        user.id,
    )
    return NoteRead(
        id=note.id,
        text=note.text,
        category=note.category,
        visibility=note.visibility,
        sensitive=note.sensitive,
        author_id=user.id,
        author_name=user.full_name or "Teammitglied",
        mine=True,
        created_at=note.created_at,
        expires_at=note.expires_at,
    )


@router.delete(
    "/venues/{venue_id}/guestbook/{profile_id}/notes/{note_id}",
    status_code=204,
    summary="Eigene Notiz löschen; die Leitung darf jede löschen",
)
async def remove_note(
    venue_id: uuid.UUID, profile_id: uuid.UUID, note_id: uuid.UUID, user: Actor, db: DB
) -> None:
    _, role = await svc.venue_access(db, user, venue_id, svc.SERVICE)
    note = (
        await db.execute(
            select(GuestNote)
            .where(
                GuestNote.id == note_id,
                GuestNote.profile_id == profile_id,
                GuestNote.venue_id == venue_id,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if note is None:
        raise HTTPException(404, "Notiz nicht gefunden.")
    if note.author_id != user.id and role != "manager":
        raise HTTPException(403, "Fremde Notizen darf nur die Betriebsleitung löschen.")
    await db.delete(note)
    svc.event(
        db, venue_id, "guestbook.note_removed", profile_id, {"category": note.category}, user.id
    )


@router.get(
    "/venues/{venue_id}/guestbook/{profile_id}/export",
    response_model=Export,
    status_code=200,
    summary="Vollständige Auskunft über eine Person, auch die persönlichen Notizen",
)
async def export(venue_id: uuid.UUID, profile_id: uuid.UUID, user: Actor, db: DB) -> Export:
    await svc.venue_access(db, user, venue_id, svc.MANAGERS)
    profile = await profile_for(db, venue_id, profile_id)
    entries = await entries_for(db, profile, user.id, everything=True)
    svc.event(db, venue_id, "guestbook.exported", profile.id, {"entries": len(entries)}, user.id)
    await db.flush()
    return Export(
        profile=ProfileRead.model_validate(profile).model_copy(update={"notes": len(entries)}),
        entries=entries,
        exported_at=datetime.now(UTC),
        hint=(
            "Diese Auskunft enthält alle gespeicherten Notizen, auch die als persönlich "
            "markierten und die bereits abgelaufenen. Sie ist für die Beantwortung einer "
            "Auskunftsanfrage gedacht."
        ),
    )


@router.delete(
    "/venues/{venue_id}/guestbook/{profile_id}",
    status_code=204,
    summary="Person vollständig löschen",
)
async def erase(venue_id: uuid.UUID, profile_id: uuid.UUID, user: Actor, db: DB) -> None:
    await svc.venue_access(db, user, venue_id, svc.MANAGERS)
    profile = await profile_for(db, venue_id, profile_id, lock=True)
    count = (
        await db.execute(
            select(func.count()).select_from(GuestNote).where(GuestNote.profile_id == profile.id)
        )
    ).scalar_one()
    await db.execute(delete(GuestNote).where(GuestNote.profile_id == profile.id))
    await db.delete(profile)
    # The record of the deletion never repeats what was deleted.
    svc.event(db, venue_id, "guestbook.erased", profile_id, {"entries": count}, user.id)


@router.post(
    "/venues/{venue_id}/guestbook/purge",
    status_code=200,
    summary="Abgelaufene Notizen endgültig entfernen",
)
async def purge(venue_id: uuid.UUID, user: Actor, db: DB) -> dict[str, int]:
    await svc.venue_access(db, user, venue_id, svc.MANAGERS)
    removed = (
        await db.execute(
            select(func.count())
            .select_from(GuestNote)
            .where(GuestNote.venue_id == venue_id, GuestNote.expires_at <= datetime.now(UTC))
        )
    ).scalar_one()
    await db.execute(
        delete(GuestNote).where(
            GuestNote.venue_id == venue_id, GuestNote.expires_at <= datetime.now(UTC)
        )
    )
    if removed:
        svc.event(db, venue_id, "guestbook.purged", venue_id, {"removed": removed}, user.id)
    return {"removed": removed}


@router.put(
    "/venues/{venue_id}/guestbook-retention",
    response_model=dict[str, int],
    status_code=200,
    summary="Aufbewahrungsdauer für Notizen festlegen",
)
async def retention(
    venue_id: uuid.UUID, data: dict[str, int], user: Actor, db: DB
) -> dict[str, int]:
    venue, _ = await svc.venue_access(db, user, venue_id, svc.MANAGERS, lock=True)
    days = int(data.get("days", 0))
    if not 30 <= days <= 1095:
        raise HTTPException(422, "Zwischen 30 und 1095 Tagen.")
    venue.guestbook_retention_days = days
    svc.event(db, venue_id, "guestbook.retention_changed", venue_id, {"days": days}, user.id)
    return {"days": days}
