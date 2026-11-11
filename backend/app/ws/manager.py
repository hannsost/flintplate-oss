"""WebSocket connection manager.

Single-worker in-memory registry. Per user, multiple tabs/devices are supported.
Redis pub/sub can be layered on top later for multi-worker deployments.
"""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from typing import Any

from fastapi import WebSocket

log = logging.getLogger(__name__)


class ConnectionManager:
    def __init__(self) -> None:
        # user_id (str) → set of active WebSocket connections
        self._connections: dict[str, set[WebSocket]] = defaultdict(set)
        # tenant_id (str) → set of user_ids currently connected
        self._tenant_users: dict[str, set[str]] = defaultdict(set)
        # role (str) → set of user_ids currently connected (for support broadcast)
        self._role_users: dict[str, set[str]] = defaultdict(set)
        # user_id → role (for cleanup on disconnect)
        self._user_role: dict[str, str] = {}

    async def connect(
        self, ws: WebSocket, user_id: str, tenant_id: str | None = None, role: str | None = None
    ) -> None:
        await ws.accept()
        self._connections[user_id].add(ws)
        if tenant_id:
            self._tenant_users[tenant_id].add(user_id)
        if role:
            self._role_users[role].add(user_id)
            self._user_role[user_id] = role
        log.debug(
            "WS connect: user=%s tenant=%s role=%s total=%d",
            user_id,
            tenant_id,
            role,
            len(self._connections[user_id]),
        )

    def disconnect(self, ws: WebSocket, user_id: str, tenant_id: str | None = None) -> None:
        self._connections[user_id].discard(ws)
        if tenant_id and not self._connections[user_id]:
            self._tenant_users[tenant_id].discard(user_id)
        if not self._connections[user_id]:
            role = self._user_role.pop(user_id, None)
            if role:
                self._role_users[role].discard(user_id)
        log.debug("WS disconnect: user=%s remaining=%d", user_id, len(self._connections[user_id]))

    async def send_to_user(self, user_id: str, event: dict[str, Any]) -> None:
        """Push a JSON event to all active connections for a user."""
        sockets = list(self._connections.get(user_id, set()))
        if not sockets:
            return
        message = json.dumps(event, default=str)
        dead: set[WebSocket] = set()
        for ws in sockets:
            try:
                await ws.send_text(message)
            except Exception:
                dead.add(ws)
        if dead:
            self._connections[user_id] -= dead

    async def broadcast_to_tenant(self, tenant_id: str, event: dict[str, Any]) -> None:
        """Push a JSON event to all connected users in a tenant."""
        user_ids = list(self._tenant_users.get(tenant_id, set()))
        for user_id in user_ids:
            await self.send_to_user(user_id, event)

    async def broadcast_to_role(self, role: str, event: dict[str, Any]) -> None:
        """Push a JSON event to all connected users with a given role."""
        user_ids = list(self._role_users.get(role, set()))
        for user_id in user_ids:
            await self.send_to_user(user_id, event)

    def active_users(self) -> list[str]:
        return [uid for uid, conns in self._connections.items() if conns]


# Module-level singleton – imported by service layer and WS router
manager = ConnectionManager()
