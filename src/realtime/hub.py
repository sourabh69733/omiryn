"""Tracks live sockets and transports events to authorized user/conversation rooms.

Sockets are per process, so which chats are open is also written to the database
(`live_presence`) with this instance's id and refreshed by a heartbeat. Background jobs on any
instance can then tell whether a user is watching, and where.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from uuid import uuid4

from fastapi import WebSocket

from agent.shared.clock import utc_now

from .contracts import RealtimeEvent

logger = logging.getLogger(__name__)

HEARTBEAT_SECONDS = 20.0


@dataclass
class RealtimeConnection:
    id: str
    user_id: str
    socket: WebSocket
    rooms: set[str] = field(default_factory=set)


class InMemoryRealtimeHub:
    """Single-process hub behind an interface that can later use Redis or Postgres pub/sub."""

    def __init__(self, instance_id: str | None = None) -> None:
        self.instance_id = instance_id or str(uuid4())
        self._connections: dict[str, RealtimeConnection] = {}
        self._rooms: dict[str, set[str]] = {}
        self._lock = asyncio.Lock()
        self._heartbeat: asyncio.Task[None] | None = None

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
        await self._write_presence()

    async def subscribe(
        self,
        connection: RealtimeConnection,
        scope: str,
        scope_id: str,
    ) -> None:
        async with self._lock:
            self._join_locked(connection, _room(scope, scope_id))
        if scope == "conversation":
            await self._write_presence()

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
        if scope == "conversation":
            await self._write_presence()

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

    async def live_everywhere(self) -> dict[tuple[str, str], set[str]]:
        """(user_id, conversation_id) -> instance ids with a socket on it, across all instances;
        this instance's own sockets are counted from memory, so they are never stale."""
        from storage import live_conversations_everywhere

        live = await asyncio.to_thread(live_conversations_everywhere, now=utc_now())
        for key in await self.live_conversations():
            live.setdefault(key, set()).add(self.instance_id)
        return live

    def start_heartbeat(self) -> None:
        if self._heartbeat is None:
            self._heartbeat = asyncio.create_task(self._heartbeat_loop(), name="realtime-presence")

    async def stop_heartbeat(self) -> None:
        if self._heartbeat is not None:
            self._heartbeat.cancel()
            await asyncio.gather(self._heartbeat, return_exceptions=True)
            self._heartbeat = None
        await self._write_presence()

    async def _heartbeat_loop(self) -> None:
        while True:
            await asyncio.sleep(HEARTBEAT_SECONDS)
            await self._write_presence()

    async def _write_presence(self) -> None:
        """Rewrite this instance's presence rows from its sockets; best effort."""
        from storage import refresh_live

        try:
            await asyncio.to_thread(refresh_live, self.instance_id, await self.live_conversations(), now=utc_now())
        except Exception:
            logger.warning("realtime.presence.write_failed instance=%s", self.instance_id, exc_info=True)

    async def reset(self) -> None:
        """Clear live state for deterministic tests and development shutdowns."""
        async with self._lock:
            self._connections.clear()
            self._rooms.clear()
        await self._write_presence()

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
