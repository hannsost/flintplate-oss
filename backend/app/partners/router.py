from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin.models import Customer
from app.companies.branding import own_customer
from app.companies.workspace_access import workspace_admin, workspace_user
from app.database import get_db
from app.partners.models import PartnerEvent, Partnership, SharedDemand
from app.users.models import User

router = APIRouter()
DB = Annotated[AsyncSession, Depends(get_db)]
HR = Annotated[User, Depends(workspace_user)]
Admin = Annotated[User, Depends(workspace_admin)]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Invite(Strict):
    target_slug: str = Field(min_length=1, max_length=100)
    purpose: str = Field(min_length=5, max_length=500)


class Decision(Strict):
    version: int = Field(ge=1)
    action: Literal["accept", "revoke"]


class PartnershipRead(BaseModel):
    id: UUID
    partner_name: str
    purpose: str
    status: str
    version: int
    incoming: bool
    can_manage: bool


class DemandInput(Strict):
    title: str = Field(min_length=1, max_length=120)
    location: str = Field(min_length=1, max_length=120)
    required_skills: list[str] = Field(default_factory=list, max_length=30)
    starts_on: date
    headcount: int = Field(ge=1, le=500)

    @field_validator("required_skills")
    @classmethod
    def skills(cls, value: list[str]) -> list[str]:
        if any(not s.strip() or len(s) > 100 for s in value):
            raise ValueError("Fähigkeiten müssen 1 bis 100 Zeichen enthalten.")
        return list(dict.fromkeys(s.strip() for s in value))


class DemandRead(DemandInput):
    id: UUID
    version: int
    status: str
    offered_count: int
    own: bool


class Capacity(Strict):
    version: int = Field(ge=1)
    offered_count: int = Field(ge=0, le=500)


class Close(Strict):
    version: int = Field(ge=1)


class EventRead(BaseModel):
    action: str
    detail: str
    actor_id: UUID | None
    created_at: datetime
    model_config = {"from_attributes": True}


def record(db: AsyncSession, p: Partnership, user: User, action: str, detail: str = "") -> None:
    db.add(
        PartnerEvent(
            partnership_id=p.id,
            actor_id=user.id,
            action=action,
            detail=detail,
            created_at=datetime.now(UTC),
        )
    )


