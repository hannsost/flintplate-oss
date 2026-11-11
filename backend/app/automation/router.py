from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.automation.models import ProcessRun, ProcessTemplate
from app.automation.schemas import (
    Review,
    RunRead,
    StartRun,
    Step,
    TemplateInput,
    TemplateRead,
    TemplateUpdate,
)
from app.automation.service import (
    advance,
    apply_step,
    event,
    job_source,
    mark_result,
    owned_job,
    read_run,
)
from app.companies.branding import own_customer
from app.companies.workspace_access import workspace_admin, workspace_user
from app.database import get_db
from app.users.models import User

router = APIRouter()
DB = Annotated[AsyncSession, Depends(get_db)]
HR = Annotated[User, Depends(workspace_user)]
Admin = Annotated[User, Depends(workspace_admin)]


async def get_template(
    db: AsyncSession, template_id: uuid.UUID, user: User, lock: bool = False
) -> ProcessTemplate:
    await own_customer(db, user)
    query = (
        select(ProcessTemplate)
        .where(ProcessTemplate.id == template_id, ProcessTemplate.tenant_id == user.tenant_id)
        .execution_options(populate_existing=True)
    )
    if lock:
        query = query.with_for_update()
    template = await db.scalar(query)
    if template is None:
        raise HTTPException(404, "Prozess nicht gefunden.")
    return template


@router.get(
    "/templates",
    response_model=list[TemplateRead],
    status_code=200,
    summary="Prozesse des Arbeitsbereichs",
)
async def templates(user: HR, db: DB) -> list[TemplateRead]:
    await own_customer(db, user)
    rows = await db.scalars(
        select(ProcessTemplate)
        .where(ProcessTemplate.tenant_id == user.tenant_id)
        .order_by(ProcessTemplate.updated_at.desc())
        .limit(100)
    )
    return [TemplateRead.model_validate(row) for row in rows]


@router.post(
    "/templates",
    response_model=TemplateRead,
    status_code=201,
    summary="Kontrollierten Prozess konfigurieren",
)
async def create_template(data: TemplateInput, user: Admin, db: DB) -> TemplateRead:
    await own_customer(db, user)
    template = ProcessTemplate(tenant_id=user.tenant_id, **data.model_dump())
    db.add(template)
    await db.flush()
    return TemplateRead.model_validate(template)


@router.put(
    "/templates/{template_id}",
    response_model=TemplateRead,
    status_code=200,
    summary="Prozessversion aktualisieren oder pausieren",
)
async def update_template(
    template_id: uuid.UUID, data: TemplateUpdate, user: Admin, db: DB
) -> TemplateRead:
    template = await get_template(db, template_id, user, lock=True)
    if template.version != data.version:
        raise HTTPException(409, "Prozess wurde geändert. Bitte neu laden.")
    for key, value in data.model_dump(exclude={"version"}).items():
        setattr(template, key, value)
    template.version += 1
    await db.flush()
    await db.refresh(template)
    return TemplateRead.model_validate(template)


@router.post(
    "/templates/{template_id}/runs",
    response_model=RunRead,
    status_code=201,
    summary="Prozess für eine Stelle starten",
)
async def start(
    template_id: uuid.UUID, data: StartRun, user: HR, db: DB, response: Response
) -> RunRead:
    await own_customer(db, user)
    # Serialize retries across templates, without depending on process-local locks.
    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
        {"key": f"process:{user.tenant_id}:{data.request_key}"},
    )
    existing = await db.scalar(
        select(ProcessRun).where(
            ProcessRun.tenant_id == user.tenant_id, ProcessRun.request_key == data.request_key
        )
    )
    if existing:
        if (
            existing.template_id != template_id
            or existing.job_id != data.job_id
            or existing.template_version != data.template_version
            or existing.authorize_ai != data.authorize_ai
            or existing.created_by != user.id
        ):
            raise HTTPException(
                409, "Anfrageschlüssel wurde bereits für einen anderen Start verwendet."
            )
        response.status_code = 200
        return await read_run(db, existing)
    template = await get_template(db, template_id, user, lock=True)
    if not template.enabled or template.version != data.template_version:
        raise HTTPException(409, "Prozess pausiert oder geändert. Bitte neu laden.")
    job = await owned_job(db, data.job_id, user)
    run = ProcessRun(
        tenant_id=user.tenant_id,
        template_id=template.id,
        job_id=job.id,
        created_by=user.id,
        request_key=data.request_key,
        template_version=template.version,
        name=template.name,
        four_eyes=template.four_eyes,
        steps=template.steps,
        source=job_source(job),
        authorize_ai=data.authorize_ai,
    )
    db.add(run)
    await db.flush()
    event(db, run, user.id, "started")
    await advance(db, run, user)
    return await read_run(db, run)


