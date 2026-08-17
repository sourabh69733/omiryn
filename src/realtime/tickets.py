"""Issues short-lived signed tickets so browsers never put access tokens in WebSocket URLs."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from typing import Any
from uuid import uuid4


class RealtimeTicketError(ValueError):
    pass


def issue_realtime_ticket(
    user_id: str,
    *,
    ttl_seconds: int = 60,
    now: int | None = None,
) -> dict[str, Any]:
    clean_user_id = str(user_id or "").strip()
    if not clean_user_id:
        raise ValueError("Realtime ticket requires a user id.")
    if not 1 <= ttl_seconds <= 300:
        raise ValueError("Realtime ticket lifetime must be between 1 and 300 seconds.")
    issued_at = int(time.time() if now is None else now)
    payload = {
        "sub": clean_user_id,
        "iat": issued_at,
        "exp": issued_at + ttl_seconds,
        "jti": str(uuid4()),
        "aud": "omiryn-realtime-v1",
    }
    encoded = _base64url(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode())
    signature = _signature(encoded)
    return {
        "ticket": f"{encoded}.{signature}",
        "expires_at": payload["exp"],
        "expires_in_seconds": ttl_seconds,
    }


def verify_realtime_ticket(ticket: str, *, now: int | None = None) -> str:
    try:
        encoded, supplied_signature = str(ticket or "").split(".", 1)
    except ValueError as error:
        raise RealtimeTicketError("Malformed realtime ticket.") from error
    if not hmac.compare_digest(_signature(encoded), supplied_signature):
        raise RealtimeTicketError("Invalid realtime ticket signature.")
    try:
        payload = json.loads(_base64url_decode(encoded))
    except (ValueError, json.JSONDecodeError) as error:
        raise RealtimeTicketError("Malformed realtime ticket payload.") from error
    current_time = int(time.time() if now is None else now)
    if payload.get("aud") != "omiryn-realtime-v1":
        raise RealtimeTicketError("Invalid realtime ticket audience.")
    if not isinstance(payload.get("exp"), int) or payload["exp"] < current_time:
        raise RealtimeTicketError("Realtime ticket expired.")
    user_id = str(payload.get("sub") or "").strip()
    if not user_id:
        raise RealtimeTicketError("Realtime ticket has no user.")
    return user_id


def _signature(encoded_payload: str) -> str:
    return _base64url(
        hmac.new(_ticket_secret(), encoded_payload.encode(), hashlib.sha256).digest()
    )


def _ticket_secret() -> bytes:
    explicit = os.getenv("REALTIME_TICKET_SECRET", "").strip()
    if explicit:
        return explicit.encode()
    encrypted_data_key = os.getenv("ENCRYPTION_MASTER_KEY", "").strip()
    if encrypted_data_key:
        try:
            decoded = base64.urlsafe_b64decode(
                encrypted_data_key + "=" * (-len(encrypted_data_key) % 4)
            )
        except ValueError:
            decoded = b""
        if decoded:
            # Domain separation prevents a realtime signature from being useful as an encryption key.
            return hmac.new(decoded, b"omiryn-realtime-ticket-v1", hashlib.sha256).digest()
    return b"omiryn-local-development-realtime-ticket-v1"


def _base64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode().rstrip("=")


def _base64url_decode(value: str) -> str:
    decoded = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    return decoded.decode()
