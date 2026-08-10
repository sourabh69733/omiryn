"""Safely decodes structured companion output before it can reach a user-facing reply."""

from __future__ import annotations

import json
from typing import Any


def structured_companion_reply(raw_text: str) -> str | None:
    """Return a reply from a JSON or textual-function envelope, when one is present."""
    payload = _structured_companion_payload(raw_text)
    if payload is None:
        return None
    reply = payload.get("reply")
    if not isinstance(reply, str):
        return None
    cleaned = reply.strip()
    return cleaned or None


def _structured_companion_payload(raw_text: str) -> dict[str, Any] | None:
    """Decode the first JSON object embedded in a companion structured-output envelope."""
    text = str(raw_text or "").strip()
    json_start = text.find("{")
    if json_start < 0:
        return None
    try:
        payload, _ = json.JSONDecoder().raw_decode(text[json_start:])
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None
