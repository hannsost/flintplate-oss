"""Replayable, positions-only floor arrangements with preview concurrency checks."""

from __future__ import annotations

import hashlib
import json
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, JsonValue
from sqlalchemy import func, or_, select

from app.gastro import service as svc
from app.gastro.floor_layout_models import (
    FloorLayoutCommand,
    FloorLayoutProfile,
    FloorLayoutRevision,
)
from app.gastro.floor_layout_schemas import (
    MAX_ACTIVE_PROFILES,
    MAX_PROFILE_TABLES,
    PositionInput,
    PositionRead,
    PreviewRow,
    ProfileApplyInput,
    ProfileApplyRead,
    ProfileArchiveInput,
    ProfilePreviewInput,
    ProfilePreviewRead,
    ProfileRead,
    ProfileSaveInput,
    RevisionRead,
)
from app.gastro.models import DiningTable, Room
from app.gastro.router import DB, Actor, private_response

router = APIRouter(dependencies=[Depends(private_response)])
PREFIX = "/venues/{venue_id}/layout/profiles"


def digest(kind: str, target: uuid.UUID | None, data: BaseModel) -> str:
    return hashlib.sha256(
        json.dumps(
            [kind, str(target), data.model_dump(mode="json")], sort_keys=True, separators=(",", ":")
        ).encode()
    ).hexdigest()


def position(table: DiningTable) -> PositionRead:
    return PositionRead(
        table_id=table.id,
        version=table.version,
        x=table.x,
        y=table.y,
        room_id=table.room_id,
        area=table.area,
    )


async def prior(
    db: DB, venue_id: uuid.UUID, key: uuid.UUID, fingerprint: str
) -> dict[str, JsonValue] | None:
    # All commands acquire Venue first, like the existing full table.update API.
    row = (
        await db.execute(
            select(FloorLayoutCommand).where(
                FloorLayoutCommand.venue_id == venue_id, FloorLayoutCommand.request_key == key
            )
        )
    ).scalar_one_or_none()
    if row is None:
        return None
    if row.request_hash != fingerprint:
        raise HTTPException(
            409, "Diese Vorgangs-ID wurde für eine andere Grundrissänderung verwendet."
        )
    return row.result


async def record(
    db: DB,
    venue_id: uuid.UUID,
    actor_id: uuid.UUID,
    key: uuid.UUID,
    fingerprint: str,
    kind: str,
    target: uuid.UUID,
    result: BaseModel,
) -> None:
    payload = result.model_dump(mode="json")
    db.add(
        FloorLayoutCommand(
            venue_id=venue_id,
            actor_id=actor_id,
            request_key=key,
            request_hash=fingerprint,
            kind=kind,
            result=payload,
        )
    )
    svc.event(db, venue_id, f"layout.{kind}", target, payload, actor_id)
    await db.flush()


async def profile_for(db: DB, venue_id: uuid.UUID, profile_id: uuid.UUID) -> FloorLayoutProfile:
    row = (
        await db.execute(
            select(FloorLayoutProfile)
            .where(FloorLayoutProfile.venue_id == venue_id, FloorLayoutProfile.id == profile_id)
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, "Grundrissprofil nicht gefunden.")
    return row


async def revision_for(
    db: DB, profile: FloorLayoutProfile, revision_id: uuid.UUID | None = None
) -> FloorLayoutRevision:
    query = select(FloorLayoutRevision).where(
        FloorLayoutRevision.venue_id == profile.venue_id,
        FloorLayoutRevision.profile_id == profile.id,
    )
    query = (
        query.where(FloorLayoutRevision.id == revision_id)
        if revision_id
        else query.where(FloorLayoutRevision.version == profile.version)
    )
    row = (await db.execute(query)).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, "Gespeicherte Profilversion nicht gefunden.")
    return row


