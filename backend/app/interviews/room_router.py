"""Interview room endpoints – video call rooms for scheduled interviews.

Mounted at /interview-rooms
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.interviews.models import InterviewSchedule
from app.interviews.room_models import InterviewRoom, InterviewRoomMessage, InterviewRoomParticipant
from app.security import get_current_user
from app.users.models import User

router = APIRouter()


# ── Pydantic schemas ───────────────────────────────────────────────────────────


class ParticipantOut(BaseModel):
    model_config = {"from_attributes": True}
    id: uuid.UUID
    user_id: uuid.UUID
    display_name: str
    role: str
    joined_at: datetime | None
    left_at: datetime | None


class RoomOut(BaseModel):
    id: uuid.UUID
    schedule_id: uuid.UUID
    title: str
    status: str
    started_at: str | None
    ended_at: str | None
    participants: list[ParticipantOut]
    created_at: str


class MessageOut(BaseModel):
    id: uuid.UUID
    sender_id: uuid.UUID | None
    sender_name: str
    content: str
    created_at: str


class SendMessageIn(BaseModel):
    content: str = Field(min_length=1, max_length=4000)


# ── Helpers ────────────────────────────────────────────────────────────────────


async def _require_schedule_access(
    db: AsyncSession, schedule: InterviewSchedule, user: User
) -> None:
    from app.applications.models import Application

    application = await db.get(Application, schedule.application_id)
    if application is not None and application.user_id == user.id:
        return
    if (
        user.role in {"recruiter", "admin"}
        and user.tenant_id is not None
        and schedule.tenant_id == user.tenant_id
    ):
        return
    raise HTTPException(status_code=403, detail="Kein Zugriff auf dieses Interview.")


async def _get_room(db: AsyncSession, room_id: uuid.UUID, user: User) -> InterviewRoom:
    row = await db.get(InterviewRoom, room_id)
    if not row:
        raise HTTPException(status_code=404, detail="Raum nicht gefunden.")
    schedule = await db.get(InterviewSchedule, row.schedule_id)
    if schedule is None:
        raise HTTPException(status_code=404, detail="Interview-Termin nicht gefunden.")
    await _require_schedule_access(db, schedule, user)
    return row


async def _build_room_out(db: AsyncSession, room: InterviewRoom) -> RoomOut:
    result = await db.execute(
        select(InterviewRoomParticipant).where(InterviewRoomParticipant.room_id == room.id)
    )
    participants = result.scalars().all()
    return RoomOut(
        id=room.id,
        schedule_id=room.schedule_id,
        title=room.title,
        status=room.status,
        started_at=room.started_at.isoformat() if room.started_at else None,
        ended_at=room.ended_at.isoformat() if room.ended_at else None,
        participants=[ParticipantOut.model_validate(p) for p in participants],
        created_at=room.created_at.isoformat(),
    )


# ── Endpoints ──────────────────────────────────────────────────────────────────


@router.get(
    "/by-schedule/{schedule_id}",
    response_model=RoomOut,
    summary="Get or create interview room for a schedule",
)
async def get_or_create_by_schedule(
    schedule_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> RoomOut:
    # Verify schedule exists and user has access
    schedule_result = await db.execute(
        select(InterviewSchedule).where(InterviewSchedule.id == schedule_id)
    )
    schedule = schedule_result.scalar_one_or_none()
    if not schedule:
        raise HTTPException(status_code=404, detail="Interview-Termin nicht gefunden.")

    await _require_schedule_access(db, schedule, current_user)

    # Look up existing room
    room_result = await db.execute(
        select(InterviewRoom).where(InterviewRoom.schedule_id == schedule_id)
    )
    room = room_result.scalar_one_or_none()

    if not room:
        # Only recruiter can create the room
        if current_user.role not in {"recruiter", "admin"} or current_user.tenant_id is None:
            raise HTTPException(status_code=404, detail="Raum noch nicht erstellt.")
        room = InterviewRoom(
            schedule_id=schedule_id,
            tenant_id=current_user.tenant_id,
            created_by=current_user.id,
            title=f"Interview {schedule.scheduled_at.strftime('%d.%m.%Y %H:%M')}",
            status="waiting",
        )
        db.add(room)
        await db.flush()

    await db.commit()
    await db.refresh(room)
    return await _build_room_out(db, room)


@router.get("/{room_id}", response_model=RoomOut, summary="Get room details")
async def get_room(
    room_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> RoomOut:
    room = await _get_room(db, room_id, current_user)
    return await _build_room_out(db, room)


@router.post("/{room_id}/join", response_model=RoomOut, summary="Join interview room")
async def join_room(
    room_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> RoomOut:
    room = await _get_room(db, room_id, current_user)
    if room.status == "ended":
        raise HTTPException(status_code=409, detail="Sitzung bereits beendet.")

    # Upsert participant
    result = await db.execute(
        select(InterviewRoomParticipant).where(
            InterviewRoomParticipant.room_id == room_id,
            InterviewRoomParticipant.user_id == current_user.id,
        )
    )
    participant = result.scalar_one_or_none()

    participant_role = "recruiter" if current_user.role in {"recruiter", "admin"} else "candidate"
    display_name = current_user.full_name or current_user.email

    if participant:
        participant.joined_at = datetime.now(UTC)
        participant.left_at = None
    else:
        participant = InterviewRoomParticipant(
            room_id=room_id,
            user_id=current_user.id,
            display_name=display_name,
            role=participant_role,
            joined_at=datetime.now(UTC),
        )
        db.add(participant)

    # Activate room on first join
    if room.status == "waiting":
        room.status = "active"
        room.started_at = datetime.now(UTC)

    await db.commit()
    await db.refresh(room)
    return await _build_room_out(db, room)


@router.post(
    "/{room_id}/leave", status_code=status.HTTP_204_NO_CONTENT, summary="Leave interview room"
)
async def leave_room(
    room_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    await _get_room(db, room_id, current_user)

    result = await db.execute(
        select(InterviewRoomParticipant).where(
            InterviewRoomParticipant.room_id == room_id,
            InterviewRoomParticipant.user_id == current_user.id,
        )
    )
    participant = result.scalar_one_or_none()
    if participant:
        participant.left_at = datetime.now(UTC)
        await db.commit()


@router.post(
    "/{room_id}/end", response_model=RoomOut, summary="End interview room (recruiter only)"
)
async def end_room(
    room_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> RoomOut:
    if current_user.role not in {"recruiter", "admin"} or current_user.tenant_id is None:
        raise HTTPException(status_code=403, detail="Nur Recruiter können den Raum beenden.")
    room = await _get_room(db, room_id, current_user)

    room.status = "ended"
    room.ended_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(room)
    return await _build_room_out(db, room)


@router.get("/{room_id}/messages", response_model=list[MessageOut], summary="Get chat messages")
async def get_messages(
    room_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[MessageOut]:
    await _get_room(db, room_id, current_user)

    result = await db.execute(
        select(InterviewRoomMessage)
        .where(InterviewRoomMessage.room_id == room_id)
        .order_by(InterviewRoomMessage.created_at)
    )
    msgs = result.scalars().all()
    return [
        MessageOut(
            id=m.id,
            sender_id=m.sender_id,
            sender_name=m.sender_name,
            content=m.content,
            created_at=m.created_at.isoformat(),
        )
        for m in msgs
    ]


@router.post(
    "/{room_id}/messages",
    response_model=MessageOut,
    status_code=status.HTTP_201_CREATED,
    summary="Send chat message",
)
async def send_message(
    room_id: uuid.UUID,
    data: SendMessageIn,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> MessageOut:
    room = await _get_room(db, room_id, current_user)
    if room.status == "ended":
        raise HTTPException(status_code=409, detail="Sitzung bereits beendet.")
    if not data.content.strip():
        raise HTTPException(status_code=422, detail="Nachricht darf nicht leer sein.")

    msg = InterviewRoomMessage(
        room_id=room_id,
        sender_id=current_user.id,
        sender_name=current_user.full_name or current_user.email,
        content=data.content.strip(),
    )
    db.add(msg)
    await db.commit()
    await db.refresh(msg)
    return MessageOut(
        id=msg.id,
        sender_id=msg.sender_id,
        sender_name=msg.sender_name,
        content=msg.content,
        created_at=msg.created_at.isoformat(),
    )
