"""HR team-inbox endpoints – /zeitarbeit/messages (Sprint 4.5)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select

from app.dependencies import DBSession, TenantRecruiterUser
from app.messages.models import THREAD_STATUSES, Message, MessageThread
from app.messages.schemas import (
    AssignTeamRequest,
    HRReplyRequest,
    MessageRead,
    ThreadRead,
    ThreadWithMessages,
)
from app.teams.service import require_team

router = APIRouter()


async def _enrich_thread(
    thread: MessageThread, db: DBSession, include_messages: bool = False
) -> dict[str, Any]:
    """Build a ThreadRead/ThreadWithMessages dict with all joined data."""
    from app.teams.models import Team
    from app.users.models import User

    # Batch-load all related users in one go where possible
    user_ids = {str(thread.worker_id)}
    if thread.claimed_by:
        user_ids.add(str(thread.claimed_by))
    u_rows = await db.execute(select(User).where(User.id.in_(user_ids)))
    users = {str(u.id): u for u in u_rows.scalars()}

    worker = users.get(str(thread.worker_id))
    claimer = users.get(str(thread.claimed_by)) if thread.claimed_by else None

    team_name = None
    if thread.assigned_team_id:
        t_row = await db.execute(select(Team).where(Team.id == thread.assigned_team_id))
        t = t_row.scalar_one_or_none()
        team_name = t.name if t else None

    # Preview
    preview_row = await db.execute(
        select(Message)
        .where(Message.thread_id == thread.id, Message.is_internal_note == False)  # noqa: E712
        .order_by(Message.created_at.desc())
        .limit(1)
    )
    last = preview_row.scalar_one_or_none()
    preview = (
        (last.body[:80] + "…") if last and len(last.body) > 80 else (last.body if last else "")
    )

    result: dict[str, Any] = {
        "id": thread.id,
        "tenant_id": thread.tenant_id,
        "worker_id": thread.worker_id,
        "worker_name": worker.full_name if worker else None,
        "worker_email": worker.email if worker else "",
        "assigned_team_id": thread.assigned_team_id,
        "assigned_team_name": team_name,
        "claimed_by": thread.claimed_by,
        "claimed_by_name": (claimer.full_name or claimer.email) if claimer else None,
        "subject": thread.subject,
        "status": thread.status,
        "last_message_at": thread.last_message_at,
        "unread_hr": thread.unread_hr,
        "unread_worker": thread.unread_worker,
        "created_at": thread.created_at,
        "updated_at": thread.updated_at,
        "preview": preview,
    }

    if include_messages:
        msg_rows = await db.execute(
            select(Message, User)
            .join(User, Message.sender_id == User.id)
            .where(Message.thread_id == thread.id)
            .order_by(Message.created_at)
        )
        result["messages"] = [
            MessageRead(
                id=m.id,
                thread_id=m.thread_id,
                sender_id=m.sender_id,
                sender_name=u.full_name or u.email,
                sender_role=u.role,
                body=m.body,
                is_internal_note=m.is_internal_note,
                created_at=m.created_at,
            )
            for m, u in msg_rows.all()
        ]

    return result


# ── List / Get ────────────────────────────────────────────────────────────────


@router.get("", response_model=list[ThreadRead])
async def list_threads(
    user: TenantRecruiterUser,
    db: DBSession,
    status: str | None = Query(None),
    team_id: str | None = Query(None),
    worker_id: str | None = Query(None),
    unread_only: bool = Query(False),
) -> list[dict[str, Any]]:
    stmt = select(MessageThread).where(MessageThread.tenant_id == user.tenant_id)

    if status:
        if status not in THREAD_STATUSES:
            raise HTTPException(status_code=422, detail=f"status must be one of {THREAD_STATUSES}")
        stmt = stmt.where(MessageThread.status == status)

    if team_id:
        stmt = stmt.where(MessageThread.assigned_team_id == team_id)

    if worker_id:
        stmt = stmt.where(MessageThread.worker_id == worker_id)

    if unread_only:
        stmt = stmt.where(MessageThread.unread_hr > 0)

    stmt = stmt.order_by(MessageThread.last_message_at.desc().nullslast())
    rows = await db.execute(stmt)
    threads = list(rows.scalars().all())
    return [await _enrich_thread(t, db) for t in threads]


@router.get("/{thread_id}", response_model=ThreadWithMessages)
async def get_thread(thread_id: str, user: TenantRecruiterUser, db: DBSession) -> dict[str, Any]:
    row = await db.execute(
        select(MessageThread).where(
            MessageThread.id == thread_id,
            MessageThread.tenant_id == user.tenant_id,
        )
    )
    thread = row.scalar_one_or_none()
    if not thread:
        raise HTTPException(status_code=404, detail="Konversation nicht gefunden")

    # Mark as read for HR
    if thread.unread_hr > 0:
        thread.unread_hr = 0
        await db.commit()
        await db.refresh(thread)

    return await _enrich_thread(thread, db, include_messages=True)


# ── Reply / Internal Note ─────────────────────────────────────────────────────


@router.post("/{thread_id}/reply", response_model=MessageRead, status_code=201)
async def reply(
    thread_id: str, body: HRReplyRequest, user: TenantRecruiterUser, db: DBSession
) -> MessageRead:
    row = await db.execute(
        select(MessageThread).where(
            MessageThread.id == thread_id,
            MessageThread.tenant_id == user.tenant_id,
        )
    )
    thread = row.scalar_one_or_none()
    if not thread:
        raise HTTPException(status_code=404, detail="Konversation nicht gefunden")

    now = datetime.now()
    message = Message(
        thread_id=thread.id,
        sender_id=user.id,
        body=body.body,
        is_internal_note=body.is_internal_note,
    )
    db.add(message)

    thread.last_message_at = now
    thread.updated_at = now

    if not body.is_internal_note:
        # Visible to worker → bump unread_worker
        thread.unread_worker += 1
        if thread.status == "open":
            thread.status = "in_progress"
            thread.claimed_by = thread.claimed_by or user.id

    await db.commit()
    await db.refresh(message)

    return MessageRead(
        id=message.id,
        thread_id=message.thread_id,
        sender_id=message.sender_id,
        sender_name=user.full_name or user.email,
        sender_role=user.role,
        body=message.body,
        is_internal_note=message.is_internal_note,
        created_at=message.created_at,
    )


# ── Lifecycle actions ─────────────────────────────────────────────────────────


@router.post("/{thread_id}/claim", response_model=ThreadRead)
async def claim(thread_id: str, user: TenantRecruiterUser, db: DBSession) -> dict[str, Any]:
    row = await db.execute(
        select(MessageThread).where(
            MessageThread.id == thread_id,
            MessageThread.tenant_id == user.tenant_id,
        )
    )
    thread = row.scalar_one_or_none()
    if not thread:
        raise HTTPException(status_code=404, detail="Konversation nicht gefunden")

    thread.claimed_by = user.id
    thread.status = "in_progress"
    thread.updated_at = datetime.now()
    await db.commit()
    await db.refresh(thread)
    return await _enrich_thread(thread, db)


@router.post("/{thread_id}/unclaim", response_model=ThreadRead)
async def unclaim(thread_id: str, user: TenantRecruiterUser, db: DBSession) -> dict[str, Any]:
    row = await db.execute(
        select(MessageThread).where(
            MessageThread.id == thread_id,
            MessageThread.tenant_id == user.tenant_id,
        )
    )
    thread = row.scalar_one_or_none()
    if not thread:
        raise HTTPException(status_code=404, detail="Konversation nicht gefunden")

    thread.claimed_by = None
    thread.status = "open"
    thread.updated_at = datetime.now()
    await db.commit()
    await db.refresh(thread)
    return await _enrich_thread(thread, db)


@router.post("/{thread_id}/resolve", response_model=ThreadRead)
async def resolve(thread_id: str, user: TenantRecruiterUser, db: DBSession) -> dict[str, Any]:
    row = await db.execute(
        select(MessageThread).where(
            MessageThread.id == thread_id,
            MessageThread.tenant_id == user.tenant_id,
        )
    )
    thread = row.scalar_one_or_none()
    if not thread:
        raise HTTPException(status_code=404, detail="Konversation nicht gefunden")

    thread.status = "resolved"
    thread.updated_at = datetime.now()
    await db.commit()
    await db.refresh(thread)
    return await _enrich_thread(thread, db)


@router.post("/{thread_id}/reopen", response_model=ThreadRead)
async def reopen(thread_id: str, user: TenantRecruiterUser, db: DBSession) -> dict[str, Any]:
    row = await db.execute(
        select(MessageThread).where(
            MessageThread.id == thread_id,
            MessageThread.tenant_id == user.tenant_id,
        )
    )
    thread = row.scalar_one_or_none()
    if not thread:
        raise HTTPException(status_code=404, detail="Konversation nicht gefunden")

    thread.status = "open"
    thread.updated_at = datetime.now()
    await db.commit()
    await db.refresh(thread)
    return await _enrich_thread(thread, db)


@router.patch("/{thread_id}/assign-team", response_model=ThreadRead)
async def assign_team(
    thread_id: str, body: AssignTeamRequest, user: TenantRecruiterUser, db: DBSession
) -> dict[str, Any]:
    row = await db.execute(
        select(MessageThread).where(
            MessageThread.id == thread_id,
            MessageThread.tenant_id == user.tenant_id,
        )
    )
    thread = row.scalar_one_or_none()
    if not thread:
        raise HTTPException(status_code=404, detail="Konversation nicht gefunden")

    if body.team_id:
        await require_team(db, user.tenant_id, body.team_id)
    thread.assigned_team_id = body.team_id
    thread.updated_at = datetime.now()
    await db.commit()
    await db.refresh(thread)
    return await _enrich_thread(thread, db)
