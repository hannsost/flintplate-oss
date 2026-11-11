"""Worker-facing equipment endpoints – /worker/equipment (Sprint 4.8)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from app.dependencies import DBSession, WorkerUser
from app.equipment.models import EquipmentAssignment, EquipmentItem
from app.equipment.schemas import EquipmentAssignmentRead, EquipmentItemRead

router = APIRouter()


async def _enrich(asgn: EquipmentAssignment, db: DBSession) -> EquipmentAssignmentRead:
    from app.users.models import User

    item_row = await db.execute(
        select(EquipmentItem).where(EquipmentItem.id == asgn.equipment_item_id)
    )
    item = item_row.scalar_one_or_none()

    worker_row = await db.execute(select(User).where(User.id == asgn.worker_id))
    worker = worker_row.scalar_one_or_none()

    assigner_name = None
    if asgn.assigned_by:
        a_row = await db.execute(select(User).where(User.id == asgn.assigned_by))
        a = a_row.scalar_one_or_none()
        assigner_name = (a.full_name or a.email) if a else None

    r = EquipmentAssignmentRead.model_validate(asgn)
    r.item = EquipmentItemRead.model_validate(item) if item else None
    r.worker_name = worker.full_name if worker else None
    r.worker_email = worker.email if worker else ""
    r.assigned_by_name = assigner_name
    return r


@router.get("", response_model=list[EquipmentAssignmentRead])
async def list_my_equipment(user: WorkerUser, db: DBSession) -> list[EquipmentAssignmentRead]:
    from app.worker.models import WorkerSettings

    ws_row = await db.execute(select(WorkerSettings).where(WorkerSettings.user_id == user.id))
    ws = ws_row.scalar_one_or_none()
    if ws and not ws.active_modules.get("equipment", True):
        raise HTTPException(status_code=403, detail="Ausrüstungs-Modul nicht aktiviert")

    # Only current assignments (not returned)
    stmt = (
        select(EquipmentAssignment)
        .where(
            EquipmentAssignment.worker_id == user.id,
            EquipmentAssignment.returned_at.is_(None),
        )
        .order_by(EquipmentAssignment.assigned_at.desc())
    )
    rows = await db.execute(stmt)
    assignments = list(rows.scalars().all())
    return [await _enrich(a, db) for a in assignments]


@router.get("/{assignment_id}", response_model=EquipmentAssignmentRead)
async def get_my_assignment(
    assignment_id: str, user: WorkerUser, db: DBSession
) -> EquipmentAssignmentRead:
    row = await db.execute(
        select(EquipmentAssignment).where(
            EquipmentAssignment.id == assignment_id,
            EquipmentAssignment.worker_id == user.id,
        )
    )
    asgn = row.scalar_one_or_none()
    if not asgn:
        raise HTTPException(status_code=404, detail="Zuweisung nicht gefunden")
    return await _enrich(asgn, db)
