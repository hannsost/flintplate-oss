"""Zeitarbeit endpoints – Sprint 1.7.

Mounted at /zeitarbeit
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.security import get_current_user
from app.users.models import User
from app.zeitarbeit.models import WorkAssignment
from app.zeitarbeit.schemas import (
    AssignmentCreate,
    AssignmentRead,
    AssignmentUpdate,
    AvailabilityRead,
    AvailabilityUpsert,
    CanvasAssignPayload,
    DispositionRead,
    DispositionUpdate,
    JobCanvasRead,
    PoolWorkerRead,
    WorkerCanvasRead,
    ZeitarbeitStats,
)
from app.zeitarbeit.service import (
    canvas_assign,
    canvas_job_view,
    canvas_worker_view,
    create_assignment,
    delete_assignment,
    get_assignment,
    get_availability,
    get_dispositions,
    get_zeitarbeit_stats,
    list_assignments,
    list_canvas_pool_workers,
    list_pool_workers,
    run_matching,
    update_assignment,
    update_disposition,
    upsert_availability,
)

router = APIRouter()


def _require_recruiter(user: User) -> User:
    if user.role not in {"recruiter", "admin"}:
        raise HTTPException(status_code=403, detail="Nur für Recruiter.")
    if user.tenant_id is None:
        raise HTTPException(status_code=403, detail="Keine Organisation zugewiesen.")
    return user


async def _get_own_assignment(
    assignment_id: uuid.UUID,
    current_user: User,
    db: AsyncSession,
) -> WorkAssignment:
    a = await get_assignment(db, assignment_id)
    if not a:
        raise HTTPException(status_code=404, detail="Auftrag nicht gefunden.")
    if a.recruiter_id != current_user.id:
        raise HTTPException(status_code=403, detail="Kein Zugriff.")
    return a


# ── Assignments ───────────────────────────────────────────────────────────────


@router.post(
    "/orders",
    response_model=AssignmentRead,
    status_code=status.HTTP_201_CREATED,
    summary="Neuen Auftrag anlegen",
)
async def create(
    data: AssignmentCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> AssignmentRead:
    _require_recruiter(current_user)
    return await create_assignment(db, current_user.id, data)


@router.get(
    "/orders",
    response_model=list[AssignmentRead],
    summary="Eigene Aufträge abrufen",
)
async def list_my(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    status: str | None = None,
) -> list[AssignmentRead]:
    _require_recruiter(current_user)
    return await list_assignments(db, current_user.id, status)


@router.get(
    "/orders/stats",
    response_model=ZeitarbeitStats,
    summary="Zeitarbeit-KPIs",
)
async def stats(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ZeitarbeitStats:
    _require_recruiter(current_user)
    return await get_zeitarbeit_stats(db, current_user.id)


@router.get(
    "/orders/{assignment_id}",
    response_model=AssignmentRead,
    summary="Auftrag abrufen",
)
async def get_one(
    assignment_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> AssignmentRead:
    _require_recruiter(current_user)
    a = await _get_own_assignment(assignment_id, current_user, db)
    return AssignmentRead.model_validate(a)


@router.patch(
    "/orders/{assignment_id}",
    response_model=AssignmentRead,
    summary="Auftrag aktualisieren",
)
async def update(
    assignment_id: uuid.UUID,
    data: AssignmentUpdate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> AssignmentRead:
    _require_recruiter(current_user)
    a = await _get_own_assignment(assignment_id, current_user, db)
    return await update_assignment(db, a, data)


@router.delete(
    "/orders/{assignment_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Auftrag löschen",
)
async def delete(
    assignment_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    _require_recruiter(current_user)
    a = await _get_own_assignment(assignment_id, current_user, db)
    await delete_assignment(db, a)


# ── Dispositions engine ───────────────────────────────────────────────────────


@router.post(
    "/orders/{assignment_id}/match",
    response_model=list[DispositionRead],
    summary="KI-Matching ausführen",
)
async def match(
    assignment_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[DispositionRead]:
    _require_recruiter(current_user)
    a = await _get_own_assignment(assignment_id, current_user, db)
    return await run_matching(db, a)


@router.get(
    "/orders/{assignment_id}/dispositions",
    response_model=list[DispositionRead],
    summary="Dispositions für Auftrag abrufen",
)
async def list_dispositions(
    assignment_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[DispositionRead]:
    _require_recruiter(current_user)
    await _get_own_assignment(assignment_id, current_user, db)
    return await get_dispositions(db, assignment_id)


@router.patch(
    "/orders/{assignment_id}/dispositions/{worker_id}",
    response_model=DispositionRead,
    summary="Disposition-Status aktualisieren",
)
async def update_disp(
    assignment_id: uuid.UUID,
    worker_id: uuid.UUID,
    data: DispositionUpdate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> DispositionRead:
    _require_recruiter(current_user)
    await _get_own_assignment(assignment_id, current_user, db)
    result = await update_disposition(db, assignment_id, worker_id, data)
    if not result:
        raise HTTPException(status_code=404, detail="Disposition nicht gefunden.")
    return result


# ── Pool / Availability ───────────────────────────────────────────────────────


@router.get(
    "/pool",
    response_model=list[AvailabilityRead],
    summary="Verfügbare Zeitarbeiter im Pool",
)
async def pool(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[AvailabilityRead]:
    _require_recruiter(current_user)
    return await list_pool_workers(db, tenant_id=current_user.tenant_id)


@router.get(
    "/availability/me",
    response_model=AvailabilityRead | None,
    summary="Eigene Verfügbarkeit abrufen (Kandidat)",
)
async def my_availability(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> AvailabilityRead | None:
    return await get_availability(db, current_user.id)


@router.put(
    "/availability/me",
    response_model=AvailabilityRead,
    summary="Eigene Verfügbarkeit setzen (Kandidat)",
)
async def set_availability(
    data: AvailabilityUpsert,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> AvailabilityRead:
    return await upsert_availability(db, current_user.id, data)


# ── Workforce Canvas ────────────────────────────────────────────────────────────


@router.get(
    "/canvas/pool",
    response_model=list[PoolWorkerRead],
    summary="Canvas: Pool-Worker mit Name, Headline und Skills",
)
async def canvas_pool(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[PoolWorkerRead]:
    _require_recruiter(current_user)
    return await list_canvas_pool_workers(db, tenant_id=current_user.tenant_id)


@router.get(
    "/canvas/job/{assignment_id}",
    response_model=JobCanvasRead,
    summary="Canvas: Job-first Perspektive",
)
async def canvas_job(
    assignment_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> JobCanvasRead:
    _require_recruiter(current_user)
    await _get_own_assignment(assignment_id, current_user, db)
    result = await canvas_job_view(db, assignment_id)
    if not result:
        raise HTTPException(status_code=404, detail="Auftrag nicht gefunden.")
    return result


@router.get(
    "/canvas/worker/{worker_id}",
    response_model=WorkerCanvasRead,
    summary="Canvas: Worker-first Perspektive",
)
async def canvas_worker(
    worker_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> WorkerCanvasRead:
    _require_recruiter(current_user)
    result = await canvas_worker_view(db, worker_id, current_user.id)
    if not result:
        raise HTTPException(status_code=404, detail="Worker nicht im Pool.")
    return result


@router.post(
    "/canvas/assign",
    response_model=DispositionRead,
    status_code=status.HTTP_201_CREATED,
    summary="Canvas: Worker auf Auftrag zuweisen (Drag-drop)",
)
async def canvas_assign_endpoint(
    payload: CanvasAssignPayload,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> DispositionRead:
    _require_recruiter(current_user)
    await _get_own_assignment(payload.assignment_id, current_user, db)
    result = await canvas_assign(db, payload)
    if not result:
        raise HTTPException(status_code=400, detail="Zuweisung fehlgeschlagen.")
    return result
