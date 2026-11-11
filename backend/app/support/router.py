"""Support module REST endpoints."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.security import get_current_user, require_admin
from app.support.models import SupportConfig, SupportSession
from app.support.schemas import (
    SupportConfigRead,
    SupportConfigUpdate,
    SupportSessionAgentRead,
    SupportSessionCreate,
    SupportSessionRead,
    SupportSessionUpdate,
    SupportWidgetConfig,
)
from app.users.models import User
from app.ws.manager import manager

router = APIRouter()


# ── helpers ───────────────────────────────────────────────────────────────────


def _require_support(user: User) -> User:
    if user.role != "support":
        raise HTTPException(status_code=403, detail="Nur Support-Agenten haben Zugriff.")
    return user


def _require_recruiter_or_admin(user: User) -> User:
    if user.role not in ("recruiter", "admin"):
        raise HTTPException(
            status_code=403, detail="Nur Recruiter/Admins können Support anfordern."
        )
    return user


async def _get_or_create_config(db: AsyncSession, tenant_id: uuid.UUID) -> SupportConfig:
    row = await db.execute(select(SupportConfig).where(SupportConfig.tenant_id == tenant_id))
    cfg = row.scalar_one_or_none()
    if not cfg:
        cfg = SupportConfig(tenant_id=tenant_id)
        db.add(cfg)
        await db.flush()
    return cfg


# ── Widget config (public for recruiters) ────────────────────────────────────


@router.get("/widget-config", response_model=SupportWidgetConfig)
async def get_widget_config(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> SupportWidgetConfig:
    """Returns minimal config needed to render the support widget."""
    _require_recruiter_or_admin(current_user)
    if not current_user.tenant_id:
        return SupportWidgetConfig(
            enabled=False,
            allow_video=True,
            allow_audio=True,
            allow_remote_control=True,
            allow_dom_viewing=True,
            widget_title="Live Support",
            widget_color="#2563eb",
            welcome_message=None,
            require_consent=True,
        )
    cfg = await _get_or_create_config(db, current_user.tenant_id)
    return SupportWidgetConfig(
        enabled=cfg.enabled,
        allow_video=cfg.allow_video,
        allow_audio=cfg.allow_audio,
        allow_remote_control=cfg.allow_remote_control,
        allow_dom_viewing=cfg.allow_dom_viewing,
        widget_title=cfg.widget_title,
        widget_color=cfg.widget_color,
        welcome_message=cfg.welcome_message,
        require_consent=cfg.require_consent,
    )


# ── Sessions ─────────────────────────────────────────────────────────────────


@router.post("/sessions", response_model=SupportSessionRead, status_code=status.HTTP_201_CREATED)
async def create_session(
    data: SupportSessionCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> SupportSessionRead:
    """Recruiter requests a support session."""
    _require_recruiter_or_admin(current_user)
    if not current_user.tenant_id:
        raise HTTPException(status_code=400, detail="Kein Tenant zugeordnet.")

    cfg = await _get_or_create_config(db, current_user.tenant_id)
    if not cfg.enabled:
        raise HTTPException(
            status_code=403, detail="Support ist für diesen Tenant nicht aktiviert."
        )

    session = SupportSession(
        tenant_id=current_user.tenant_id,
        requester_id=current_user.id,
        subject=data.subject,
        video_enabled=data.video_enabled and cfg.allow_video,
        audio_enabled=data.audio_enabled and cfg.allow_audio,
        remote_control_enabled=data.remote_control_enabled and cfg.allow_remote_control,
        dom_viewing_enabled=data.dom_viewing_enabled and cfg.allow_dom_viewing,
        billing_model=cfg.billing_model,
    )
    db.add(session)
    await db.flush()
    await db.refresh(session)

    # Notify all connected support agents about the new session
    await manager.broadcast_to_role(
        "support",
        {
            "type": "support.incoming",
            "session_id": str(session.id),
            "subject": session.subject,
            "requester": current_user.full_name or current_user.email,
            "tenant_id": str(session.tenant_id),
            "video": session.video_enabled,
            "audio": session.audio_enabled,
            "remote_control": session.remote_control_enabled,
            "dom_viewing": session.dom_viewing_enabled,
        },
    )

    return SupportSessionRead.model_validate(session)


@router.get("/sessions", response_model=list[SupportSessionRead])
async def list_my_sessions(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[SupportSessionRead]:
    """Recruiter sees their own sessions. Support agents see all pending/active."""
    if current_user.role == "support":
        rows = await db.execute(
            select(SupportSession)
            .where(SupportSession.status.in_(["pending", "active"]))
            .order_by(SupportSession.requested_at.desc())
        )
    elif current_user.role in ("recruiter", "admin"):
        rows = await db.execute(
            select(SupportSession)
            .where(SupportSession.requester_id == current_user.id)
            .order_by(SupportSession.requested_at.desc())
            .limit(50)
        )
    else:
        raise HTTPException(status_code=403, detail="Kein Zugriff.")
    return [SupportSessionRead.model_validate(s) for s in rows.scalars()]


@router.get("/sessions/queue", response_model=list[SupportSessionAgentRead])
async def agent_queue(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[SupportSessionAgentRead]:
    """Support agent queue – all pending + active sessions."""
    _require_support(current_user)
    rows = await db.execute(
        select(SupportSession)
        .where(SupportSession.status.in_(["pending", "active"]))
        .order_by(SupportSession.requested_at.asc())
    )
    return [SupportSessionAgentRead.model_validate(s) for s in rows.scalars()]


@router.get(
    "/sessions/{session_id}",
    response_model=SupportSessionRead | SupportSessionAgentRead,
    status_code=200,
    summary="Eigene Support-Sitzung oder Agentenansicht abrufen",
)
async def get_session(
    session_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> SupportSessionRead | SupportSessionAgentRead:
    row = await db.execute(select(SupportSession).where(SupportSession.id == session_id))
    session = row.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Session nicht gefunden.")
    # Access: own session or support agent
    if current_user.role == "support":
        return SupportSessionAgentRead.model_validate(session)
    elif current_user.id != session.requester_id:
        raise HTTPException(status_code=403, detail="Kein Zugriff.")
    return SupportSessionRead.model_validate(session)


@router.post("/sessions/{session_id}/accept", response_model=SupportSessionRead)
async def accept_session(
    session_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> SupportSessionRead:
    """Support agent accepts a pending session."""
    _require_support(current_user)
    row = await db.execute(
        select(SupportSession)
        .where(SupportSession.id == session_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    session = row.scalar_one_or_none()
    if not session or session.status != "pending":
        raise HTTPException(status_code=400, detail="Session nicht verfügbar.")

    session.agent_id = current_user.id
    session.status = "active"
    session.started_at = datetime.now(UTC)
    await db.flush()

    # Notify requester
    await manager.send_to_user(
        str(session.requester_id),
        {
            "type": "support.accepted",
            "session_id": str(session.id),
            "agent_name": current_user.full_name or "Support",
        },
    )
    return SupportSessionRead.model_validate(session)


@router.post("/sessions/{session_id}/reject", response_model=SupportSessionRead)
async def reject_session(
    session_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> SupportSessionRead:
    """Support agent rejects a pending session."""
    _require_support(current_user)
    row = await db.execute(select(SupportSession).where(SupportSession.id == session_id))
    session = row.scalar_one_or_none()
    if not session or session.status != "pending":
        raise HTTPException(status_code=400, detail="Session nicht verfügbar.")

    session.status = "rejected"
    session.end_reason = "agent_rejected"
    session.ended_at = datetime.now(UTC)
    await db.flush()

    await manager.send_to_user(
        str(session.requester_id),
        {
            "type": "support.rejected",
            "session_id": str(session.id),
        },
    )
    return SupportSessionRead.model_validate(session)


@router.post("/sessions/{session_id}/consent", response_model=SupportSessionRead)
async def give_consent(
    session_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> SupportSessionRead:
    """Requester gives DSGVO consent for this session."""
    _require_recruiter_or_admin(current_user)
    row = await db.execute(select(SupportSession).where(SupportSession.id == session_id))
    session = row.scalar_one_or_none()
    if not session or session.requester_id != current_user.id:
        raise HTTPException(status_code=404, detail="Session nicht gefunden.")

    session.consent_given = True
    session.consent_given_at = datetime.now(UTC)
    await db.flush()

    # Notify agent that consent was granted
    if session.agent_id:
        await manager.send_to_user(
            str(session.agent_id),
            {
                "type": "support.consent_granted",
                "session_id": str(session.id),
            },
        )
    return SupportSessionRead.model_validate(session)


@router.post("/sessions/{session_id}/end", response_model=SupportSessionRead)
async def end_session(
    session_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> SupportSessionRead:
    """End a session (by requester or agent)."""
    row = await db.execute(select(SupportSession).where(SupportSession.id == session_id))
    session = row.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Session nicht gefunden.")

    is_requester = session.requester_id == current_user.id
    is_agent = current_user.role == "support" and session.agent_id == current_user.id
    if not is_requester and not is_agent:
        raise HTTPException(status_code=403, detail="Kein Zugriff.")

    if session.status in ("ended", "cancelled", "rejected"):
        return SupportSessionRead.model_validate(session)

    now = datetime.now(UTC)
    session.status = "ended"
    session.ended_at = now
    session.end_reason = "requester_ended" if is_requester else "agent_ended"

    if session.started_at:
        delta = now - session.started_at
        session.duration_seconds = int(delta.total_seconds())
        # Calculate billing
        if session.billing_model == "per_minute" and session.duration_seconds:
            cfg = await _get_or_create_config(db, session.tenant_id)
            if cfg.per_minute_cents:
                mins = max(1, session.duration_seconds // 60)
                session.billed_amount_cents = mins * cfg.per_minute_cents
                session.billed_at = now
        elif session.billing_model == "per_session":
            cfg = await _get_or_create_config(db, session.tenant_id)
            if cfg.per_session_cents:
                session.billed_amount_cents = cfg.per_session_cents
                session.billed_at = now

    await db.flush()

    # Notify both parties
    event = {"type": "support.ended", "session_id": str(session.id), "reason": session.end_reason}
    notify_ids = [str(session.requester_id)]
    if session.agent_id:
        notify_ids.append(str(session.agent_id))
    for uid in notify_ids:
        await manager.send_to_user(uid, event)

    return SupportSessionRead.model_validate(session)


@router.patch("/sessions/{session_id}/notes", response_model=SupportSessionAgentRead)
async def update_notes(
    session_id: uuid.UUID,
    data: SupportSessionUpdate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> SupportSessionAgentRead:
    """Update agent notes / summary (agent only)."""
    _require_support(current_user)
    row = await db.execute(select(SupportSession).where(SupportSession.id == session_id))
    session = row.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Session nicht gefunden.")
    if session.agent_id != current_user.id:
        raise HTTPException(
            status_code=403, detail="Diese Sitzung ist einem anderen Agenten zugeordnet."
        )
    if data.agent_notes is not None:
        session.agent_notes = data.agent_notes
    if data.summary is not None:
        session.summary = data.summary
    await db.flush()
    return SupportSessionAgentRead.model_validate(session)


# ── Config (admin only) ───────────────────────────────────────────────────────


@router.get("/config", response_model=SupportConfigRead)
async def get_config(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> SupportConfigRead:
    require_admin(current_user)
    if not current_user.tenant_id:
        raise HTTPException(status_code=400, detail="Kein Tenant.")
    cfg = await _get_or_create_config(db, current_user.tenant_id)
    return SupportConfigRead.model_validate(cfg)


@router.patch("/config", response_model=SupportConfigRead)
async def update_config(
    data: SupportConfigUpdate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> SupportConfigRead:
    require_admin(current_user)
    if not current_user.tenant_id:
        raise HTTPException(status_code=400, detail="Kein Tenant.")
    cfg = await _get_or_create_config(db, current_user.tenant_id)
    for key, val in data.model_dump(exclude_none=True).items():
        setattr(cfg, key, val)
    await db.flush()
    await db.refresh(cfg)
    return SupportConfigRead.model_validate(cfg)
