"""Worker-facing messaging endpoints – GET/POST /worker/messages (Sprint 4.5)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from app.dependencies import DBSession, WorkerUser
from app.messages.models import Message, MessageThread
from app.messages.schemas import (
    MessageRead,
    NewThreadRequest,
    ThreadRead,
    ThreadWithMessages,
    WorkerReplyRequest,
)
from app.teams.service import require_team

router = APIRouter()


async def _thread_to_read(
    thread: MessageThread, db: DBSession, include_messages: bool = False
) -> dict[str, Any]:
    from app.teams.models import Team
    from app.users.models import User

    worker_row = await db.execute(select(User).where(User.id == thread.worker_id))
    worker = worker_row.scalar_one_or_none()

    team_name = None
    if thread.assigned_team_id:
        t_row = await db.execute(select(Team).where(Team.id == thread.assigned_team_id))
        t = t_row.scalar_one_or_none()
        team_name = t.name if t else None

    claimed_name = None
    if thread.claimed_by:
        c_row = await db.execute(select(User).where(User.id == thread.claimed_by))
        c = c_row.scalar_one_or_none()
        claimed_name = c.full_name or c.email if c else None

    # Preview: last non-internal message
    msg_rows = await db.execute(
        select(Message)
        .where(Message.thread_id == thread.id, Message.is_internal_note == False)  # noqa: E712
        .order_by(Message.created_at.desc())
        .limit(1)
    )
    last_msg = msg_rows.scalar_one_or_none()
    preview = (
        (last_msg.body[:80] + "…")
        if last_msg and len(last_msg.body) > 80
        else (last_msg.body if last_msg else "")
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
        "claimed_by_name": claimed_name,
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
        msgs = await db.execute(
            select(Message, User)
            .join(User, Message.sender_id == User.id)
            .where(Message.thread_id == thread.id, Message.is_internal_note == False)  # noqa: E712
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
            for m, u in msgs.all()
        ]

    return result


@router.get("", response_model=list[ThreadRead])
async def list_my_threads(user: WorkerUser, db: DBSession) -> list[dict[str, Any]]:
    rows = await db.execute(
        select(MessageThread)
        .where(MessageThread.worker_id == user.id)
        .order_by(MessageThread.last_message_at.desc().nullslast())
    )
    threads = list(rows.scalars().all())
    return [await _thread_to_read(t, db) for t in threads]


@router.post("", response_model=ThreadWithMessages, status_code=201)
async def create_thread(body: NewThreadRequest, user: WorkerUser, db: DBSession) -> dict[str, Any]:
    from app.worker.models import WorkerSettings

    ws_row = await db.execute(select(WorkerSettings).where(WorkerSettings.user_id == user.id))
    ws = ws_row.scalar_one_or_none()
    if ws and not ws.active_modules.get("messages", True):
        raise HTTPException(status_code=403, detail="Nachrichten-Modul nicht aktiviert")

    now = datetime.now()

    # Determine team: use provided, else fallback to worker's assigned team
    team_id = body.assigned_team_id
    if not team_id and ws and ws.assigned_team_id:
        team_id = ws.assigned_team_id

    if team_id:
        await require_team(db, user.tenant_id, team_id)

    thread = MessageThread(
        tenant_id=ws.tenant_id if ws else user.tenant_id,
        worker_id=user.id,
        assigned_team_id=team_id,
        subject=body.subject,
        status="open",
        last_message_at=now,
        unread_hr=1,
    )
    db.add(thread)
    await db.flush()

    message = Message(
        thread_id=thread.id,
        sender_id=user.id,
        body=body.body,
        is_internal_note=False,
    )
    db.add(message)
    await db.commit()
    await db.refresh(thread)

    return await _thread_to_read(thread, db, include_messages=True)


@router.get("/{thread_id}", response_model=ThreadWithMessages)
async def get_thread(thread_id: str, user: WorkerUser, db: DBSession) -> dict[str, Any]:
    row = await db.execute(
        select(MessageThread).where(
            MessageThread.id == thread_id,
            MessageThread.worker_id == user.id,
        )
    )
    thread = row.scalar_one_or_none()
    if not thread:
        raise HTTPException(status_code=404, detail="Konversation nicht gefunden")

    # Mark as read for worker
    thread.unread_worker = 0
    await db.commit()
    await db.refresh(thread)

    return await _thread_to_read(thread, db, include_messages=True)


@router.post("/{thread_id}/reply", response_model=MessageRead, status_code=201)
async def reply_to_thread(
    thread_id: str, body: WorkerReplyRequest, user: WorkerUser, db: DBSession
) -> MessageRead:
    row = await db.execute(
        select(MessageThread).where(
            MessageThread.id == thread_id,
            MessageThread.worker_id == user.id,
        )
    )
    thread = row.scalar_one_or_none()
    if not thread:
        raise HTTPException(status_code=404, detail="Konversation nicht gefunden")
    if thread.status == "resolved":
        # Reopen on new worker reply
        thread.status = "open"
        thread.claimed_by = None

    now = datetime.now()
    message = Message(thread_id=thread.id, sender_id=user.id, body=body.body)
    db.add(message)

    thread.last_message_at = now
    thread.updated_at = now
    thread.unread_hr += 1

    await db.commit()
    await db.refresh(message)

    return MessageRead(
        id=message.id,
        thread_id=message.thread_id,
        sender_id=message.sender_id,
        sender_name=None,
        sender_role="worker",
        body=message.body,
        is_internal_note=False,
        created_at=message.created_at,
    )
