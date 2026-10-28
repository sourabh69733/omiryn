"""Talks to the WhatsApp Cloud API (Meta): settings, webhook signatures and sending messages."""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
from urllib.parse import quote

import httpx

logger = logging.getLogger(__name__)

CHANNEL = "whatsapp"
# The first word of the message that connects an account: "connect <code>".
CONNECT_WORD = "connect"
_GRAPH_BASE = "https://graph.facebook.com"
# WhatsApp's limit is 4096 characters per text message.
_MAX_MESSAGE_CHARS = 4000


def whatsapp_enabled() -> bool:
    """On only when switched on and the token, number and both secrets are all set."""
    return (
        os.getenv("WHATSAPP_ENABLED", "false").strip().lower() == "true"
        and bool(_token())
        and bool(_phone_number_id())
        and bool(whatsapp_phone_number())
        and bool(whatsapp_app_secret())
        and bool(whatsapp_verify_token())
    )


def whatsapp_phone_number() -> str:
    """The business number people message, digits only (for wa.me links)."""
    return "".join(char for char in os.getenv("WHATSAPP_PHONE_NUMBER", "") if char.isdigit())


def whatsapp_app_secret() -> str:
    return os.getenv("WHATSAPP_APP_SECRET", "").strip()


def whatsapp_verify_token() -> str:
    return os.getenv("WHATSAPP_VERIFY_TOKEN", "").strip()


def whatsapp_allowed_for(email: str | None) -> bool:
    """WHATSAPP_ALLOWED_EMAILS limits connecting to test users; empty lets everyone connect."""
    allowed = {
        item.strip().casefold()
        for item in os.getenv("WHATSAPP_ALLOWED_EMAILS", "").split(",")
        if item.strip()
    }
    return not allowed or bool(email and email.strip().casefold() in allowed)


def whatsapp_start_url(code: str) -> str:
    """Opens WhatsApp with the connect message already typed; the user only taps send."""
    return f"https://wa.me/{whatsapp_phone_number()}?text={quote(f'{CONNECT_WORD} {code}')}"


def valid_whatsapp_signature(body: bytes, header: str | None) -> bool:
    """Meta signs each webhook body with the app secret (X-Hub-Signature-256: sha256=<hex>)."""
    secret = whatsapp_app_secret()
    if not secret or not header or not header.startswith("sha256="):
        return False
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header.removeprefix("sha256="))


async def send_whatsapp_message(to: str, text: str) -> bool:
    """Send plain text, split when longer than WhatsApp allows. False if any part failed."""
    sent = True
    for chunk in _chunks(text):
        sent = await _call({"to": to, "type": "text", "text": {"body": chunk}}) and sent
    return sent


async def send_whatsapp_typing(message_id: str) -> None:
    """Marks the user's message read and shows "typing…" (until a reply or about 25 seconds)."""
    await _call({"status": "read", "message_id": message_id, "typing_indicator": {"type": "text"}})


async def _call(payload: dict[str, object]) -> bool:
    version = os.getenv("WHATSAPP_GRAPH_VERSION", "v23.0").strip()
    url = f"{_GRAPH_BASE}/{version}/{_phone_number_id()}/messages"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(
                url,
                json={"messaging_product": "whatsapp", **payload},
                headers={"Authorization": f"Bearer {_token()}"},
            )
    except httpx.HTTPError as error:
        logger.warning("whatsapp.send.failed error=%s", type(error).__name__)
        return False
    if response.status_code != 200:
        # The body names the problem (expired token, number not allowed); it never holds the token.
        logger.warning("whatsapp.send.failed status=%s body=%s", response.status_code, response.text[:200])
        return False
    return True


def _chunks(text: str) -> list[str]:
    text = text.strip()
    return [text[start : start + _MAX_MESSAGE_CHARS] for start in range(0, len(text), _MAX_MESSAGE_CHARS)]


def _token() -> str:
    return os.getenv("WHATSAPP_ACCESS_TOKEN", "").strip()


def _phone_number_id() -> str:
    return os.getenv("WHATSAPP_PHONE_NUMBER_ID", "").strip()
