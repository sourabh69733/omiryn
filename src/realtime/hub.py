"""Tracks live sockets and transports events to authorized user/conversation rooms."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from uuid import uuid4

from fastapi import WebSocket

from .contracts import RealtimeEvent


@dataclass
class RealtimeConnection:
    id: str
    user_id: str
    socket: WebSocket
    rooms: set[str] = field(default_factory=set)


class InMemoryRealtimeHub:
    """Single-process hub behind an interface that can later use Redis or Postgres pub/sub."""

    def __init__(self) -> None:
        self._connections: dict[str, RealtimeConnection] = {}
        self._rooms: dict[str, set[str]] = {}
        self._lock = asyncio.Lock()

    async def register(self, socket: WebSocket, user_id: str) -> RealtimeConnection:
        connection = RealtimeConnection(id=str(uuid4()), user_id=user_id, socket=socket)
        async with self._lock:
            self._connections[connection.id] = connection
            self._join_locked(connection, _room("user", user_id))
        return connection

    async def unregister(self, connection: RealtimeConnection) -> None:
        async with self._lock:
            self._connections.pop(connection.id, None)
            for room in tuple(connection.rooms):
                members = self._rooms.get(room)
                if members is not None:
                    members.discard(connection.id)
                    if not members:
                        self._rooms.pop(room, None)
            connection.rooms.clear()

    async def subscribe(
        self,
        connection: RealtimeConnection,
        scope: str,
        scope_id: str,
    ) -> None:
        async with self._lock:
            self._join_locked(connection, _room(scope, scope_id))

    async def unsubscribe(
        self,
        connection: RealtimeConnection,
        scope: str,
        scope_id: str,
    ) -> None:
        room = _room(scope, scope_id)
        async with self._lock:
            connection.rooms.discard(room)
            members = self._rooms.get(room)
            if members is not None:
                members.discard(connection.id)
                if not members:
                    self._rooms.pop(room, None)

    async def publish(self, event: RealtimeEvent) -> int:
        room = _room(event.scope, event.scope_id)
        async with self._lock:
            targets = [
                self._connections[connection_id]
                for connection_id in self._rooms.get(room, set())
                if connection_id in self._connections
            ]
        delivered = 0
        stale: list[RealtimeConnection] = []
        for connection in targets:
            try:
                await connection.socket.send_json(event.as_dict())
                delivered += 1
            except Exception:
                stale.append(connection)
        for connection in stale:
            await self.unregister(connection)
        return delivered

    async def live_conversations(self) -> list[tuple[str, str]]:
        """Return (user_id, conversation_id) pairs that have a socket watching right now."""
        async with self._lock:
            return sorted(
                {
                    (connection.user_id, room.removeprefix("conversation:"))
                    for connection in self._connections.values()
                    for room in connection.rooms
                    if room.startswith("conversation:")
                }
            )

    async def reset(self) -> None:
        """Clear live state for deterministic tests and development shutdowns."""
        async with self._lock:
            self._connections.clear()
            self._rooms.clear()

    def _join_locked(self, connection: RealtimeConnection, room: str) -> None:
        connection.rooms.add(room)
        self._rooms.setdefault(room, set()).add(connection.id)


def _room(scope: str, scope_id: str) -> str:
    if scope not in {"user", "conversation"}:
        raise ValueError(f"Unsupported realtime scope: {scope}")
    clean_scope_id = str(scope_id or "").strip()
    if not clean_scope_id:
        raise ValueError("Realtime room requires a scope id.")
    return f"{scope}:{clean_scope_id}"


realtime_hub = InMemoryRealtimeHub()
