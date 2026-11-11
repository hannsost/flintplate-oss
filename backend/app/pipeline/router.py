"""Pipeline Builder API – palmscout MVP 2.

Mounted at /pipeline (via main.py)
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.pipeline.access import require_application, require_stage, require_template
from app.pipeline.schemas import (
    ApplicationStageHistoryRead,
    KanbanBoardRead,
    PipelineStageCreate,
    PipelineStageRead,
    PipelineStageUpdate,
    PipelineTemplateCreate,
    PipelineTemplateRead,
    PipelineTemplateUpdate,
    StageTransitionRequest,
    StageTransitionResponse,
)
from app.pipeline.service import (
    add_stage,
    create_template,
    delete_stage,
    delete_template,
    get_current_stage,
    get_kanban_board,
    get_stage_history,
    list_templates,
    transition_stage,
    update_stage,
    update_template,
)
from app.security import get_current_user
from app.users.models import User

router = APIRouter()


def _require_recruiter(user: User) -> User:
    if user.role not in {"recruiter", "admin"} or user.tenant_id is None:
        raise HTTPException(status_code=403, detail="Nur für Recruiter.")
    return user


# ── Templates ─────────────────────────────────────────────────────────────────


@router.post(
    "/templates",
    response_model=PipelineTemplateRead,
    status_code=status.HTTP_201_CREATED,
    summary="Pipeline-Template erstellen",
)
async def create(
    data: PipelineTemplateCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> PipelineTemplateRead:
    _require_recruiter(current_user)
    return await create_template(db, current_user.id, data)


@router.get(
    "/templates",
    response_model=list[PipelineTemplateRead],
    summary="Eigene + System-Pipelines abrufen",
)
async def list_all(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[PipelineTemplateRead]:
    _require_recruiter(current_user)
    return await list_templates(db, current_user.id, current_user.company_id)


@router.get(
    "/templates/{template_id}",
    response_model=PipelineTemplateRead,
    summary="Pipeline-Template abrufen",
)
async def get_one(
    template_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> PipelineTemplateRead:
    _require_recruiter(current_user)
    template = await require_template(db, template_id, current_user)
    from app.pipeline.schemas import PipelineTemplateRead

    return PipelineTemplateRead.model_validate(template)


@router.patch(
    "/templates/{template_id}",
    response_model=PipelineTemplateRead,
    summary="Pipeline-Template umbenennen / als Standard setzen",
)
async def update(
    template_id: uuid.UUID,
    data: PipelineTemplateUpdate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> PipelineTemplateRead:
    _require_recruiter(current_user)
    template = await require_template(db, template_id, current_user, write=True)
    return await update_template(db, template, data)


@router.delete(
    "/templates/{template_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Pipeline-Template löschen",
)
async def delete(
    template_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    _require_recruiter(current_user)
    template = await require_template(db, template_id, current_user, write=True)
    await delete_template(db, template)


# ── Stages ────────────────────────────────────────────────────────────────────


@router.post(
    "/templates/{template_id}/stages",
    response_model=PipelineStageRead,
    status_code=status.HTTP_201_CREATED,
    summary="Stage zu Pipeline hinzufügen",
)
async def add(
    template_id: uuid.UUID,
    data: PipelineStageCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> PipelineStageRead:
    _require_recruiter(current_user)
    await require_template(db, template_id, current_user, write=True)
    return await add_stage(db, template_id, data)


@router.patch(
    "/stages/{stage_id}",
    response_model=PipelineStageRead,
    summary="Stage konfigurieren (Name, SLA, Trigger, Approval)",
)
async def update_s(
    stage_id: uuid.UUID,
    data: PipelineStageUpdate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> PipelineStageRead:
    _require_recruiter(current_user)
    stage = await require_stage(db, stage_id, current_user, write=True)
    return await update_stage(db, stage, data)


@router.delete(
    "/stages/{stage_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Stage löschen",
)
async def delete_s(
    stage_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    _require_recruiter(current_user)
    stage = await require_stage(db, stage_id, current_user, write=True)
    await delete_stage(db, stage)


# ── Transitions ───────────────────────────────────────────────────────────────


@router.post(
    "/transitions",
    response_model=StageTransitionResponse,
    summary="Bewerbung in neue Stage verschieben",
)
async def transition(
    data: StageTransitionRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> StageTransitionResponse:
    _require_recruiter(current_user)
    await require_application(db, data.application_id, current_user)
    stage = await require_stage(db, data.to_stage_id, current_user)
    if stage.requires_approval and current_user.role not in {
        stage.approver_role or "recruiter",
        "admin",
    }:
        raise HTTPException(
            status_code=403, detail="Diese Stage erfordert die konfigurierte Freigaberolle."
        )
    try:
        result = await transition_stage(db, data, current_user.id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from None

    # Broadcast real-time Kanban update to all tenant recruiters
    if current_user.tenant_id:
        import asyncio

        from app.ws.manager import manager

        asyncio.ensure_future(
            manager.broadcast_to_tenant(
                str(current_user.tenant_id),
                {
                    "type": "pipeline_move",
                    "application_id": str(data.application_id),
                    "to_stage_id": str(data.to_stage_id),
                    "stage_name": result.stage.name,
                    "moved_by": current_user.email,
                },
            )
        )

    return result


@router.get(
    "/kanban/{template_id}",
    response_model=KanbanBoardRead,
    summary="Kanban-Board für ein Pipeline-Template",
)
async def kanban_board(
    template_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> KanbanBoardRead:
    _require_recruiter(current_user)
    await require_template(db, template_id, current_user)
    try:
        return await get_kanban_board(
            db, template_id, recruiter_id=current_user.id, tenant_id=current_user.tenant_id
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from None


@router.get(
    "/applications/{application_id}/stage",
    response_model=PipelineStageRead | None,
    summary="Aktuelle Stage einer Bewerbung",
)
async def current_stage(
    application_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> PipelineStageRead | None:
    _require_recruiter(current_user)
    await require_application(db, application_id, current_user)
    return await get_current_stage(db, application_id)


@router.get(
    "/applications/{application_id}/history",
    response_model=list[ApplicationStageHistoryRead],
    summary="Stage-Verlauf einer Bewerbung",
)
async def stage_history(
    application_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[ApplicationStageHistoryRead]:
    _require_recruiter(current_user)
    await require_application(db, application_id, current_user)
    history = await get_stage_history(db, application_id)
    return [ApplicationStageHistoryRead.model_validate(h) for h in history]
