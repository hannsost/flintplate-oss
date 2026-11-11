"""Profile templates: one qualification profile several people inherit, with visible overrides.

A template carries only documented qualification, never authorisation and never a
voluntary choice. The venue role stays personal, and the opt-in for replacement
requests belongs to the person alone, so neither can be handed out by applying a
template to a group.

Inherited values are materialised on the membership row, so every existing reader
of a profile keeps working and the recorded value is always the effective one. A
field listed in `overrides` stays personal and no longer follows the template.
"""

from __future__ import annotations

import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.gastro import service as svc
from app.gastro.models import Membership, ProfileTemplate
from app.gastro.router import DB, Actor, private_response
from app.gastro.schemas import ReadModel, VersionInput
from app.users.models import User

router = APIRouter(dependencies=[Depends(private_response)])

Field_ = Literal["stations", "competence"]
FIELDS: tuple[Field_, ...] = ("stations", "competence")

# The same station vocabulary the replacement matcher understands.
Station = Literal["service", "kitchen", "bar", "activities"]


class TemplateInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=80)
    description: str = Field(default="", max_length=300)
    stations: list[Station] = Field(default_factory=list, max_length=4)
    competence: int = Field(default=1, ge=1, le=5)
    active: bool = True

    @field_validator("stations")
    @classmethod
    def unique_stations(cls, value: list[Station]) -> list[Station]:
        return sorted(set(value))


class TemplateUpdate(TemplateInput, VersionInput):
    pass


class TemplateRead(TemplateInput, ReadModel):
    version: int
    members: int = 0


class Change(BaseModel):
    worker_id: uuid.UUID
    full_name: str
    field: Field_
    before: JsonValue
    after: JsonValue


class Shielded(BaseModel):
    worker_id: uuid.UUID
    full_name: str
    fields: list[Field_]


class Impact(BaseModel):
    """What applying these values would change, before anything is written."""

    changes: list[Change]
    shielded: list[Shielded]
    affected_members: int


class ProfileRead(BaseModel):
    worker_id: uuid.UUID
    full_name: str
    role: str
    active: bool
    template_id: uuid.UUID | None
    template_name: str
    stations: list[Station]
    competence: int
    stations_source: Literal["Vorlage", "eigen"]
    competence_source: Literal["Vorlage", "eigen"]
    emergency_opt_in: bool


class ProfileInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    template_id: uuid.UUID | None = None
    overrides: list[Field_] = Field(default_factory=list)
    stations: list[Station] | None = Field(default=None, max_length=4)
    competence: int | None = Field(default=None, ge=1, le=5)

    @field_validator("stations")
    @classmethod
    def unique_stations(cls, value: list[Station] | None) -> list[Station] | None:
        return None if value is None else sorted(set(value))


class CopyInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_worker_id: uuid.UUID


async def template_for_venue(
    db: AsyncSession, venue_id: uuid.UUID, template_id: uuid.UUID, *, lock: bool = False
) -> ProfileTemplate:
    query = select(ProfileTemplate).where(
        ProfileTemplate.id == template_id, ProfileTemplate.venue_id == venue_id
    )
    if lock:
        query = query.with_for_update()
    row = (await db.execute(query)).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, "Profilvorlage nicht gefunden.")
    return row


