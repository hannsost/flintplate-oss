"""Worker-facing payroll endpoints – /worker/payroll (Sprint 4.10)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select

from app.dependencies import DBSession, WorkerUser
from app.payroll.models import PayStub
from app.payroll.schemas import PayStubRead

router = APIRouter()


async def _enrich(stub: PayStub, db: DBSession) -> PayStubRead:
    from app.users.models import User

    row = await db.execute(select(User).where(User.id == stub.worker_id))
    worker = row.scalar_one_or_none()
    r = PayStubRead.model_validate(stub)
    r.worker_name = worker.full_name if worker else None
    r.worker_email = worker.email if worker else ""
    return r


@router.get("", response_model=list[PayStubRead])
async def list_my_pay_stubs(
    user: WorkerUser,
    db: DBSession,
    year: int | None = Query(None),
) -> list[PayStubRead]:
    from app.worker.models import WorkerSettings

    ws_row = await db.execute(select(WorkerSettings).where(WorkerSettings.user_id == user.id))
    ws = ws_row.scalar_one_or_none()
    if ws and not ws.active_modules.get("payroll", True):
        raise HTTPException(status_code=403, detail="Lohnabrechnung-Modul nicht aktiviert")

    stmt = select(PayStub).where(
        PayStub.worker_id == user.id,
        PayStub.status == "published",
    )
    if year:
        stmt = stmt.where(PayStub.period_year == year)
    stmt = stmt.order_by(PayStub.period_year.desc(), PayStub.period_month.desc())
    rows = await db.execute(stmt)
    stubs = list(rows.scalars().all())
    return [await _enrich(s, db) for s in stubs]


@router.get("/{stub_id}", response_model=PayStubRead)
async def get_my_pay_stub(stub_id: str, user: WorkerUser, db: DBSession) -> PayStubRead:
    row = await db.execute(
        select(PayStub).where(
            PayStub.id == stub_id,
            PayStub.worker_id == user.id,
            PayStub.status == "published",
        )
    )
    stub = row.scalar_one_or_none()
    if not stub:
        raise HTTPException(status_code=404, detail="Lohnabrechnung nicht gefunden")
    return await _enrich(stub, db)