@router.get(
    "/runs", response_model=list[RunRead], status_code=200, summary="Prozessläufe und Freigaben"
)
async def runs(user: HR, db: DB, limit: int = Query(30, ge=1, le=100)) -> list[RunRead]:
    await own_customer(db, user)
    rows = await db.scalars(
        select(ProcessRun)
        .where(ProcessRun.tenant_id == user.tenant_id)
        .order_by(ProcessRun.created_at.desc())
        .limit(limit)
    )
    return [RunRead.model_validate(row) for row in rows]


async def get_run(
    db: AsyncSession, run_id: uuid.UUID, user: User, lock: bool = False
) -> ProcessRun:
    await own_customer(db, user)
    query = (
        select(ProcessRun)
        .where(ProcessRun.id == run_id, ProcessRun.tenant_id == user.tenant_id)
        .execution_options(populate_existing=True)
    )
    if lock:
        query = query.with_for_update()
    run = await db.scalar(query)
    if run is None:
        raise HTTPException(404, "Prozesslauf nicht gefunden.")
    return run


@router.get(
    "/runs/{run_id}",
    response_model=RunRead,
    status_code=200,
    summary="Ergebnisse und Verlauf eines Prozesslaufs",
)
async def detail(run_id: uuid.UUID, user: HR, db: DB) -> RunRead:
    return await read_run(db, await get_run(db, run_id, user))


@router.post(
    "/runs/{run_id}/review",
    response_model=RunRead,
    status_code=200,
    summary="Schritt prüfen oder Prozess abbrechen",
)
async def review(run_id: uuid.UUID, data: Review, user: HR, db: DB) -> RunRead:
    run = await get_run(db, run_id, user, lock=True)
    if run.version != data.version or run.status not in {"awaiting_review", "blocked"}:
        raise HTTPException(409, "Lauf wurde bereits bearbeitet. Bitte neu laden.")
    if data.decision == "cancel":
        run.status = "cancelled"
        mark_result(run, "cancelled")
    else:
        if run.status != "awaiting_review":
            raise HTTPException(409, "Blockierte Läufe können nur abgebrochen werden.")
        if run.four_eyes and run.created_by == user.id:
            raise HTTPException(403, "Für diesen Prozess muss eine andere HR-Person prüfen.")
        if data.decision == "reject":
            run.status = "rejected"
            mark_result(run, "rejected")
        else:
            template = await get_template(db, run.template_id, user, lock=True)
            if not template.enabled:
                raise HTTPException(409, "Prozess ist pausiert. Freigaben sind gesperrt.")
            job = await owned_job(db, run.job_id, user)
            if job_source(job) != run.source:
                raise HTTPException(
                    409, "Stellendaten wurden geändert. Bitte abbrechen und neu starten."
                )
            step = Step.model_validate(run.steps[run.cursor])
            apply_step(db, run, step, str(run.results[-1]["output"]), user)
            mark_result(run, "approved")
            event(db, run, user.id, "approved", data.note)
            run.cursor += 1
            await advance(db, run, user)
    if data.decision != "approve":
        event(db, run, user.id, data.decision, data.note)
    run.version += 1
    return await read_run(db, run)