async def member_row(db: AsyncSession, venue_id: uuid.UUID, worker_id: uuid.UUID) -> Membership:
    row = (
        await db.execute(
            select(Membership)
            .where(Membership.venue_id == venue_id, Membership.user_id == worker_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, "Diese Person gehört nicht zu der Betriebsstätte.")
    return row


async def usage(db: AsyncSession, venue_id: uuid.UUID) -> dict[uuid.UUID, int]:
    rows = (
        await db.execute(
            select(Membership.template_id, func.count())
            .where(Membership.venue_id == venue_id, Membership.template_id.is_not(None))
            .group_by(Membership.template_id)
        )
    ).all()
    return {row[0]: row[1] for row in rows}


async def followers(
    db: AsyncSession, venue_id: uuid.UUID, template_id: uuid.UUID
) -> list[tuple[Membership, str]]:
    rows = (
        await db.execute(
            select(Membership, User.full_name)
            .join(User, User.id == Membership.user_id)
            .where(Membership.venue_id == venue_id, Membership.template_id == template_id)
            .order_by(User.full_name)
        )
    ).all()
    return [(row[0], row[1] or "Teammitglied") for row in rows]


def value_of(source: Membership | ProfileTemplate, field: Field_) -> JsonValue:
    return list(source.stations) if field == "stations" else source.competence


def apply_template(member: Membership, template: ProfileTemplate) -> None:
    """Materialise every field the person has not taken over personally."""
    for field in FIELDS:
        if field in member.overrides:
            continue
        if field == "stations":
            member.stations = sorted(set(template.stations))
        else:
            member.competence = template.competence


@router.get(
    "/venues/{venue_id}/profile-templates",
    response_model=list[TemplateRead],
    status_code=200,
    summary="Profilvorlagen der Betriebsstätte",
)
async def templates(venue_id: uuid.UUID, user: Actor, db: DB) -> list[TemplateRead]:
    await svc.venue_access(db, user, venue_id, svc.SERVICE)
    counts = await usage(db, venue_id)
    rows = (
        (
            await db.execute(
                select(ProfileTemplate)
                .where(ProfileTemplate.venue_id == venue_id)
                .order_by(ProfileTemplate.name)
            )
        )
        .scalars()
        .all()
    )
    return [
        TemplateRead(
            id=row.id,
            name=row.name,
            description=row.description,
            stations=row.stations,
            competence=row.competence,
            active=row.active,
            version=row.version,
            members=counts.get(row.id, 0),
        )
        for row in rows
    ]


@router.post(
    "/venues/{venue_id}/profile-templates",
    response_model=TemplateRead,
    status_code=201,
    summary="Profilvorlage anlegen",
)
async def create_template(
    venue_id: uuid.UUID, data: TemplateInput, user: Actor, db: DB
) -> TemplateRead:
    await svc.venue_access(db, user, venue_id, svc.MANAGERS, lock=True)
    exists = (
        await db.execute(
            select(ProfileTemplate.id).where(
                ProfileTemplate.venue_id == venue_id, ProfileTemplate.name == data.name
            )
        )
    ).first()
    if exists:
        raise HTTPException(409, "Eine Vorlage mit diesem Namen existiert bereits.")
    row = ProfileTemplate(venue_id=venue_id, **data.model_dump())
    db.add(row)
    await db.flush()
    svc.event(
        db, venue_id, "profile.template_created", row.id, data.model_dump(mode="json"), user.id
    )
    return TemplateRead(**data.model_dump(), id=row.id, version=row.version, members=0)


@router.post(
    "/venues/{venue_id}/profile-templates/{template_id}/impact",
    response_model=Impact,
    status_code=200,
    summary="Vorschau: was diese Werte bei wem ändern würden",
)
async def impact(
    venue_id: uuid.UUID, template_id: uuid.UUID, data: TemplateInput, user: Actor, db: DB
) -> Impact:
    await svc.venue_access(db, user, venue_id, svc.MANAGERS)
    template = await template_for_venue(db, venue_id, template_id)
    proposed = ProfileTemplate(
        venue_id=venue_id, name=data.name, stations=data.stations, competence=data.competence
    )
    changes: list[Change] = []
    shielded: list[Shielded] = []
    for member, name in await followers(db, venue_id, template.id):
        kept: list[Field_] = []
        for field in FIELDS:
            if field in member.overrides:
                kept.append(field)
                continue
            before, after = value_of(member, field), value_of(proposed, field)
            if before != after:
                changes.append(
                    Change(
                        worker_id=member.user_id,
                        full_name=name,
                        field=field,
                        before=before,
                        after=after,
                    )
                )
        if kept:
            shielded.append(Shielded(worker_id=member.user_id, full_name=name, fields=kept))
    return Impact(
        changes=changes,
        shielded=shielded,
        affected_members=len({str(change.worker_id) for change in changes}),
    )


@router.put(
    "/venues/{venue_id}/profile-templates/{template_id}",
    response_model=TemplateRead,
    status_code=200,
    summary="Profilvorlage ändern und auf die erbenden Personen anwenden",
)
async def update_template(
    venue_id: uuid.UUID, template_id: uuid.UUID, data: TemplateUpdate, user: Actor, db: DB
) -> TemplateRead:
    await svc.venue_access(db, user, venue_id, svc.MANAGERS, lock=True)
    template = await template_for_venue(db, venue_id, template_id, lock=True)
    svc.check_version(template.version, data.version)
    clash = (
        await db.execute(
            select(ProfileTemplate.id).where(
                ProfileTemplate.venue_id == venue_id,
                ProfileTemplate.name == data.name,
                ProfileTemplate.id != template_id,
            )
        )
    ).first()
    if clash:
        raise HTTPException(409, "Eine Vorlage mit diesem Namen existiert bereits.")
    for field, value in data.model_dump(exclude={"version"}).items():
        setattr(template, field, value)
    template.version += 1
    rows = await followers(db, venue_id, template.id)
    for member, _ in rows:
        apply_template(member, template)
    svc.event(
        db,
        venue_id,
        "profile.template_changed",
        template.id,
        data.model_dump(mode="json") | {"members": len(rows)},
        user.id,
    )
    await db.flush()
    return TemplateRead(
        id=template.id,
        name=template.name,
        description=template.description,
        stations=template.stations,
        competence=template.competence,
        active=template.active,
        version=template.version,
        members=len(rows),
    )


@router.delete(
    "/venues/{venue_id}/profile-templates/{template_id}",
    status_code=204,
    summary="Unbenutzte Profilvorlage entfernen",
)
async def delete_template(venue_id: uuid.UUID, template_id: uuid.UUID, user: Actor, db: DB) -> None:
    await svc.venue_access(db, user, venue_id, svc.MANAGERS, lock=True)
    template = await template_for_venue(db, venue_id, template_id, lock=True)
    rows = await followers(db, venue_id, template.id)
    if rows:
        raise HTTPException(
            409,
            f"{len(rows)} Personen erben noch von dieser Vorlage. Zuerst dort lösen.",
        )
    await db.delete(template)
    svc.event(
        db, venue_id, "profile.template_removed", template_id, {"name": template.name}, user.id
    )


@router.get(
    "/venues/{venue_id}/staff-profiles",
    response_model=list[ProfileRead],
    status_code=200,
    summary="Profile des Teams mit Herkunft je Feld",
)
async def profiles(venue_id: uuid.UUID, user: Actor, db: DB) -> list[ProfileRead]:
    await svc.venue_access(db, user, venue_id, svc.SERVICE)
    rows = (
        await db.execute(
            select(Membership, User.full_name, ProfileTemplate.name)
            .join(User, User.id == Membership.user_id)
            .join(ProfileTemplate, ProfileTemplate.id == Membership.template_id, isouter=True)
            .where(Membership.venue_id == venue_id, User.tenant_id == user.tenant_id)
            .order_by(User.full_name)
        )
    ).all()
    return [
        ProfileRead(
            worker_id=member.user_id,
            full_name=name or "Teammitglied",
            role=member.role,
            active=member.active,
            template_id=member.template_id,
            template_name=template or "",
            stations=member.stations,
            competence=member.competence,
            stations_source=(
                "eigen"
                if member.template_id is None or "stations" in member.overrides
                else "Vorlage"
            ),
            competence_source=(
                "eigen"
                if member.template_id is None or "competence" in member.overrides
                else "Vorlage"
            ),
            emergency_opt_in=member.emergency_opt_in,
        )
        for member, name, template in rows
    ]


async def write_profile(
    db: AsyncSession, venue_id: uuid.UUID, member: Membership, data: ProfileInput
) -> None:
    if data.stations is not None:
        member.stations = list(data.stations)
    if data.competence is not None:
        member.competence = data.competence
    if data.template_id is None:
        # Without a template every field is personal; the last inherited values stay.
        member.template_id = None
        member.overrides = []
        return
    template = await template_for_venue(db, venue_id, data.template_id)
    if not template.active:
        raise HTTPException(409, "Diese Vorlage ist nicht mehr aktiv.")
    member.template_id = template.id
    member.overrides = [field for field in FIELDS if field in data.overrides]
    apply_template(member, template)


@router.put(
    "/venues/{venue_id}/staff-profiles/{worker_id}",
    response_model=ProfileRead,
    status_code=200,
    summary="Vorlage zuweisen, Felder selbst setzen oder wieder erben lassen",
)
async def set_profile(
    venue_id: uuid.UUID, worker_id: uuid.UUID, data: ProfileInput, user: Actor, db: DB
) -> ProfileRead:
    await svc.venue_access(db, user, venue_id, svc.MANAGERS, lock=True)
    member = await member_row(db, venue_id, worker_id)
    await write_profile(db, venue_id, member, data)
    svc.event(
        db,
        venue_id,
        "profile.assigned",
        member.id,
        data.model_dump(mode="json") | {"worker_id": str(worker_id)},
        user.id,
    )
    await db.flush()
    return await one_profile(db, venue_id, worker_id, user)


@router.post(
    "/venues/{venue_id}/staff-profiles/{worker_id}/copy-from",
    response_model=ProfileRead,
    status_code=200,
    summary="Einstellungen einer anderen Person übernehmen",
)
async def copy_from(
    venue_id: uuid.UUID, worker_id: uuid.UUID, data: CopyInput, user: Actor, db: DB
) -> ProfileRead:
    await svc.venue_access(db, user, venue_id, svc.MANAGERS, lock=True)
    if data.source_worker_id == worker_id:
        raise HTTPException(422, "Quelle und Ziel sind dieselbe Person.")
    source = await member_row(db, venue_id, data.source_worker_id)
    target = await member_row(db, venue_id, worker_id)
    # Role and the voluntary replacement opt-in are deliberately not copied.
    target.stations = sorted(set(source.stations))
    target.competence = source.competence
    target.template_id = source.template_id
    target.overrides = list(source.overrides)
    svc.event(
        db,
        venue_id,
        "profile.copied",
        target.id,
        {"from_worker_id": str(data.source_worker_id), "worker_id": str(worker_id)},
        user.id,
    )
    await db.flush()
    return await one_profile(db, venue_id, worker_id, user)


async def one_profile(
    db: AsyncSession, venue_id: uuid.UUID, worker_id: uuid.UUID, user: User
) -> ProfileRead:
    rows = await profiles(venue_id, user, db)
    for row in rows:
        if row.worker_id == worker_id:
            return row
    raise HTTPException(404, "Diese Person gehört nicht zu der Betriebsstätte.")
