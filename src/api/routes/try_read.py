"""The read, before sign-in: what a WhatsApp chat says about the two people in it.

`POST /api/public/chat-read` takes the exported chat and which name is the sender's, reads it in
memory and answers with the same read a signed-in upload gets. Nothing from the chat is stored:
not the text, not the names, not the read. What is kept is one row that a read was made (for the
daily limits) with a mark of the address that cannot be turned back into it.

The answer carries a seal of the read (`kept`). After sign-in the app shares the chat the usual
way and sends the seal along, and the read they already saw is kept instead of written again.

This is the one place a person with no account can spend money on a model, so it is limited per
address and for everyone together per day (PUBLIC_CHAT_READ_PER_ADDRESS_DAILY, default 3, and
PUBLIC_CHAT_READ_DAILY_LIMIT, default 100; 0 turns the page off). A chat that cannot have a read
(a group, too short) is turned away by code before anything is counted or paid for.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Request

from agent.cognition.background.uploads.chat_read import build_chat_read, why_no_read
from agent.cognition.background.uploads.sealed_read import keyed_mark, seal_read
from agent.shared.timeline import user_zone
from ingestion.upload_chat import whatsapp_upload_messages
from storage import reserve_public_event

from ..ip_location import client_ip
from ..models import PublicChatRead
from .public import SERVER_EVENT_PREFIX

router = APIRouter()
logger = logging.getLogger(__name__)

TRY_READ_EVENT = f"{SERVER_EVENT_PREFIX}try_read"
DAILY_LIMIT = 100
PER_ADDRESS_DAILY = 3
_DAY = timedelta(hours=24)


@router.post("/api/public/chat-read")
async def try_chat_read(payload: PublicChatRead, request: Request) -> dict[str, object]:
    daily = _env_int("PUBLIC_CHAT_READ_DAILY_LIMIT", DAILY_LIMIT)
    if daily <= 0:
        raise HTTPException(status_code=404, detail="Sign in to get your read.")
    zone = user_zone(request.headers.get("x-timezone"))
    try:
        messages = whatsapp_upload_messages(payload.content, payload.user_sender, zone)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    why_not = why_no_read(messages)
    if why_not:
        return {"state": why_not}

    address = client_ip(request.headers.get("x-forwarded-for"), request.client.host if request.client else None) or "unknown"
    refused = reserve_public_event(
        TRY_READ_EVENT,
        keyed_mark(address, "try-read-address"),
        since=datetime.now(timezone.utc) - _DAY,
        total_limit=daily,
        session_limit=_env_int("PUBLIC_CHAT_READ_PER_ADDRESS_DAILY", PER_ADDRESS_DAILY),
        metadata={"messages": len(messages)},
        path="/try",
    )
    if refused:
        detail = "You've had today's free reads. Sign in to read more chats." if refused == "session" else "A lot of people are trying this right now. Sign in to get your read, or come back tomorrow."
        raise HTTPException(status_code=429, detail={"code": "sign_in_to_read", "message": detail})

    me = payload.user_sender.split()[0]
    read = await build_chat_read(messages, me=me, zone=zone, conversation_id="", model=os.getenv("PUBLIC_CHAT_READ_MODEL", "").strip() or None)
    logger.info("agent.try_read state=%s messages=%s written=%s", read.get("state"), len(messages), bool(read.get("written")))
    if read.get("state") != "ready":
        return read
    return {**read, "kept": seal_read(read)}


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, "").strip() or default)
    except ValueError:
        return default


__all__ = ["router"]
