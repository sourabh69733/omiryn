"""Talks to the Telegram Bot API: settings and sending messages."""

from __future__ import annotations

import logging
import os

import httpx

logger = logging.getLogger(__name__)

CHANNEL = "telegram"
_API_BASE = "https://api.telegram.org"
# Telegram's limit is 4096 characters per message.
_MAX_MESSAGE_CHARS = 4000


def telegram_enabled() -> bool:
    """On only when switched on and the bot token, name and webhook secret are all set."""
    return (
        os.getenv("TELEGRAM_ENABLED", "false").strip().lower() == "true"
        and bool(_token())
        and bool(telegram_bot_username())
        and bool(telegram_webhook_secret())
    )


def telegram_bot_username() -> str:
    return os.getenv("TELEGRAM_BOT_USERNAME", "").strip().lstrip("@")


def telegram_webhook_secret() -> str:
    return os.getenv("TELEGRAM_WEBHOOK_SECRET", "").strip()


def telegram_allowed_for(email: str | None) -> bool:
    """TELEGRAM_ALLOWED_EMAILS limits linking to test users; empty lets everyone link."""
    allowed = {
        item.strip().casefold()
        for item in os.getenv("TELEGRAM_ALLOWED_EMAILS", "").split(",")
        if item.strip()
    }
    return not allowed or bool(email and email.strip().casefold() in allowed)


def telegram_start_url(code: str) -> str:
    return f"https://t.me/{telegram_bot_username()}?start={code}"


async def send_telegram_message(chat_id: str, text: str) -> bool:
    """Send plain text, split when longer than Telegram allows. False if any part failed."""
    sent = True
    for chunk in _chunks(text):
        sent = await _call("sendMessage", {"chat_id": chat_id, "text": chunk}) and sent
    return sent


async def send_telegram_typing(chat_id: str) -> None:
    """Shows "typing…" in the chat for about five seconds."""
    await _call("sendChatAction", {"chat_id": chat_id, "action": "typing"})


async def _call(method: str, payload: dict[str, object]) -> bool:
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(f"{_API_BASE}/bot{_token()}/{method}", json=payload)
    except httpx.HTTPError as error:
        logger.warning("telegram.%s.failed error=%s", method, type(error).__name__)
        return False
    if response.status_code != 200:
        # The body names the problem (blocked bot, bad chat id); it never holds the token.
        logger.warning("telegram.%s.failed status=%s body=%s", method, response.status_code, response.text[:200])
        return False
    return True


def _chunks(text: str) -> list[str]:
    text = text.strip()
    return [text[start : start + _MAX_MESSAGE_CHARS] for start in range(0, len(text), _MAX_MESSAGE_CHARS)]


def _token() -> str:
    return os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