async def profile_read(db: DB, row: FloorLayoutProfile) -> ProfileRead:
    # SQL onupdate timestamps can be expired after an async flush.
    await db.refresh(row)
    revision = await revision_for(db, row)
    return ProfileRead(
        id=row.id,
        name=row.name,
        room_id=row.room_id,
        version=row.version,
        archived=row.archived,
        current_revision_id=revision.id,
        table_count=len(revision.placements),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


async def active_name(
    db: DB,
    venue_id: uuid.UUID,
    name: str,
    exclude: uuid.UUID | None = None,
    *,
    growing: bool = False,
) -> None:
    query = select(FloorLayoutProfile.id).where(
        FloorLayoutProfile.venue_id == venue_id,
        FloorLayoutProfile.archived.is_(False),
        func.lower(FloorLayoutProfile.name) == func.lower(name),
    )
    if exclude:
        query = query.where(FloorLayoutProfile.id != exclude)
    if (await db.execute(query)).first():
        raise HTTPException(409, "Ein aktives Grundrissprofil dieses Namens besteht bereits.")
    if growing:
        count = await db.scalar(
            select(func.count())
            .select_from(FloorLayoutProfile)
            .where(FloorLayoutProfile.venue_id == venue_id, FloorLayoutProfile.archived.is_(False))
        )
        if count is not None and count >= MAX_ACTIVE_PROFILES:
            raise HTTPException(
                409, "Höchstens 50 Grundrissprofile können gleichzeitig aktiv sein."
            )


async def missing_rooms(db: DB, venue_id: uuid.UUID, ids: set[uuid.UUID]) -> set[uuid.UUID]:
    if not ids:
        return set()
    found = set(
        (
            await db.execute(select(Room.id).where(Room.venue_id == venue_id, Room.id.in_(ids)))
        ).scalars()
    )
    return ids - found


async def scoped_tables(
    db: DB,
    venue_id: uuid.UUID,
    room_id: uuid.UUID | None,
    *,
    saved_ids: set[uuid.UUID] | None = None,
) -> list[DiningTable]:
    query = select(DiningTable).where(DiningTable.venue_id == venue_id)
    if room_id is not None:
        query = query.where(
            or_(DiningTable.room_id == room_id, DiningTable.id.in_(saved_ids or set()))
        )
    # More than 500 current scoped resources cannot be reviewed in one snapshot.
    # Saved targets outside this room remain included to diagnose room changes.
    return list(
        (
            await db.execute(
                query.order_by(DiningTable.id)
                .limit(MAX_PROFILE_TABLES * 2 + 1)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        ).scalars()
    )


async def next_revision(
    db: DB,
    profile: FloorLayoutProfile,
    *,
    name: str,
    archived: bool,
    placements: list[PositionRead],
    actor_id: uuid.UUID,
    previous: FloorLayoutRevision | None,
) -> FloorLayoutRevision:
    row = FloorLayoutRevision(
        venue_id=profile.venue_id,
        profile_id=profile.id,
        previous_id=previous.id if previous else None,
        version=previous.version + 1 if previous else 1,
        name=name,
        room_id=profile.room_id,
        archived=archived,
        placements=[p.model_dump(mode="json") for p in placements],
        actor_id=actor_id,
    )
    db.add(row)
    # DDL guards require the immutable next snapshot before metadata advances.
    await db.flush()
    if previous is not None:
        profile.version = row.version
        profile.name = name
        profile.archived = archived
        await db.flush()
    return row


@router.post(
    "/venues/{venue_id}/tables/{table_id}/position",
    response_model=PositionRead,
    status_code=201,
    summary="Ressource idempotent verschieben, ohne Raum, Kapazität oder Tarif zu ändern",
)
async def move_table(
    venue_id: uuid.UUID, table_id: uuid.UUID, data: PositionInput, user: Actor, db: DB
) -> PositionRead:
    await svc.venue_access(db, user, venue_id, svc.MANAGERS, lock=True)
    fingerprint = digest("position", table_id, data)
    replay = await prior(db, venue_id, data.request_key, fingerprint)
    if replay is not None:
        return PositionRead.model_validate(replay)
    table = await svc.table_for_venue(db, venue_id, table_id, lock=True)
    svc.check_version(table.version, data.version)
    if (table.x, table.y) != (data.x, data.y):
        table.x, table.y = data.x, data.y
        table.version += 1
        await db.flush()
    result = position(table)
    await record(db, venue_id, user.id, data.request_key, fingerprint, "position", table.id, result)
    return result


@router.get(
    PREFIX,
    response_model=list[ProfileRead],
    status_code=200,
    summary="Benannte Grundrissanordnungen des Betriebs anzeigen",
)
async def list_profiles(
    venue_id: uuid.UUID, user: Actor, db: DB, include_archived: bool = False
) -> list[ProfileRead]:
    await svc.venue_access(db, user, venue_id)
    query = select(FloorLayoutProfile).where(FloorLayoutProfile.venue_id == venue_id)
    if not include_archived:
        query = query.where(FloorLayoutProfile.archived.is_(False))
    profiles = list(
        (await db.execute(query.order_by(FloorLayoutProfile.name, FloorLayoutProfile.id))).scalars()
    )
    return [await profile_read(db, row) for row in profiles]


@router.get(
    PREFIX + "/{profile_id}/versions",
    response_model=list[RevisionRead],
    status_code=200,
    summary="Unveränderliche Profilversionen einschließlich früherer Anordnungen anzeigen",
)
async def revisions(
    venue_id: uuid.UUID,
    profile_id: uuid.UUID,
    user: Actor,
    db: DB,
    before_version: int | None = Query(default=None, ge=1),
    limit: int = Query(default=50, ge=1, le=50),
) -> list[FloorLayoutRevision]:
    await svc.venue_access(db, user, venue_id)
    await profile_for(db, venue_id, profile_id)
    query = select(FloorLayoutRevision).where(
        FloorLayoutRevision.venue_id == venue_id, FloorLayoutRevision.profile_id == profile_id
    )
    if before_version is not None:
        query = query.where(FloorLayoutRevision.version < before_version)
    return list(
        (
            await db.execute(query.order_by(FloorLayoutRevision.version.desc()).limit(limit))
        ).scalars()
    )


@router.post(
    PREFIX,
    response_model=ProfileRead,
    status_code=201,
    summary="Die vollständig angezeigte aktuelle Anordnung als Profilversion speichern",
)
async def save_profile(
    venue_id: uuid.UUID, data: ProfileSaveInput, user: Actor, db: DB
) -> ProfileRead:
    await svc.venue_access(db, user, venue_id, svc.MANAGERS, lock=True)
    fingerprint = digest("save", data.profile_id, data)
    replay = await prior(db, venue_id, data.request_key, fingerprint)
    if replay is not None:
        return ProfileRead.model_validate(replay)
    if data.room_id and await missing_rooms(db, venue_id, {data.room_id}):
        raise HTTPException(404, "Raum nicht in diesem Betrieb gefunden.")
    previous: FloorLayoutRevision | None = None
    if data.profile_id:
        profile = await profile_for(db, venue_id, data.profile_id)
        svc.check_version(profile.version, data.expected_version)
        if profile.archived:
            raise HTTPException(409, "Archiviertes Profil zuerst ausdrücklich reaktivieren.")
        if profile.room_id != data.room_id:
            raise HTTPException(
                422, "Der Geltungsraum eines bestehenden Profils bleibt unverändert."
            )
        previous = await revision_for(db, profile)
    else:
        profile = FloorLayoutProfile(
            id=uuid.uuid4(),
            venue_id=venue_id,
            name=data.name,
            room_id=data.room_id,
            version=1,
            archived=False,
        )
    tables = await scoped_tables(db, venue_id, data.room_id)
    if len(tables) > MAX_PROFILE_TABLES:
        raise HTTPException(422, "Ein Grundrissprofil darf höchstens 500 Ressourcen enthalten.")
    versions = {row.table_id: row.version for row in data.tables}
    if set(versions) != {table.id for table in tables}:
        raise HTTPException(
            409,
            "Die Ressourcen dieses Raums haben sich geändert. Vollständigen Grundriss neu laden.",
        )
    if any(table.version != versions[table.id] for table in tables):
        raise HTTPException(
            409, "Eine Ressource wurde inzwischen geändert. Grundriss vor dem Speichern neu laden."
        )
    if await missing_rooms(db, venue_id, {table.room_id for table in tables if table.room_id}):
        raise HTTPException(409, "Eine gespeicherte Raumzuordnung ist nicht mehr gültig.")
    await active_name(db, venue_id, data.name, profile.id, growing=previous is None)
    if previous is None:
        db.add(profile)
        await db.flush()
    await next_revision(
        db,
        profile,
        name=data.name,
        archived=False,
        placements=[position(table) for table in tables],
        actor_id=user.id,
        previous=previous,
    )
    result = await profile_read(db, profile)
    await record(db, venue_id, user.id, data.request_key, fingerprint, "save", profile.id, result)
    return result


async def preview_for(
    db: DB, profile: FloorLayoutProfile, revision_id: uuid.UUID | None
) -> ProfilePreviewRead:
    revision = await revision_for(db, profile, revision_id)
    placements = [PositionRead.model_validate(row) for row in revision.placements]
    saved = {row.table_id: row for row in placements}
    current = await scoped_tables(db, profile.venue_id, profile.room_id, saved_ids=set(saved))
    by_id = {row.id: row for row in current}
    scope_ids = {
        row.id for row in current if profile.room_id is None or row.room_id == profile.room_id
    }
    added = scope_ids - set(saved)
    missing = set(saved) - set(by_id)
    room_ids = {row.room_id for row in placements if row.room_id}
    if profile.room_id:
        room_ids.add(profile.room_id)
    bad_rooms = await missing_rooms(db, profile.venue_id, room_ids)
    problems: list[str] = []
    if profile.archived:
        problems.append("Dieses Profil ist archiviert und muss zuerst reaktiviert werden.")
    if len(scope_ids) > MAX_PROFILE_TABLES:
        problems.append("Der Geltungsraum überschreitet 500 Ressourcen.")
    if missing:
        problems.append(
            "Gespeicherte Ressourcen fehlen; sie werden nicht automatisch neu angelegt."
        )
    if added:
        problems.append(
            "Der Geltungsraum enthält inzwischen zusätzliche Ressourcen. Profil vor dem Anwenden neu prüfen und speichern."
        )
    if bad_rooms:
        problems.append("Ein gespeicherter Raum besteht nicht mehr in diesem Betrieb.")
    if any(
        table.id in saved
        and (table.room_id, table.area) != (saved[table.id].room_id, saved[table.id].area)
        for table in current
    ):
        problems.append(
            "Raum oder Bereich einer Ressource wurde geändert. Eine Anordnung verschiebt keine Ressourcen zwischen Räumen."
        )
    rows = [
        PreviewRow(
            table_id=entry.table_id,
            name=(
                by_id[entry.table_id].name
                if entry.table_id in by_id
                else "Nicht mehr vorhandene Ressource"
            ),
            current=position(by_id[entry.table_id]) if entry.table_id in by_id else None,
            saved=entry,
            changed=entry.table_id in by_id
            and (by_id[entry.table_id].x, by_id[entry.table_id].y) != (entry.x, entry.y),
        )
        for entry in placements
    ]
    result = ProfilePreviewRead(
        profile_id=profile.id,
        profile_version=profile.version,
        revision_id=revision.id,
        snapshot_version=revision.version,
        name=profile.name,
        room_id=profile.room_id,
        rows=rows,
        added_table_ids=sorted(added, key=str),
        missing_table_ids=sorted(missing, key=str),
        blocking_reasons=problems,
        fingerprint="",
    )
    result.fingerprint = digest("preview", profile.id, result)
    return result


@router.post(
    PREFIX + "/{profile_id}/preview",
    response_model=ProfilePreviewRead,
    status_code=200,
    summary="Gespeicherte Anordnung mit dem aktuellen Grundriss vergleichen, ohne Änderungen zu speichern",
)
async def preview_profile(
    venue_id: uuid.UUID, profile_id: uuid.UUID, data: ProfilePreviewInput, user: Actor, db: DB
) -> ProfilePreviewRead:
    # Read-only but locked, so the table/version set is one coherent preview.
    await svc.venue_access(db, user, venue_id, lock=True)
    profile = await profile_for(db, venue_id, profile_id)
    svc.check_version(profile.version, data.version)
    return await preview_for(db, profile, data.revision_id)


@router.post(
    PREFIX + "/{profile_id}/apply",
    response_model=ProfileApplyRead,
    status_code=201,
    summary="Vorgeprüfte Profilkoordinaten atomar auf die bestehenden Ressourcen anwenden",
)
async def apply_profile(
    venue_id: uuid.UUID, profile_id: uuid.UUID, data: ProfileApplyInput, user: Actor, db: DB
) -> ProfileApplyRead:
    await svc.venue_access(db, user, venue_id, svc.MANAGERS, lock=True)
    fingerprint = digest("apply", profile_id, data)
    replay = await prior(db, venue_id, data.request_key, fingerprint)
    if replay is not None:
        return ProfileApplyRead.model_validate(replay)
    profile = await profile_for(db, venue_id, profile_id)
    svc.check_version(profile.version, data.version)
    preview = await preview_for(db, profile, data.revision_id)
    if preview.fingerprint != data.fingerprint:
        raise HTTPException(
            409, "Grundriss oder Profil haben sich seit der Vorschau geändert. Erneut prüfen."
        )
    if preview.blocking_reasons:
        raise HTTPException(409, " ".join(preview.blocking_reasons))
    ids = [row.table_id for row in preview.rows]
    tables = list(
        (
            await db.execute(
                select(DiningTable)
                .where(DiningTable.venue_id == venue_id, DiningTable.id.in_(ids))
                .order_by(DiningTable.id)
                .with_for_update()
            )
        ).scalars()
    )
    saved = {row.table_id: row.saved for row in preview.rows}
    changed: list[uuid.UUID] = []
    for table in tables:
        target = saved[table.id]
        if (table.x, table.y) != (target.x, target.y):
            table.x, table.y = target.x, target.y
            table.version += 1
            changed.append(table.id)
    await db.flush()
    result = ProfileApplyRead(
        request_key=data.request_key,
        profile_id=profile.id,
        profile_version=profile.version,
        revision_id=preview.revision_id,
        positions=[position(table) for table in tables],
        changed_table_ids=changed,
    )
    await record(db, venue_id, user.id, data.request_key, fingerprint, "apply", profile.id, result)
    return result


@router.post(
    PREFIX + "/{profile_id}/archive",
    response_model=ProfileRead,
    status_code=201,
    summary="Grundrissprofil nachvollziehbar archivieren oder reaktivieren",
)
async def archive_profile(
    venue_id: uuid.UUID, profile_id: uuid.UUID, data: ProfileArchiveInput, user: Actor, db: DB
) -> ProfileRead:
    await svc.venue_access(db, user, venue_id, svc.MANAGERS, lock=True)
    fingerprint = digest("archive", profile_id, data)
    replay = await prior(db, venue_id, data.request_key, fingerprint)
    if replay is not None:
        return ProfileRead.model_validate(replay)
    profile = await profile_for(db, venue_id, profile_id)
    svc.check_version(profile.version, data.version)
    if profile.archived != data.archived:
        if not data.archived:
            await active_name(db, venue_id, profile.name, profile.id, growing=True)
        previous = await revision_for(db, profile)
        await next_revision(
            db,
            profile,
            name=profile.name,
            archived=data.archived,
            placements=[PositionRead.model_validate(row) for row in previous.placements],
            actor_id=user.id,
            previous=previous,
        )
    result = await profile_read(db, profile)
    await record(
        db, venue_id, user.id, data.request_key, fingerprint, "archive", profile.id, result
    )
    return result
