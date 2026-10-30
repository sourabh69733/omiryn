"""Chat with Omi on WhatsApp: connect from Profile, then talk to Omi in its own WhatsApp chat.

The WhatsApp chat is separate from the web chat; memories and vibe are shared. Meta wants the
webhook answered at once, so messages are handled in the background after the 200.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse

from channels.whatsapp import (
    CHANNEL,
    CONNECT_WORD,
    send_whatsapp_message,
    send_whatsapp_typing,
    valid_whatsapp_signature,
    whatsapp_allowed_for,
    whatsapp_enabled,
    whatsapp_start_url,
    whatsapp_verify_token,
)
from security.auth import CurrentUser, require_user
from storage import (
    channel_link_for_chat,
    channel_link_for_user,
    claim_channel_message,
    consume_channel_link_code,
    create_channel_link_code,
    link_channel_chat,
    unlink_channel,
)

from ..helpers import _user_id
from .channel_replies import REPLY_FAILED, ChannelSender, handle_channel_message

router = APIRouter()
logger = logging.getLogger(__name__)

_CONNECT_HINT = "To chat with Omi here, open Omiryn, go to Profile and tap Connect WhatsApp."
_LINKED = "Connected. This is your own chat with Omi, and it knows what you share in the app too. Say hi!"
_EXPIRED = "That link has expired. Open Omiryn, go to Profile and tap Connect WhatsApp for a new one."
_DISCONNECTED = "Disconnected. Omi won't read this chat anymore. You can reconnect from Profile any time."
_TEXT_ONLY = "I can only read text here for now."
_REPLY_FAILED = REPLY_FAILED
_DISCONNECT_WORDS = {"disconnect", "stop"}

# The newest message from each chat, which WhatsApp needs to show "typing…" there. Per process
# on purpose: a stale id only means the typing indicator is skipped.
_last_message_ids: dict[str, str] = {}
# Background work started by the webhook, kept so it is not garbage-collected mid-run.
_pending: set[asyncio.Task] = set()


# Looked up when called, so tests can patch this module's send functions.
async def _send_text(chat_id: str, text: str) -> None:
    await send_whatsapp_message(chat_id, text)


async def _send_typing(chat_id: str) -> None:
    message_id = _last_message_ids.get(chat_id)
    if message_id:
        await send_whatsapp_typing(message_id)


# WhatsApp's typing indicator lasts until the reply or about 25 seconds.
_SENDER = ChannelSender(CHANNEL, _send_text, _send_typing, typing_refresh_seconds=20.0)


@router.get("/api/channels/whatsapp")
async def whatsapp_status(user: CurrentUser = Depends(require_user)) -> dict[str, Any]:
    available = whatsapp_enabled() and whatsapp_allowed_for(user.email)
    link = channel_link_for_user(_user_id(user), CHANNEL) if available else None
    return {"available": available, "connected": link is not None}


@router.post("/api/channels/whatsapp/link")
async def create_whatsapp_link(user: CurrentUser = Depends(require_user)) -> dict[str, Any]:
    """A wa.me link with "connect <one-time code>" typed in; sending it connects."""
    if not whatsapp_enabled():
        raise HTTPException(status_code=404, detail="WhatsApp isn't available.")
    if not whatsapp_allowed_for(user.email):
        raise HTTPException(status_code=403, detail="WhatsApp is in testing and not open to your account yet.")
    code, expires_at = create_channel_link_code(_user_id(user), CHANNEL)
    return {"url": whatsapp_start_url(code), "expires_at": expires_at.isoformat()}


@router.delete("/api/channels/whatsapp")
async def disconnect_whatsapp(user: CurrentUser = Depends(require_user)) -> dict[str, Any]:
    link = unlink_channel(_user_id(user), CHANNEL)
    if link and whatsapp_enabled():
        await send_whatsapp_message(link["external_chat_id"], _DISCONNECTED)
    return {"connected": False}


@router.get("/api/channels/whatsapp/webhook")
async def verify_whatsapp_webhook(
    mode: str | None = Query(default=None, alias="hub.mode"),
    token: str | None = Query(default=None, alias="hub.verify_token"),
    challenge: str | None = Query(default=None, alias="hub.challenge"),
) -> PlainTextResponse:
    """Meta calls this once when the webhook URL is saved; echoing the challenge confirms it."""
    if not whatsapp_enabled():
        raise HTTPException(status_code=404, detail="Not found.")
    if mode != "subscribe" or token != whatsapp_verify_token() or challenge is None:
        raise HTTPException(status_code=403, detail="Verification failed.")
    return PlainTextResponse(challenge)


@router.post("/api/channels/whatsapp/webhook")
async def whatsapp_webhook(
    request: Request,
    signature: str | None = Header(default=None, alias="X-Hub-Signature-256"),
) -> dict[str, bool]:
    if not whatsapp_enabled():
        raise HTTPException(status_code=404, detail="Not found.")
    body = await request.body()
    if not valid_whatsapp_signature(body, signature):
        raise HTTPException(status_code=401, detail="Bad signature.")
    try:
        payload = json.loads(body)
    except ValueError:
        return {"ok": True}
    for message in _incoming_messages(payload):
        # Meta may deliver a message more than once, to any instance; each is answered once.
        if not claim_channel_message(CHANNEL, str(message.get("id") or "")):
            continue
        task = asyncio.create_task(_handle(message))
        _pending.add(task)
        task.add_done_callback(_pending.discard)
    return {"ok": True}


def _incoming_messages(payload: Any) -> list[dict[str, Any]]:
    """User messages in a webhook body; delivery and read receipts are skipped."""
    if not isinstance(payload, dict):
        return []
    messages = []
    for entry in payload.get("entry") or []:
        for change in (entry or {}).get("changes") or []:
            value = (change or {}).get("value") or {}
            messages.extend(message for message in value.get("messages") or [] if isinstance(message, dict))
    return messages


async def _handle(message: dict[str, Any]) -> None:
    try:
        await _handle_message(message)
    except Exception:
        logger.exception("whatsapp.message.failed")


async def _handle_message(message: dict[str, Any]) -> None:
    chat_id = str(message.get("from") or "")
    if not chat_id:
        return
    if message.get("id"):
        _last_message_ids[chat_id] = str(message["id"])
    text = ((message.get("text") or {}).get("body") or "").strip() if message.get("type") == "text" else ""

    first, _, rest = text.partition(" ")
    if first.casefold() == CONNECT_WORD and rest.strip():
        await _connect(chat_id, rest.strip())
        return
    link = channel_link_for_chat(CHANNEL, chat_id)
    if link is None:
        await send_whatsapp_message(chat_id, _CONNECT_HINT)
        return
    if text.casefold() in _DISCONNECT_WORDS:
        unlink_channel(link["user_id"], CHANNEL)
        await send_whatsapp_message(chat_id, _DISCONNECTED)
        return
    if not text:
        await send_whatsapp_message(chat_id, _TEXT_ONLY)
        return

    # The request has already returned, so background learning runs here when the reply is done.
    tasks = BackgroundTasks()
    await handle_channel_message(_SENDER, chat_id, CurrentUser(id=link["user_id"]), text, tasks)
    await tasks()


async def _connect(chat_id: str, code: str) -> None:
    user_id = consume_channel_link_code(code, CHANNEL)
    if user_id is None:
        await send_whatsapp_message(chat_id, _EXPIRED)
        return
    link_channel_chat(user_id, CHANNEL, chat_id)
    await send_whatsapp_message(chat_id, _LINKED)
