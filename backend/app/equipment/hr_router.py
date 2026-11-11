"""HR equipment management endpoints – /zeitarbeit/equipment (Sprint 4.8)."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select

from app.dependencies import DBSession, TenantRecruiterUser
from app.equipment.models import (
    EQUIPMENT_CATEGORIES,
    EQUIPMENT_STATUSES,
    EquipmentAssignment,
    EquipmentItem,
)
from app.equipment.schemas import (
    AssignItemRequest,
    EquipmentAssignmentRead,
    EquipmentItemCreate,
    EquipmentItemRead,
    EquipmentItemUpdate,
    ReturnItemRequest,
)
from app.worker.access import require_member

router = APIRouter()


async def _enrich_assignment(asgn: EquipmentAssignment, db: DBSession) -> EquipmentAssignmentRead:
    from app.users.models import User

    item_row = await db.execute(
        select(EquipmentItem).where(EquipmentItem.id == asgn.equipment_item_id)
    )
    item = item_row.scalar_one_or_none()

    user_ids = {str(asgn.worker_id)}
    if asgn.assigned_by:
        user_ids.add(str(asgn.assigned_by))
    u_rows = await db.execute(select(User).where(User.id.in_(user_ids)))
    users = {str(u.id): u for u in u_rows.scalars()}

    worker = users.get(str(asgn.worker_id))
    assigner = users.get(str(asgn.assigned_by)) if asgn.assigned_by else None

    r = EquipmentAssignmentRead.model_validate(asgn)
    r.item = EquipmentItemRead.model_validate(item) if item else None
    r.worker_name = worker.full_name if worker else None
    r.worker_email = worker.email if worker else ""
    r.assigned_by_name = (assigner.full_name or assigner.email) if assigner else None
    return r


# ── Items ─────────────────────────────────────────────────────────────────────


@router.get("", response_model=list[EquipmentItemRead])
async def list_items(
    user: TenantRecruiterUser,
    db: DBSession,
    status: str | None = Query(None),
    category: str | None = Query(None),
) -> list[EquipmentItemRead]:
    stmt = select(EquipmentItem).where(EquipmentItem.tenant_id == user.tenant_id)
    if status:
        if status not in EQUIPMENT_STATUSES:
            raise HTTPException(
                status_code=422, detail=f"status must be one of {EQUIPMENT_STATUSES}"
            )
        stmt = stmt.where(EquipmentItem.status == status)
    if category:
        stmt = stmt.where(EquipmentItem.category == category)
    stmt = stmt.order_by(EquipmentItem.created_at.desc())
    rows = await db.execute(stmt)
    return [EquipmentItemRead.model_validate(i) for i in rows.scalars()]


@router.post("", response_model=EquipmentItemRead, status_code=201)
async def create_item(
    body: EquipmentItemCreate, user: TenantRecruiterUser, db: DBSession
) -> EquipmentItemRead:
    if body.category not in EQUIPMENT_CATEGORIES:
        raise HTTPException(
            status_code=422, detail=f"category must be one of {EQUIPMENT_CATEGORIES}"
        )
    item = EquipmentItem(
        tenant_id=user.tenant_id,
        name=body.name,
        category=body.category,
        serial_number=body.serial_number,
        asset_tag=body.asset_tag,
        condition=body.condition,
        description=body.description,
        notes=body.notes,
        status="available",
    )
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return EquipmentItemRead.model_validate(item)


@router.get("/{item_id}", response_model=EquipmentItemRead)
async def get_item(item_id: str, user: TenantRecruiterUser, db: DBSession) -> EquipmentItemRead:
    row = await db.execute(
        select(EquipmentItem).where(
            EquipmentItem.id == item_id, EquipmentItem.tenant_id == user.tenant_id
        )
    )
    item = row.scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="Ausrüstungsgegenstand nicht gefunden")
    return EquipmentItemRead.model_validate(item)


@router.patch("/{item_id}", response_model=EquipmentItemRead)
async def update_item(
    item_id: str, body: EquipmentItemUpdate, user: TenantRecruiterUser, db: DBSession
) -> EquipmentItemRead:
    row = await db.execute(
        select(EquipmentItem).where(
            EquipmentItem.id == item_id, EquipmentItem.tenant_id == user.tenant_id
        )
    )
    item = row.scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="Ausrüstungsgegenstand nicht gefunden")
    for field, value in body.model_dump(exclude_none=True).items():
        setattr(item, field, value)
    item.updated_at = datetime.now()
    await db.commit()
    await db.refresh(item)
    return EquipmentItemRead.model_validate(item)


@router.delete("/{item_id}", status_code=204)
async def delete_item(item_id: str, user: TenantRecruiterUser, db: DBSession) -> None:
    row = await db.execute(
        select(EquipmentItem).where(
            EquipmentItem.id == item_id, EquipmentItem.tenant_id == user.tenant_id
        )
    )
    item = row.scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="Ausrüstungsgegenstand nicht gefunden")
    if item.status == "assigned":
        raise HTTPException(status_code=409, detail="Ausrüstung ist noch zugewiesen")
    await db.delete(item)
    await db.commit()


# ── Assignments ───────────────────────────────────────────────────────────────


@router.get("/assignments/list", response_model=list[EquipmentAssignmentRead])
async def list_assignments(
    user: TenantRecruiterUser,
    db: DBSession,
    worker_id: str | None = Query(None),
    active_only: bool = Query(True),
) -> list[EquipmentAssignmentRead]:
    stmt = select(EquipmentAssignment).where(EquipmentAssignment.tenant_id == user.tenant_id)
    if worker_id:
        stmt = stmt.where(EquipmentAssignment.worker_id == worker_id)
    if active_only:
        stmt = stmt.where(EquipmentAssignment.returned_at.is_(None))
    stmt = stmt.order_by(EquipmentAssignment.assigned_at.desc())
    rows = await db.execute(stmt)
    assignments = list(rows.scalars().all())
    return [await _enrich_assignment(a, db) for a in assignments]


@router.post("/{item_id}/assign", response_model=EquipmentAssignmentRead, status_code=201)
async def assign_item(
    item_id: str, body: AssignItemRequest, user: TenantRecruiterUser, db: DBSession
) -> EquipmentAssignmentRead:
    await require_member(db, user.tenant_id, body.worker_id)
    row = await db.execute(
        select(EquipmentItem).where(
            EquipmentItem.id == item_id, EquipmentItem.tenant_id == user.tenant_id
        )
    )
    item = row.scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="Ausrüstungsgegenstand nicht gefunden")
    if item.status == "assigned":
        raise HTTPException(status_code=409, detail="Ausrüstung ist bereits zugewiesen")
    if item.status == "retired":
        raise HTTPException(status_code=409, detail="Ausrüstung ist ausgemustert")

    asgn = EquipmentAssignment(
        equipment_item_id=item.id,
        worker_id=body.worker_id,
        tenant_id=user.tenant_id,
        assigned_by=user.id,
        assigned_at=body.assigned_at,
        notes=body.notes,
    )
    item.status = "assigned"
    item.updated_at = datetime.now()
    db.add(asgn)
    await db.commit()
    await db.refresh(asgn)
    return await _enrich_assignment(asgn, db)


@router.post("/{item_id}/return", response_model=EquipmentAssignmentRead)
async def return_item(
    item_id: str, body: ReturnItemRequest, user: TenantRecruiterUser, db: DBSession
) -> EquipmentAssignmentRead:
    # Find the active assignment for this item
    row = await db.execute(
        select(EquipmentAssignment).where(
            EquipmentAssignment.equipment_item_id == item_id,
            EquipmentAssignment.tenant_id == user.tenant_id,
            EquipmentAssignment.returned_at.is_(None),
        )
    )
    asgn = row.scalar_one_or_none()
    if not asgn:
        raise HTTPException(status_code=404, detail="Keine aktive Zuweisung gefunden")

    item_row = await db.execute(select(EquipmentItem).where(EquipmentItem.id == item_id))
    item = item_row.scalar_one_or_none()

    asgn.returned_at = body.returned_at
    if body.notes:
        asgn.notes = (asgn.notes or "") + f"\nRückgabe: {body.notes}"
    asgn.updated_at = datetime.now()

    if item:
        item.status = "available"
        item.updated_at = datetime.now()

    await db.commit()
    await db.refresh(asgn)
    return await _enrich_assignment(asgn, db)
