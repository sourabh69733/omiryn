"""Chat with Omi on Telegram: connect from Profile, then talk to Omi in its own Telegram chat.

The Telegram chat is separate from the web chat; memories and vibe are shared."""

from __future__ import annotations

import hmac
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException

from channels.telegram import (
    CHANNEL,
    send_telegram_message,
    send_telegram_typing,
    telegram_allowed_for,
    telegram_bot_username,
    telegram_enabled,
    telegram_start_url,
    telegram_webhook_secret,
)
from security.auth import CurrentUser, require_user
from storage import (
    channel_link_for_chat,
    channel_link_for_user,
    claim_channel_update,
    consume_channel_link_code,
    create_channel_link_code,
    link_channel_chat,
    unlink_channel,
)

from ..helpers import _user_id
from .channel_replies import REPLY_FAILED, ChannelSender, handle_channel_message

router = APIRouter()

_CONNECT_HINT = "To chat with Omi here, open Omiryn, go to Profile and tap Connect Telegram."
_LINKED = "Connected. This is your own chat with Omi, and it knows what you share in the app too. Say hi!"
_EXPIRED = "That link has expired. Open Omiryn, go to Profile and tap Connect Telegram for a new one."
_DISCONNECTED = "Disconnected. Omi won't read this chat anymore. You can reconnect from Profile any time."
_TEXT_ONLY = "I can only read text here for now."
_REPLY_FAILED = REPLY_FAILED


# Looked up when called, so tests can patch this module's send functions.
async def _send_text(chat_id: str, text: str) -> None:
    await send_telegram_message(chat_id, text)


async def _send_typing(chat_id: str) -> None:
    await send_telegram_typing(chat_id)


# Telegram shows "typing…" for about five seconds; it is renewed every four.
_SENDER = ChannelSender(CHANNEL, _send_text, _send_typing, typing_refresh_seconds=4.0)


@router.get("/api/channels/telegram")
async def telegram_status(user: CurrentUser = Depends(require_user)) -> dict[str, Any]:
    available = telegram_enabled() and telegram_allowed_for(user.email)
    link = channel_link_for_user(_user_id(user), CHANNEL) if available else None
    return {
        "available": available,
        "connected": link is not None,
        "bot_username": telegram_bot_username() if available else None,
    }


@router.post("/api/channels/telegram/link")
async def create_telegram_link(user: CurrentUser = Depends(require_user)) -> dict[str, Any]:
    """A t.me link with a one-time code; opening it in Telegram and tapping Start connects."""
    if not telegram_enabled():
        raise HTTPException(status_code=404, detail="Telegram isn't available.")
    if not telegram_allowed_for(user.email):
        raise HTTPException(status_code=403, detail="Telegram is in testing and not open to your account yet.")
    code, expires_at = create_channel_link_code(_user_id(user), CHANNEL)
    return {"url": telegram_start_url(code), "expires_at": expires_at.isoformat()}


@router.delete("/api/channels/telegram")
async def disconnect_telegram(user: CurrentUser = Depends(require_user)) -> dict[str, Any]:
    link = unlink_channel(_user_id(user), CHANNEL)
    if link and telegram_enabled():
        await send_telegram_message(link["external_chat_id"], _DISCONNECTED)
    return {"connected": False}


@router.post("/api/channels/telegram/webhook")
async def telegram_webhook(
    update: dict[str, Any],
    background_tasks: BackgroundTasks,
    secret: str | None = Header(default=None, alias="X-Telegram-Bot-Api-Secret-Token"),
) -> dict[str, bool]:
    """Telegram calls this for every message to the bot. It always gets 200 once the secret
    checks out: a failure is told to the user in the chat, and a retry would only repeat it."""
    if not telegram_enabled():
        raise HTTPException(status_code=404, detail="Not found.")
    if not hmac.compare_digest((secret or "").encode(), telegram_webhook_secret().encode()):
        raise HTTPException(status_code=401, detail="Bad secret.")
    message = update.get("message")
    if not isinstance(message, dict):
        return {"ok": True}
    chat = message.get("chat") or {}
    if chat.get("type") != "private" or chat.get("id") is None:
        # Group chats are not supported yet.
        return {"ok": True}
    chat_id = str(chat["id"])
    text = message.get("text")
    text = text.strip() if isinstance(text, str) else ""

    if text.startswith("/start"):
        await _start(chat_id, text.removeprefix("/start").strip())
        return {"ok": True}
    link = channel_link_for_chat(CHANNEL, chat_id)
    if link is None:
        await send_telegram_message(chat_id, _CONNECT_HINT)
        return {"ok": True}
    update_id = update.get("update_id")
    if isinstance(update_id, int) and not claim_channel_update(CHANNEL, chat_id, update_id):
        return {"ok": True}
    if text in {"/disconnect", "/stop"}:
        unlink_channel(link["user_id"], CHANNEL)
        await send_telegram_message(chat_id, _DISCONNECTED)
        return {"ok": True}
    if not text:
        await send_telegram_message(chat_id, _TEXT_ONLY)
        return {"ok": True}

    # On Cloud Run the server has CPU only while a request is open, so the first message's
    # request stays open until every message of the burst is answered.
    await handle_channel_message(_SENDER, chat_id, CurrentUser(id=link["user_id"]), text, background_tasks)
    return {"ok": True}


async def _start(chat_id: str, code: str) -> None:
    if not code:
        already = channel_link_for_chat(CHANNEL, chat_id)
        await send_telegram_message(chat_id, "You're connected. Just say hi!" if already else _CONNECT_HINT)
        return
    user_id = consume_channel_link_code(code, CHANNEL)
    if user_id is None:
        await send_telegram_message(chat_id, _EXPIRED)
        return
    link_channel_chat(user_id, CHANNEL, chat_id)
    await send_telegram_message(chat_id, _LINKED)
