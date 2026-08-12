"""Decodes model transport envelopes before a companion reply reaches the user."""

from __future__ import annotations

import json
import re
from typing import Any


def structured_companion_reply(raw_text: str) -> str | None:
    """Return a reply from a JSON or textual-function envelope, when one is present."""
    payload = structured_companion_payload(raw_text)
    if payload is None:
        return None
    reply = payload.get("reply")
    if not isinstance(reply, str):
        return None
    cleaned = reply.strip()
    return cleaned or None


def structured_companion_payload(raw_text: str) -> dict[str, Any] | None:
    """Decode a reply-shaped JSON object embedded in a companion output envelope."""
    text = str(raw_text or "").strip()
    decoder = json.JSONDecoder()
    for json_start, character in enumerate(text):
        if character != "{":
            continue
        try:
            payload, _ = decoder.raw_decode(text[json_start:])
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict) and isinstance(payload.get("reply"), str):
            return payload
    return None


def textual_tool_arguments(raw_text: str, *, expected_name: str | None = None) -> str | None:
    """Decode a provider's textual function-call envelope into JSON arguments."""
    text = str(raw_text or "").strip()
    payload = structured_companion_payload(text)
    function_name = _textual_function_name(text)
    if payload is None or function_name is None or "</function" not in text.casefold():
        return None
    if expected_name and function_name != expected_name.casefold():
        return None
    return json.dumps(payload, ensure_ascii=False)


def _textual_function_name(text: str) -> str | None:
    match = re.search(
        r"<function(?:\s*\(\s*|\s*=\s*|\s*\{\s*|\s+name\s*=\s*['\"]?)([a-z0-9_.-]+)",
        text,
        flags=re.IGNORECASE,
    )
    return match.group(1).casefold() if match else None
