"""Exposes authenticated realtime tickets and the generic WebSocket gateway."""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Depends, Query, WebSocket, WebSocketDisconnect

from agent.cognition.background.idle import catch_up_pending
from agent.proactive import schedule_return_greeting
from realtime import RealtimeTicketError, issue_realtime_ticket, realtime_hub
from realtime.tickets import verify_realtime_ticket
from security.auth import CurrentUser, production_runtime_enabled, require_user
from security.config import configured_cors_origins
from storage import delete_stale_temporary_conversations, get_conversation, prune_threads_from_missing_chats

router = APIRouter()


@router.post("/api/realtime/ticket", status_code=201)
async def create_realtime_ticket(
    user: CurrentUser = Depends(require_user),
) -> dict[str, object]:
    return issue_realtime_ticket(user.id)


@router.websocket("/api/realtime")
async def realtime_websocket(
    websocket: WebSocket,
    ticket: str = Query(..., min_length=20, max_length=2000),
) -> None:
    if not _origin_allowed(websocket.headers.get("origin")):
        await websocket.close(code=4403, reason="Origin is not allowed.")
        return
    try:
        user_id = verify_realtime_ticket(ticket)
    except RealtimeTicketError:
        await websocket.close(code=4401, reason="Invalid or expired realtime ticket.")
        return

    await websocket.accept()
    connection = await realtime_hub.register(websocket, user_id)
    # The open connection keeps the server's CPU on, so memory work missed while the user was
    # away runs now.
    task = asyncio.create_task(_catch_up(user_id))
    _catch_up_tasks.add(task)
    task.add_done_callback(_catch_up_tasks.discard)
    await websocket.send_json(
        {
            "type": "realtime.connected",
            "version": 1,
            "payload": {"connection_id": connection.id},
        }
    )
    try:
        while True:
            command = await websocket.receive_json()
            await _handle_command(websocket, connection, command)
    except WebSocketDisconnect:
        pass
    finally:
        await realtime_hub.unregister(connection)


# Running catch-ups, held so they are not garbage-collected before they finish.
_catch_up_tasks: set[asyncio.Task[None]] = set()


async def _catch_up(user_id: str) -> None:
    try:
        await asyncio.to_thread(prune_threads_from_missing_chats, user_id)
        await asyncio.to_thread(delete_stale_temporary_conversations, user_id)
        await asyncio.to_thread(catch_up_pending, user_id)
    except Exception:
        logging.getLogger(__name__).exception("agent.memory_catch_up_failed")


async def _handle_command(websocket: WebSocket, connection, command: object) -> None:
    if not isinstance(command, dict):
        await _command_error(websocket, "Command must be an object.")
        return
    command_type = str(command.get("type") or "").strip()
    if command_type == "ping":
        await websocket.send_json({"type": "pong", "version": 1, "payload": {}})
        return
    scope = str(command.get("scope") or "").strip()
    scope_id = str(command.get("scope_id") or "").strip()
    if command_type not in {"subscribe", "unsubscribe"} or scope != "conversation" or not scope_id:
        await _command_error(websocket, "Unsupported realtime command.")
        return
    if get_conversation(scope_id, connection.user_id) is None:
        await _command_error(websocket, "Conversation is unavailable.")
        return
    if command_type == "subscribe":
        await realtime_hub.subscribe(connection, scope, scope_id)
        # Opening a chat after a long gap may earn a short greeting if the user stays quiet.
        schedule_return_greeting(connection.user_id, scope_id)
    else:
        await realtime_hub.unsubscribe(connection, scope, scope_id)
    await websocket.send_json(
        {
            "type": f"realtime.{command_type}d",
            "version": 1,
            "payload": {"scope": scope, "scope_id": scope_id},
        }
    )


async def _command_error(websocket: WebSocket, message: str) -> None:
    await websocket.send_json(
        {"type": "realtime.error", "version": 1, "payload": {"message": message}}
    )


def _origin_allowed(origin: str | None) -> bool:
    if not production_runtime_enabled() or not origin:
        return True
    normalized = origin.strip().rstrip("/")
    return normalized in configured_cors_origins()