async def require_partner(
    db: AsyncSession, pid: UUID, user: User, active: bool = False
) -> Partnership:
    await own_customer(db, user)
    p = await db.scalar(
        select(Partnership)
        .where(
            Partnership.id == pid,
            or_(
                Partnership.initiator_id == user.tenant_id,
                Partnership.recipient_id == user.tenant_id,
            ),
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if p is None:
        raise HTTPException(404, "Kooperation nicht gefunden.")
    if active:
        statuses = (
            await db.scalars(
                select(Customer.status).where(Customer.id.in_([p.initiator_id, p.recipient_id]))
            )
        ).all()
        if p.status != "active" or any(s not in {"active", "trial"} for s in statuses):
            raise HTTPException(403, "Kooperation ist nicht aktiv.")
    return p


async def read_partner(db: AsyncSession, p: Partnership, user: User) -> PartnershipRead:
    other = p.recipient_id if p.initiator_id == user.tenant_id else p.initiator_id
    name = await db.scalar(select(Customer.name).where(Customer.id == other))
    return PartnershipRead(
        id=p.id,
        partner_name=name or "Unternehmen",
        purpose=p.purpose,
        status=p.status,
        version=p.version,
        incoming=p.recipient_id == user.tenant_id,
        can_manage=user.role == "admin",
    )


def read_demand(d: SharedDemand, user: User) -> DemandRead:
    return DemandRead(
        id=d.id,
        version=d.version,
        title=d.title,
        location=d.location,
        required_skills=d.required_skills,
        starts_on=d.starts_on,
        headcount=d.headcount,
        offered_count=d.offered_count,
        status=d.status,
        own=d.owner_id == user.tenant_id,
    )


@router.get(
    "", response_model=list[PartnershipRead], status_code=200, summary="Eigene Firmenkooperationen"
)
async def list_partners(user: HR, db: DB) -> list[PartnershipRead]:
    await own_customer(db, user)
    rows = await db.scalars(
        select(Partnership)
        .where(
            or_(
                Partnership.initiator_id == user.tenant_id,
                Partnership.recipient_id == user.tenant_id,
            )
        )
        .order_by(Partnership.created_at.desc())
        .limit(100)
    )
    return [await read_partner(db, p, user) for p in rows]


@router.post(
    "",
    response_model=PartnershipRead,
    status_code=201,
    summary="Kooperation bei einer bestimmten Firma anfragen",
)
async def invite(data: Invite, user: Admin, db: DB) -> PartnershipRead:
    await own_customer(db, user)
    target = await db.scalar(
        select(Customer).where(
            Customer.slug == data.target_slug, Customer.status.in_(["active", "trial"])
        )
    )
    if target is None:
        raise HTTPException(404, "Arbeitsbereich nicht gefunden.")
    if target.id == user.tenant_id:
        raise HTTPException(422, "Bitte einen anderen Firmenarbeitsbereich wählen.")
    pair = ":".join(sorted([str(target.id), str(user.tenant_id)]))
    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
        {"key": f"partnership:{pair}"},
    )
    if await db.scalar(
        select(Partnership.id).where(
            Partnership.pair_key == pair, Partnership.status.in_(["pending", "active"])
        )
    ):
        raise HTTPException(
            409, "Zwischen diesen Firmen besteht bereits eine Anfrage oder Kooperation."
        )
    p = Partnership(
        initiator_id=user.tenant_id, recipient_id=target.id, pair_key=pair, purpose=data.purpose
    )
    db.add(p)
    await db.flush()
    record(db, p, user, "requested")
    return await read_partner(db, p, user)


@router.post(
    "/{pid}/decision",
    response_model=PartnershipRead,
    status_code=200,
    summary="Kooperation annehmen oder Zugriff widerrufen",
)
async def decision(pid: UUID, data: Decision, user: Admin, db: DB) -> PartnershipRead:
    p = await require_partner(db, pid, user)
    if p.version != data.version or p.status == "revoked":
        raise HTTPException(409, "Kooperation wurde bereits geändert.")
    if data.action == "accept":
        if p.recipient_id != user.tenant_id or p.status != "pending":
            raise HTTPException(403, "Nur die angefragte Firma kann eine offene Anfrage annehmen.")
        p.status = "active"
    else:
        p.status = "revoked"
    p.version += 1
    record(db, p, user, data.action)
    return await read_partner(db, p, user)


@router.get(
    "/{pid}/demands",
    response_model=list[DemandRead],
    status_code=200,
    summary="Gemeinsam freigegebene Personalbedarfe",
)
async def demands(pid: UUID, user: HR, db: DB) -> list[DemandRead]:
    await require_partner(db, pid, user, active=True)
    rows = await db.scalars(
        select(SharedDemand)
        .where(SharedDemand.partnership_id == pid)
        .order_by(SharedDemand.created_at.desc())
        .limit(100)
    )
    return [read_demand(d, user) for d in rows]


@router.post(
    "/{pid}/demands",
    response_model=DemandRead,
    status_code=201,
    summary="Bedarf ohne Bewerberprofile mit Partner teilen",
)
async def share_demand(pid: UUID, data: DemandInput, user: HR, db: DB) -> DemandRead:
    p = await require_partner(db, pid, user, active=True)
    d = SharedDemand(partnership_id=pid, owner_id=user.tenant_id, **data.model_dump())
    db.add(d)
    await db.flush()
    record(db, p, user, "demand_shared", str(d.id))
    return read_demand(d, user)


async def require_demand(db: AsyncSession, pid: UUID, did: UUID, version: int) -> SharedDemand:
    d = await db.scalar(
        select(SharedDemand)
        .where(SharedDemand.id == did, SharedDemand.partnership_id == pid)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if d is None:
        raise HTTPException(404, "Bedarf nicht gefunden.")
    if d.version != version or d.status != "open":
        raise HTTPException(409, "Bedarf wurde bereits geändert oder geschlossen.")
    return d


@router.put(
    "/{pid}/demands/{did}/capacity",
    response_model=DemandRead,
    status_code=200,
    summary="Partnerkapazität unverbindlich anbieten",
)
async def capacity(pid: UUID, did: UUID, data: Capacity, user: HR, db: DB) -> DemandRead:
    p = await require_partner(db, pid, user, active=True)
    d = await require_demand(db, pid, did, data.version)
    if d.owner_id == user.tenant_id:
        raise HTTPException(403, "Kapazität muss von der Partnerfirma angeboten werden.")
    if data.offered_count > d.headcount:
        raise HTTPException(422, "Angebotene Kapazität darf den Bedarf nicht überschreiten.")
    d.offered_count = data.offered_count
    d.version += 1
    record(db, p, user, "capacity_offered", f"{d.id}: {data.offered_count}")
    return read_demand(d, user)


@router.post(
    "/{pid}/demands/{did}/close",
    response_model=DemandRead,
    status_code=200,
    summary="Eigenen geteilten Bedarf schließen",
)
async def close(pid: UUID, did: UUID, data: Close, user: HR, db: DB) -> DemandRead:
    p = await require_partner(db, pid, user, active=True)
    d = await require_demand(db, pid, did, data.version)
    if d.owner_id != user.tenant_id:
        raise HTTPException(403, "Nur die anfragende Firma kann den Bedarf schließen.")
    d.status = "closed"
    d.version += 1
    record(db, p, user, "demand_closed", str(d.id))
    return read_demand(d, user)


@router.get(
    "/{pid}/events",
    response_model=list[EventRead],
    status_code=200,
    summary="Verlauf einer Kooperation",
)
async def events(pid: UUID, user: HR, db: DB) -> list[EventRead]:
    await require_partner(db, pid, user)
    rows = await db.scalars(
        select(PartnerEvent)
        .where(PartnerEvent.partnership_id == pid)
        .order_by(PartnerEvent.created_at.desc())
        .limit(100)
    )
    return [EventRead.model_validate(e) for e in rows]
