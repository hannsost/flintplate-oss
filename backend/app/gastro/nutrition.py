"""Ingredients on the plate, markers on the guest, and one honest rule between them.

A dish declares what it contains. A guest carries markers: an allergy, a diet, a
condition. A marker names the ingredient tags it rules out. The check is the
intersection of the two, so a new diet is a new marker and needs no new code.

Only one conflict refuses an order: alcohol for someone recorded as a minor. That
is the law, not a preference. Everything else warns loudly and can be overruled by
a person who confirms it, because a stale note must never stop a guest from
ordering what they want.

Markers that touch health, pregnancy or belief are special categories. They use the
same recorded consent as the guest book, and without it they cannot be stored.
"""

from __future__ import annotations

import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.gastro import service as svc
from app.gastro.guestbook import profile_for
from app.gastro.models import DietMarker, GuestProfile, MenuItem
from app.gastro.router import DB, Actor, private_response
from app.gastro.schemas import Ingredient, MenuPayload

router = APIRouter(dependencies=[Depends(private_response)])

Kind = Literal["allergie", "diaet", "zustand"]

# A starter set a venue can take over and then edit. Deliberately small: the point
# is the mechanism, not a claim to cover every diet.
DEFAULTS: tuple[dict[str, object], ...] = (
    {
        "key": "minderjaehrig",
        "label": "Minderjährig",
        "kind": "zustand",
        "special": True,
        "legal_block": True,
        "avoid": ["alkohol"],
        "note": "Jugendschutz: Alkohol wird nicht ausgegeben, nicht nur angewarnt.",
    },
    {
        "key": "schwanger",
        "label": "Schwanger",
        "kind": "zustand",
        "special": True,
        "avoid": ["alkohol", "roh"],
        "note": "Hinweis auf Alkohol und rohe Zutaten.",
    },
    {
        "key": "vegan",
        "label": "Vegan",
        "kind": "diaet",
        "avoid": ["fleisch", "fisch", "meeresfruechte", "milch", "ei", "honig"],
    },
    {
        "key": "vegetarisch",
        "label": "Vegetarisch",
        "kind": "diaet",
        "avoid": ["fleisch", "fisch", "meeresfruechte"],
    },
    {
        "key": "halal",
        "label": "Halal",
        "kind": "diaet",
        "special": True,
        "avoid": ["schwein", "alkohol"],
        "note": "Religiös begründet, deshalb einwilligungspflichtig.",
    },
    {
        "key": "nussallergie",
        "label": "Nussallergie",
        "kind": "allergie",
        "special": True,
        "avoid": ["nuss", "erdnuss"],
    },
    {
        "key": "glutenfrei",
        "label": "Glutenunverträglichkeit",
        "kind": "allergie",
        "special": True,
        "avoid": ["gluten"],
    },
    {
        "key": "laktosefrei",
        "label": "Laktoseintoleranz",
        "kind": "allergie",
        "special": True,
        "avoid": ["milch", "laktose"],
    },
)


class MarkerInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: str = Field(min_length=2, max_length=40, pattern=r"^[a-z0-9_-]+$")
    label: str = Field(min_length=2, max_length=80)
    kind: Kind = "diaet"
    special: bool = False
    legal_block: bool = False
    avoid: list[str] = Field(default_factory=list, max_length=30)
    note: str = Field(default="", max_length=300)
    active: bool = True

    @field_validator("avoid")
    @classmethod
    def clean(cls, value: list[str]) -> list[str]:
        return sorted({entry.strip().lower() for entry in value if entry.strip()})


class MarkerUpdate(MarkerInput):
    version: int = Field(ge=1)


