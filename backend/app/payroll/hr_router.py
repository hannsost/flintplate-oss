"""HR payroll management endpoints – /zeitarbeit/payroll (Sprint 4.10)."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.dependencies import DBSession, TenantRecruiterUser
from app.payroll.models import PayStub
from app.payroll.schemas import PayStubCreate, PayStubRead, PayStubUpdate
from app.worker.access import require_member

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
async def list_pay_stubs(
    user: TenantRecruiterUser,
    db: DBSession,
    worker_id: str | None = Query(None),
    year: int | None = Query(None),
    status: str | None = Query(None),
) -> list[PayStubRead]:
    stmt = select(PayStub).where(PayStub.tenant_id == user.tenant_id)
    if worker_id:
        stmt = stmt.where(PayStub.worker_id == worker_id)
    if year:
        stmt = stmt.where(PayStub.period_year == year)
    if status:
        stmt = stmt.where(PayStub.status == status)
    stmt = stmt.order_by(PayStub.period_year.desc(), PayStub.period_month.desc())
    rows = await db.execute(stmt)
    stubs = list(rows.scalars().all())
    return [await _enrich(s, db) for s in stubs]


@router.post("", response_model=PayStubRead, status_code=201)
async def create_pay_stub(
    body: PayStubCreate, user: TenantRecruiterUser, db: DBSession
) -> PayStubRead:
    await require_member(db, user.tenant_id, body.worker_id)
    stub = PayStub(
        tenant_id=user.tenant_id,
        worker_id=body.worker_id,
        created_by=user.id,
        period_year=body.period_year,
        period_month=body.period_month,
        gross_cents=body.gross_cents,
        net_cents=body.net_cents,
        tax_cents=body.tax_cents,
        social_security_cents=body.social_security_cents,
        hours_worked=body.hours_worked,
        overtime_hours=body.overtime_hours,
        document_url=body.document_url,
        notes=body.notes,
        status="draft",
    )
    db.add(stub)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=409,
            detail=f"Lohnabrechnung für {body.period_month}/{body.period_year} existiert bereits",
        ) from None
    await db.refresh(stub)
    return await _enrich(stub, db)


@router.get("/{stub_id}", response_model=PayStubRead)
async def get_pay_stub(stub_id: str, user: TenantRecruiterUser, db: DBSession) -> PayStubRead:
    row = await db.execute(
        select(PayStub).where(PayStub.id == stub_id, PayStub.tenant_id == user.tenant_id)
    )
    stub = row.scalar_one_or_none()
    if not stub:
        raise HTTPException(status_code=404, detail="Lohnabrechnung nicht gefunden")
    return await _enrich(stub, db)


@router.patch("/{stub_id}", response_model=PayStubRead)
async def update_pay_stub(
    stub_id: str, body: PayStubUpdate, user: TenantRecruiterUser, db: DBSession
) -> PayStubRead:
    row = await db.execute(
        select(PayStub).where(PayStub.id == stub_id, PayStub.tenant_id == user.tenant_id)
    )
    stub = row.scalar_one_or_none()
    if not stub:
        raise HTTPException(status_code=404, detail="Lohnabrechnung nicht gefunden")
    if stub.status == "published":
        raise HTTPException(
            status_code=409, detail="Veröffentlichte Abrechnungen können nicht bearbeitet werden"
        )
    changes = body.model_dump(exclude_none=True)
    if changes.get("net_cents", stub.net_cents) > changes.get("gross_cents", stub.gross_cents):
        raise HTTPException(
            status_code=422, detail="Der Nettobetrag darf den Bruttobetrag nicht überschreiten."
        )
    for field, value in changes.items():
        setattr(stub, field, value)
    stub.updated_at = datetime.now()
    await db.commit()
    await db.refresh(stub)
    return await _enrich(stub, db)


@router.post("/{stub_id}/publish", response_model=PayStubRead)
async def publish_pay_stub(stub_id: str, user: TenantRecruiterUser, db: DBSession) -> PayStubRead:
    row = await db.execute(
        select(PayStub).where(PayStub.id == stub_id, PayStub.tenant_id == user.tenant_id)
    )
    stub = row.scalar_one_or_none()
    if not stub:
        raise HTTPException(status_code=404, detail="Lohnabrechnung nicht gefunden")
    if stub.status == "published":
        raise HTTPException(status_code=409, detail="Bereits veröffentlicht")
    now = datetime.now()
    stub.status = "published"
    stub.published_at = now
    stub.updated_at = now
    await db.commit()
    await db.refresh(stub)
    return await _enrich(stub, db)


@router.delete("/{stub_id}", status_code=204)
async def delete_pay_stub(stub_id: str, user: TenantRecruiterUser, db: DBSession) -> None:
    row = await db.execute(
        select(PayStub).where(PayStub.id == stub_id, PayStub.tenant_id == user.tenant_id)
    )
    stub = row.scalar_one_or_none()
    if not stub:
        raise HTTPException(status_code=404, detail="Lohnabrechnung nicht gefunden")
    if stub.status == "published":
        raise HTTPException(
            status_code=409, detail="Veröffentlichte Abrechnungen können nicht gelöscht werden"
        )
    await db.delete(stub)
    await db.commit()
