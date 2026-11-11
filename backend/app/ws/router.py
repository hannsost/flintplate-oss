"""WebSocket endpoint – /ws?token=<jwt>

Handles:
  - Keepalive ping/pong
  - Support module signaling (WebRTC offer/answer/ICE, DOM events, remote control)
  - Interview room signaling (WebRTC mesh, chat, media state)
"""

from __future__ import annotations

import json
import logging
import uuid

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ws.manager import manager

log = logging.getLogger(__name__)

router = APIRouter()

# Support message types that are simply relayed to the peer (session_id-based routing)
SUPPORT_RELAY_TYPES = {
    "support.webrtc_offer",
    "support.webrtc_answer",
    "support.webrtc_ice",
    "support.dom_snapshot",
    "support.dom_events",
    "support.control_mouse",
    "support.control_keyboard",
    "support.cursor_move",
    "support.agent_ready",
}

# Interview room: peer-to-peer WebRTC signals (carry target_peer_id)
INTERVIEW_P2P_TYPES = {
    "interview.webrtc_offer",
    "interview.webrtc_answer",
    "interview.webrtc_ice",
}

# Interview room: broadcast to all participants in the room
INTERVIEW_BROADCAST_TYPES = {
    "interview.chat_message",
    "interview.media_state",
    "interview.peer_joined",
    "interview.peer_left",
    "interview.room_ended",
}


async def _identity(db: AsyncSession, token: str) -> tuple[str, str | None, str] | None:
    from app.security import get_current_user

    try:
        user = await get_current_user(token, db)
    except HTTPException:
        return None
    return str(user.id), str(user.tenant_id) if user.tenant_id else None, user.role


async def _support_access(
    db: AsyncSession, session_id: str, user_id: str, msg_type: str
) -> str | None:
    from app.support.models import SupportSession

    try:
        session = await db.get(SupportSession, uuid.UUID(session_id))
    except ValueError:
        return None
    if session is None or session.status != "active" or not session.consent_given:
        return None
    peer = (
        "requester"
        if str(session.requester_id) == user_id
        else "agent" if str(session.agent_id) == user_id else None
    )
    if peer is None:
        return None
    if msg_type.startswith("support.control_") or msg_type == "support.cursor_move":
        return peer if peer == "agent" and session.remote_control_enabled else None
    if msg_type.startswith("support.dom_"):
        return peer if peer == "requester" and session.dom_viewing_enabled else None
    return peer


async def _room_access(db: AsyncSession, room_id: str, user_id: str, msg_type: str) -> bool:
    from app.interviews.room_models import InterviewRoom, InterviewRoomParticipant

    try:
        rid, uid = uuid.UUID(room_id), uuid.UUID(user_id)
    except ValueError:
        return False
    room = await db.get(InterviewRoom, rid)
    if room is None:
        return False
    if msg_type == "interview.room_ended":
        return room.created_by == uid and room.status == "ended"
    if room.status == "ended":
        return False
    participant = await db.scalar(
        select(InterviewRoomParticipant.id).where(
            InterviewRoomParticipant.room_id == rid,
            InterviewRoomParticipant.user_id == uid,
            InterviewRoomParticipant.joined_at.is_not(None),
            InterviewRoomParticipant.left_at.is_(None),
        )
    )
    return participant is not None


# session_id → {requester_id, agent_id} in-memory relay map
_session_peers: dict[str, dict[str, str]] = {}

# room_id → set of user_ids currently in the room
_room_participants: dict[str, set[str]] = {}