class MarkerRead(MarkerInput, BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    version: int


class MarkerAssignment(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: int = Field(ge=1)
    markers: list[str] = Field(default_factory=list, max_length=20)


class ItemDetail(BaseModel):
    """What the service reads out at the table."""

    id: uuid.UUID
    sku: str
    name: str
    description: str
    category: str
    station: str
    available: bool
    allergens: list[str]
    contains: list[str]
    ingredients: list[Ingredient]
    published: bool


class Verdict(BaseModel):
    item_id: uuid.UUID
    name: str
    state: Literal["ok", "warnung", "gesperrt"]
    reasons: list[str]
    markers: list[str]


class CheckInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    profile_id: uuid.UUID | None = None
    markers: list[str] = Field(default_factory=list, max_length=20)
    item_ids: list[uuid.UUID] = Field(default_factory=list, max_length=60)


class CheckResult(BaseModel):
    markers: list[MarkerRead]
    verdicts: list[Verdict]
    blocked: int
    warned: int


async def markers_of(db: AsyncSession, venue_id: uuid.UUID) -> dict[str, DietMarker]:
    rows = (
        (
            await db.execute(
                select(DietMarker).where(
                    DietMarker.venue_id == venue_id, DietMarker.active.is_(True)
                )
            )
        )
        .scalars()
        .all()
    )
    return {row.key: row for row in rows}


async def items_of(
    db: AsyncSession, venue_id: uuid.UUID, item_ids: list[uuid.UUID] | None = None
) -> list[MenuItem]:
    query = select(MenuItem).where(MenuItem.venue_id == venue_id)
    if item_ids:
        query = query.where(MenuItem.id.in_(item_ids))
    return list((await db.execute(query.order_by(MenuItem.sku))).scalars())


def payload_of(item: MenuItem) -> MenuPayload:
    return MenuPayload.model_validate(item.published or item.draft)


def judge(item: MenuItem, chosen: list[DietMarker]) -> Verdict:
    payload = payload_of(item)
    contains = set(payload.contains)
    reasons: list[str] = []
    hit: list[str] = []
    blocked = False
    for marker in chosen:
        overlap = sorted(contains & set(marker.avoid))
        if not overlap:
            continue
        hit.append(marker.key)
        reasons.append(f"{marker.label}: enthält {', '.join(overlap)}.")
        if marker.legal_block:
            blocked = True
    return Verdict(
        item_id=item.id,
        name=payload.name,
        state="gesperrt" if blocked else "warnung" if reasons else "ok",
        reasons=reasons,
        markers=hit,
    )


async def check(
    db: AsyncSession, venue_id: uuid.UUID, keys: list[str], item_ids: list[uuid.UUID] | None
) -> CheckResult:
    known = await markers_of(db, venue_id)
    chosen = [known[key] for key in keys if key in known]
    items = await items_of(db, venue_id, item_ids)
    verdicts = [judge(item, chosen) for item in items]
    return CheckResult(
        markers=[MarkerRead.model_validate(row) for row in chosen],
        verdicts=verdicts,
        blocked=sum(1 for row in verdicts if row.state == "gesperrt"),
        warned=sum(1 for row in verdicts if row.state == "warnung"),
    )


@router.get(
    "/venues/{venue_id}/diet-markers",
    response_model=list[MarkerRead],
    status_code=200,
    summary="Merkmale dieser Betriebsstätte",
)
async def markers(venue_id: uuid.UUID, user: Actor, db: DB) -> list[MarkerRead]:
    await svc.venue_access(db, user, venue_id, svc.SERVICE)
    rows = (
        (
            await db.execute(
                select(DietMarker)
                .where(DietMarker.venue_id == venue_id)
                .order_by(DietMarker.kind, DietMarker.label)
            )
        )
        .scalars()
        .all()
    )
    return [MarkerRead.model_validate(row) for row in rows]


@router.post(
    "/venues/{venue_id}/diet-markers",
    response_model=MarkerRead,
    status_code=201,
    summary="Eigenes Merkmal anlegen, etwa einen neuen Diättyp",
)
async def create_marker(venue_id: uuid.UUID, data: MarkerInput, user: Actor, db: DB) -> MarkerRead:
    await svc.venue_access(db, user, venue_id, svc.MANAGERS, lock=True)
    exists = (
        await db.execute(
            select(DietMarker.id).where(DietMarker.venue_id == venue_id, DietMarker.key == data.key)
        )
    ).first()
    if exists:
        raise HTTPException(409, "Ein Merkmal mit diesem Schlüssel existiert bereits.")
    row = DietMarker(venue_id=venue_id, **data.model_dump())
    db.add(row)
    await db.flush()
    svc.event(
        db, venue_id, "nutrition.marker_created", row.id, data.model_dump(mode="json"), user.id
    )
    return MarkerRead.model_validate(row)


@router.put(
    "/venues/{venue_id}/diet-markers/{marker_id}",
    response_model=MarkerRead,
    status_code=200,
    summary="Merkmal ändern",
)
async def update_marker(
    venue_id: uuid.UUID, marker_id: uuid.UUID, data: MarkerUpdate, user: Actor, db: DB
) -> MarkerRead:
    await svc.venue_access(db, user, venue_id, svc.MANAGERS, lock=True)
    row = (
        await db.execute(
            select(DietMarker)
            .where(DietMarker.id == marker_id, DietMarker.venue_id == venue_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, "Merkmal nicht gefunden.")
    svc.check_version(row.version, data.version)
    if data.key != row.key:
        raise HTTPException(422, "Der Schlüssel eines Merkmals bleibt unverändert.")
    for field, value in data.model_dump(exclude={"version", "key"}).items():
        setattr(row, field, value)
    row.version += 1
    svc.event(
        db, venue_id, "nutrition.marker_changed", row.id, data.model_dump(mode="json"), user.id
    )
    await db.flush()
    return MarkerRead.model_validate(row)


@router.post(
    "/venues/{venue_id}/diet-markers/defaults",
    response_model=list[MarkerRead],
    status_code=201,
    summary="Übliche Merkmale übernehmen und danach selbst anpassen",
)
async def seed(venue_id: uuid.UUID, user: Actor, db: DB) -> list[MarkerRead]:
    await svc.venue_access(db, user, venue_id, svc.MANAGERS, lock=True)
    known = {
        row
        for row in (await db.execute(select(DietMarker.key).where(DietMarker.venue_id == venue_id)))
        .scalars()
        .all()
    }
    created = []
    for entry in DEFAULTS:
        if entry["key"] in known:
            continue
        row = DietMarker(venue_id=venue_id, **entry)
        db.add(row)
        created.append(row)
    await db.flush()
    svc.event(
        db, venue_id, "nutrition.defaults_seeded", venue_id, {"created": len(created)}, user.id
    )
    return [MarkerRead.model_validate(row) for row in created]


@router.put(
    "/venues/{venue_id}/guestbook/{profile_id}/markers",
    status_code=200,
    response_model=list[str],
    summary="Merkmale eines Gastes setzen",
)
async def assign(
    venue_id: uuid.UUID, profile_id: uuid.UUID, data: MarkerAssignment, user: Actor, db: DB
) -> list[str]:
    await svc.venue_access(db, user, venue_id, svc.SERVICE)
    profile = await profile_for(db, venue_id, profile_id, lock=True)
    svc.check_version(profile.version, data.version)
    known = await markers_of(db, venue_id)
    unknown = [key for key in data.markers if key not in known]
    if unknown:
        raise HTTPException(404, f"Unbekanntes Merkmal: {', '.join(unknown)}.")
    needs_consent = [key for key in data.markers if known[key].special]
    if needs_consent and not profile.consent_special:
        labels = ", ".join(known[key].label for key in needs_consent)
        raise HTTPException(
            409,
            f"{labels} berührt Gesundheit, Schwangerschaft oder Glauben und braucht die "
            "ausdrückliche Einwilligung des Gastes.",
        )
    profile.markers = sorted(set(data.markers))
    profile.version += 1
    # The journal records that markers changed and how many, never which ones.
    svc.event(
        db,
        venue_id,
        "nutrition.guest_markers_changed",
        profile.id,
        {"count": len(profile.markers)},
        user.id,
    )
    await db.flush()
    return profile.markers


@router.post(
    "/venues/{venue_id}/menu-check",
    response_model=CheckResult,
    status_code=200,
    summary="Karte gegen die Merkmale eines Gastes prüfen",
)
async def menu_check(venue_id: uuid.UUID, data: CheckInput, user: Actor, db: DB) -> CheckResult:
    await svc.venue_access(db, user, venue_id, svc.SERVICE)
    keys = list(data.markers)
    if data.profile_id is not None:
        profile = await profile_for(db, venue_id, data.profile_id)
        keys = sorted(set(keys) | set(profile.markers))
    return await check(db, venue_id, keys, data.item_ids or None)


@router.get(
    "/venues/{venue_id}/menu/{item_id}/details",
    response_model=ItemDetail,
    status_code=200,
    summary="Zutaten eines Gerichts für Rückfragen am Tisch",
)
async def details(venue_id: uuid.UUID, item_id: uuid.UUID, user: Actor, db: DB) -> ItemDetail:
    await svc.venue_access(db, user, venue_id, svc.SERVICE)
    item = await svc.menu_for_venue(db, venue_id, item_id)
    payload = payload_of(item)
    return ItemDetail(
        id=item.id,
        sku=item.sku,
        name=payload.name,
        description=payload.description,
        category=payload.category,
        station=payload.station,
        available=payload.available,
        allergens=payload.allergens,
        contains=payload.contains,
        ingredients=payload.ingredients,
        published=item.published is not None,
    )


async def guest_guard(
    db: AsyncSession,
    venue_id: uuid.UUID,
    profile: GuestProfile | None,
    item_ids: list[uuid.UUID],
    accepted: bool,
) -> None:
    """The guest app enforces what the profile says; the service decides in person."""
    if profile is None or not profile.markers:
        return
    result = await check(db, venue_id, list(profile.markers), item_ids)
    blocked = [row for row in result.verdicts if row.state == "gesperrt"]
    if blocked:
        raise HTTPException(
            409,
            "Nicht möglich: "
            + " ".join(f"{row.name} – {' '.join(row.reasons)}" for row in blocked),
        )
    warned = [row for row in result.verdicts if row.state == "warnung"]
    if warned and not accepted:
        raise HTTPException(
            409,
            "Bitte bestätigen: "
            + " ".join(f"{row.name} – {' '.join(row.reasons)}" for row in warned),
        )
