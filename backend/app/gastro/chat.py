"""Chat für das Team einer Betriebsstätte.

Absichtlich klein gehalten: Kanäle, Nachrichten, gelesen-bis. Kein Bearbeiten,
damit niemand nachträglich umschreibt, was er geschrieben hat. Eigene Nachrichten
lassen sich löschen, fremde nur durch die Betriebsleitung.

Auch ein Dienstchat enthält personenbezogene Daten, oft über Gäste und Kollegen.
Deshalb läuft jede Nachricht nach der Aufbewahrungsfrist des Betriebs ab, wird
danach nicht mehr angezeigt und lässt sich endgültig entfernen. Wer hier liest,
ist Mitglied dieser Betriebsstätte; der Chat einer anderen bleibt unsichtbar.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.gastro import service as svc
from app.gastro.models import ChatChannel, ChatMessage, ChatRead
from app.gastro.router import DB, Actor, private_response
from app.users.models import User

router = APIRouter(dependencies=[Depends(private_response)])

GENERAL = "Team"


class ChannelInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=2, max_length=60)
    topic: str = Field(default="", max_length=200)


class ChannelRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    name: str
    topic: str
    unread: int = 0
    last_message_at: datetime | None = None


class MessageInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=2000)


class MessageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    text: str
    author_id: uuid.UUID
    author_name: str = ""
    mine: bool = False
    created_at: datetime
    expires_at: datetime


async def channel_for(db: AsyncSession, venue_id: uuid.UUID, channel_id: uuid.UUID) -> ChatChannel:
    row = (
        await db.execute(
            select(ChatChannel).where(
                ChatChannel.id == channel_id, ChatChannel.venue_id == venue_id
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, "Kanal nicht gefunden.")
    return row


async def ensure_general(db: AsyncSession, venue_id: uuid.UUID) -> None:
    """A team without a channel has nowhere to write; the first visit opens one."""
    exists = (
        await db.execute(select(ChatChannel.id).where(ChatChannel.venue_id == venue_id))
    ).first()
    if not exists:
        db.add(
            ChatChannel(
                venue_id=venue_id,
                name=GENERAL,
                topic="Alles, was die Schicht betrifft.",
            )
        )
        await db.flush()


@router.get(
    "/venues/{venue_id}/chat/channels",
    response_model=list[ChannelRead],
    status_code=200,
    summary="Kanäle mit ungelesenen Nachrichten",
)
async def channels(venue_id: uuid.UUID, user: Actor, db: DB) -> list[ChannelRead]:
    await svc.venue_access(db, user, venue_id)
    await ensure_general(db, venue_id)
    rows = (
        (
            await db.execute(
                select(ChatChannel)
                .where(ChatChannel.venue_id == venue_id, ChatChannel.active.is_(True))
                .order_by(ChatChannel.name)
            )
        )
        .scalars()
        .all()
    )
    marked = (
        await db.execute(
            select(ChatRead.channel_id, ChatRead.last_read_sequence).where(
                ChatRead.user_id == user.id,
                ChatRead.channel_id.in_([row.id for row in rows] or [uuid.uuid4()]),
            )
        )
    ).all()
    marks: dict[uuid.UUID, int] = {row[0]: row[1] for row in marked}
    now = datetime.now(UTC)
    result = []
    for row in rows:
        unread = (
            await db.execute(
                select(func.count())
                .select_from(ChatMessage)
                .where(
                    ChatMessage.channel_id == row.id,
                    ChatMessage.expires_at > now,
                    ChatMessage.author_id != user.id,
                    ChatMessage.sequence > marks.get(row.id, 0),
                )
            )
        ).scalar_one()
        latest = (
            await db.execute(
                select(func.max(ChatMessage.created_at)).where(
                    ChatMessage.channel_id == row.id, ChatMessage.expires_at > now
                )
            )
        ).scalar_one()
        result.append(
            ChannelRead(
                id=row.id, name=row.name, topic=row.topic, unread=unread, last_message_at=latest
            )
        )
    return result


@router.post(
    "/venues/{venue_id}/chat/channels",
    response_model=ChannelRead,
    status_code=201,
    summary="Weiteren Kanal anlegen",
)
async def create_channel(
    venue_id: uuid.UUID, data: ChannelInput, user: Actor, db: DB
) -> ChannelRead:
    await svc.venue_access(db, user, venue_id, svc.MANAGERS, lock=True)
    exists = (
        await db.execute(
            select(ChatChannel.id).where(
                ChatChannel.venue_id == venue_id, ChatChannel.name == data.name
            )
        )
    ).first()
    if exists:
        raise HTTPException(409, "Ein Kanal mit diesem Namen existiert bereits.")
    row = ChatChannel(venue_id=venue_id, **data.model_dump())
    db.add(row)
    await db.flush()
    svc.event(db, venue_id, "chat.channel_created", row.id, {"name": row.name}, user.id)
    return ChannelRead.model_validate(row)


@router.get(
    "/venues/{venue_id}/chat/channels/{channel_id}/messages",
    response_model=list[MessageRead],
    status_code=200,
    summary="Nachrichten eines Kanals",
)
async def messages(
    venue_id: uuid.UUID, channel_id: uuid.UUID, user: Actor, db: DB, limit: int = 60
) -> list[MessageRead]:
    await svc.venue_access(db, user, venue_id)
    channel = await channel_for(db, venue_id, channel_id)
    rows = (
        await db.execute(
            select(ChatMessage, User.full_name)
            .join(User, User.id == ChatMessage.author_id)
            .where(
                ChatMessage.channel_id == channel.id,
                ChatMessage.expires_at > datetime.now(UTC),
            )
            .order_by(ChatMessage.sequence.desc())
            .limit(max(1, min(limit, 200)))
        )
    ).all()
    return [
        MessageRead(
            id=row.id,
            text=row.text,
            author_id=row.author_id,
            author_name=name or "Teammitglied",
            mine=row.author_id == user.id,
            created_at=row.created_at,
            expires_at=row.expires_at,
        )
        for row, name in reversed(rows)
    ]


@router.post(
    "/venues/{venue_id}/chat/channels/{channel_id}/messages",
    response_model=MessageRead,
    status_code=201,
    summary="Nachricht schreiben",
)
async def write(
    venue_id: uuid.UUID, channel_id: uuid.UUID, data: MessageInput, user: Actor, db: DB
) -> MessageRead:
    venue, _ = await svc.venue_access(db, user, venue_id)
    channel = await channel_for(db, venue_id, channel_id)
    if not channel.active:
        raise HTTPException(409, "Dieser Kanal ist geschlossen.")
    row = ChatMessage(
        channel_id=channel.id,
        venue_id=venue_id,
        author_id=user.id,
        text=data.text.strip(),
        expires_at=datetime.now(UTC) + timedelta(days=venue.chat_retention_days),
    )
    db.add(row)
    await db.flush()
    return MessageRead(
        id=row.id,
        text=row.text,
        author_id=user.id,
        author_name=user.full_name or "Teammitglied",
        mine=True,
        created_at=row.created_at,
        expires_at=row.expires_at,
    )


@router.delete(
    "/venues/{venue_id}/chat/channels/{channel_id}/messages/{message_id}",
    status_code=204,
    summary="Eigene Nachricht löschen; die Leitung darf jede löschen",
)
async def remove(
    venue_id: uuid.UUID, channel_id: uuid.UUID, message_id: uuid.UUID, user: Actor, db: DB
) -> None:
    _, role = await svc.venue_access(db, user, venue_id)
    row = (
        await db.execute(
            select(ChatMessage)
            .where(
                ChatMessage.id == message_id,
                ChatMessage.channel_id == channel_id,
                ChatMessage.venue_id == venue_id,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, "Nachricht nicht gefunden.")
    if row.author_id != user.id and role != "manager":
        raise HTTPException(403, "Fremde Nachrichten darf nur die Betriebsleitung löschen.")
    foreign = row.author_id != user.id
    await db.delete(row)
    if foreign:
        # Deleting someone else's message is a management act, so it is recorded.
        svc.event(db, venue_id, "chat.message_removed", channel_id, {"by_manager": True}, user.id)


@router.post(
    "/venues/{venue_id}/chat/channels/{channel_id}/read",
    status_code=204,
    summary="Kanal als gelesen markieren",
)
async def mark_read(venue_id: uuid.UUID, channel_id: uuid.UUID, user: Actor, db: DB) -> None:
    await svc.venue_access(db, user, venue_id)
    channel = await channel_for(db, venue_id, channel_id)
    row = (
        await db.execute(
            select(ChatRead)
            .where(ChatRead.channel_id == channel.id, ChatRead.user_id == user.id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    now = datetime.now(UTC)
    latest = (
        await db.execute(
            select(func.coalesce(func.max(ChatMessage.sequence), 0)).where(
                ChatMessage.channel_id == channel.id
            )
        )
    ).scalar_one()
    if row is None:
        db.add(
            ChatRead(
                channel_id=channel.id,
                user_id=user.id,
                last_read_at=now,
                last_read_sequence=latest,
            )
        )
    else:
        row.last_read_at = now
        row.last_read_sequence = latest
    await db.flush()


@router.post(
    "/venues/{venue_id}/chat/purge",
    status_code=200,
    summary="Abgelaufene Nachrichten endgültig entfernen",
)
async def purge(venue_id: uuid.UUID, user: Actor, db: DB) -> dict[str, int]:
    await svc.venue_access(db, user, venue_id, svc.MANAGERS)
    now = datetime.now(UTC)
    removed = (
        await db.execute(
            select(func.count())
            .select_from(ChatMessage)
            .where(ChatMessage.venue_id == venue_id, ChatMessage.expires_at <= now)
        )
    ).scalar_one()
    await db.execute(
        delete(ChatMessage).where(ChatMessage.venue_id == venue_id, ChatMessage.expires_at <= now)
    )
    if removed:
        svc.event(db, venue_id, "chat.purged", venue_id, {"removed": removed}, user.id)
    return {"removed": removed}


@router.put(
    "/venues/{venue_id}/chat-retention",
    status_code=200,
    summary="Aufbewahrungsdauer für Nachrichten festlegen",
)
async def retention(
    venue_id: uuid.UUID, data: dict[str, int], user: Actor, db: DB
) -> dict[str, int]:
    venue, _ = await svc.venue_access(db, user, venue_id, svc.MANAGERS, lock=True)
    days = int(data.get("days", 0))
    if not 7 <= days <= 730:
        raise HTTPException(422, "Zwischen 7 und 730 Tagen.")
    venue.chat_retention_days = days
    svc.event(db, venue_id, "chat.retention_changed", venue_id, {"days": days}, user.id)
    return {"days": days}