@router.websocket("/ws")
async def websocket_endpoint(ws: WebSocket, token: str = "") -> None:
    from app.database import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        identity = await _identity(db, token)
    if identity is None:
        await ws.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    user_id, tenant_id, role = identity
    await manager.connect(ws, user_id, tenant_id, role)
    try:
        while True:
            data = await ws.receive_text()

            # Keepalive
            if data == "ping":
                await ws.send_text("pong")
                continue

            if len(data) > 1_048_576:
                await ws.close(code=status.WS_1009_MESSAGE_TOO_BIG)
                break

            # Parse JSON messages
            try:
                msg = json.loads(data)
            except (json.JSONDecodeError, ValueError):
                continue

            if not isinstance(msg, dict):
                continue
            msg_type = msg.get("type", "")
            session_id: str = msg.get("session_id", "")
            room_id: str = msg.get("room_id", "")

            if not all(isinstance(value, str) for value in (msg_type, session_id, room_id)):
                continue
            peer_role: str | None = None
            if msg_type.startswith("support."):
                async with AsyncSessionLocal() as db:
                    peer_role = await _support_access(db, session_id, user_id, msg_type)
                if peer_role is None:
                    continue
            if msg_type.startswith("interview.") and msg_type != "interview.room_leave":
                async with AsyncSessionLocal() as db:
                    if not await _room_access(db, room_id, user_id, msg_type):
                        continue
                # Never accept caller-supplied sender identity.
                msg = {**msg, "peer_id": user_id, "from_peer_id": user_id, "sender_id": user_id}

            # ── Support: register session peer mapping ────────────────────
            if msg_type == "support.session_join":
                if session_id and peer_role:
                    if session_id not in _session_peers:
                        _session_peers[session_id] = {}
                    _session_peers[session_id][peer_role] = user_id
                continue

            # ── Support: relay signaling / DOM / control messages ─────────
            if msg_type in SUPPORT_RELAY_TYPES and session_id:
                peers = _session_peers.get(session_id, {})
                # Determine target: send to the OTHER party in the session
                target_id: str | None = None
                if user_id == peers.get("requester"):
                    target_id = peers.get("agent")
                elif user_id == peers.get("agent"):
                    target_id = peers.get("requester")

                if target_id:
                    await manager.send_to_user(target_id, msg)
                continue

            # ── Interview room: register participant ──────────────────────
            if msg_type == "interview.room_join" and room_id:
                if room_id not in _room_participants:
                    _room_participants[room_id] = set()
                _room_participants[room_id].add(user_id)
                # Notify everyone else in the room that a new peer joined
                joined_msg = {**msg, "type": "interview.peer_joined", "peer_id": user_id}
                for peer_id in _room_participants[room_id]:
                    if peer_id != user_id:
                        await manager.send_to_user(peer_id, joined_msg)
                continue

            if msg_type == "interview.room_leave" and room_id:
                if user_id in _room_participants.get(room_id, set()):
                    _room_participants[room_id].discard(user_id)
                    if not _room_participants[room_id]:
                        del _room_participants[room_id]
                    else:
                        left_msg = {**msg, "type": "interview.peer_left", "peer_id": user_id}
                        for peer_id in _room_participants[room_id]:
                            await manager.send_to_user(peer_id, left_msg)
                continue

            # ── Interview room: P2P WebRTC (addressed to specific peer) ───
            if msg_type in INTERVIEW_P2P_TYPES and room_id:
                target_peer_id: str = msg.get("target_peer_id", "")
                participants = _room_participants.get(room_id, set())
                if user_id in participants and target_peer_id in participants:
                    await manager.send_to_user(target_peer_id, msg)
                continue

            # ── Interview room: broadcast to all room participants ─────────
            if msg_type in INTERVIEW_BROADCAST_TYPES and room_id:
                if msg_type in {"interview.peer_joined", "interview.peer_left"}:
                    continue  # Membership events are produced by the server.
                participants = _room_participants.get(room_id, set())
                if user_id not in participants:
                    continue
                for peer_id in participants:
                    if peer_id != user_id:
                        await manager.send_to_user(peer_id, msg)
                # Also deliver to sender (chat messages should appear in own UI)
                if msg_type == "interview.chat_message":
                    await manager.send_to_user(user_id, msg)
                continue

    except WebSocketDisconnect:
        pass
    finally:
        manager.disconnect(ws, user_id, tenant_id)
        if user_id not in manager.active_users():
            # Clean up support session peer registrations
            stale = [sid for sid, peers in _session_peers.items() if user_id in peers.values()]
            for sid in stale:
                peers = _session_peers[sid]
                if peers.get("requester") == user_id:
                    del peers["requester"]
                elif peers.get("agent") == user_id:
                    del peers["agent"]
            # Clean up interview room participation and notify peers
            for rid, participants in list(_room_participants.items()):
                if user_id in participants:
                    participants.discard(user_id)
                    if not participants:
                        del _room_participants[rid]
                    else:
                        left_msg = {
                            "type": "interview.peer_left",
                            "room_id": rid,
                            "peer_id": user_id,
                        }
                        for peer_id in participants:
                            await manager.send_to_user(peer_id, left_msg)
