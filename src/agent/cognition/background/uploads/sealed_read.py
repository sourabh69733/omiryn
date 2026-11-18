"""A read made before sign-in, sealed so it can come back with the same chat after sign-in.

Nothing from a chat tried without an account is stored here. The read goes back to the browser
with a seal: the read itself plus a signature only this server can make. When the person signs in
and shares that chat, the browser sends the seal along. A seal that is ours, still fresh, and
counted from the same chat is kept as the upload's read, so they keep exactly what they saw and no
second model call is paid for. Anything else is ignored and the read is made the usual way.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from typing import Any

from .chat_read import READ_VERSION

# Long enough to sign in and finish setup in the same sitting; the browser forgets sooner.
SEAL_FOR_SECONDS = 24 * 60 * 60
# The seal carries the whole read; a real one is a few thousand characters.
MAX_SEAL_CHARS = 40_000
# What must be the same for two counts to be of one chat.
_SAME_CHAT = ("messages", "from", "to", "days_talked")
_SAME_SIDE = ("messages", "words")


def seal_read(read: dict[str, Any], *, now: float | None = None) -> str:
    """The read and when the seal ends, signed. Only a ready read is sealed."""
    body = _encode(json.dumps({"read": read, "exp": int(now if now is not None else time.time()) + SEAL_FOR_SECONDS}, ensure_ascii=False, separators=(",", ":")).encode())
    return f"{body}.{_sign(body)}"


def open_sealed_read(seal: str | None, *, now: float | None = None) -> dict[str, Any] | None:
    """The read inside a seal, or None when the seal is not ours, has ended, or is of an older
    kind of read."""
    if not seal or len(seal) > MAX_SEAL_CHARS or seal.count(".") != 1:
        return None
    body, signature = seal.split(".")
    if not hmac.compare_digest(_sign(body), signature):
        return None
    try:
        inside = json.loads(_decode(body))
    except (ValueError, UnicodeDecodeError):
        return None
    read = inside.get("read") if isinstance(inside, dict) else None
    if not isinstance(read, dict) or not isinstance(inside.get("exp"), int):
        return None
    if inside["exp"] < (now if now is not None else time.time()):
        return None
    if read.get("state") != "ready" or read.get("version") != READ_VERSION or not isinstance(read.get("counts"), dict):
        return None
    return read


def same_chat(read: dict[str, Any], counts: dict[str, Any]) -> bool:
    """Whether a sealed read was counted from the chat these counts come from: the same size, the
    same days, the same split between the two people."""
    theirs = read.get("counts") or {}
    if any(theirs.get(key) != counts.get(key) for key in _SAME_CHAT):
        return False
    return all((theirs.get(side) or {}).get(key) == (counts.get(side) or {}).get(key) for side in ("me", "them") for key in _SAME_SIDE)


def keyed_mark(value: str, purpose: str) -> str:
    """A short mark of a value that cannot be turned back into it (for counting tries by address
    without keeping the address)."""
    return hmac.new(_secret(), f"{purpose}:{value}".encode(), hashlib.sha256).hexdigest()[:24]


def _sign(body: str) -> str:
    return _encode(hmac.new(_secret(), body.encode(), hashlib.sha256).digest())


def _secret() -> bytes:
    explicit = os.getenv("CHAT_READ_SEAL_SECRET", "").strip()
    if explicit:
        return explicit.encode()
    master = os.getenv("ENCRYPTION_MASTER_KEY", "").strip()
    if master:
        try:
            decoded = base64.urlsafe_b64decode(master + "=" * (-len(master) % 4))
        except ValueError:
            decoded = b""
        if decoded:
            # A key of its own, so a seal is never useful as an encryption key or a realtime ticket.
            return hmac.new(decoded, b"omiryn-chat-read-seal-v1", hashlib.sha256).digest()
    return b"omiryn-local-development-chat-read-seal-v1"


def _encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode().rstrip("=")


def _decode(value: str) -> str:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4)).decode()


__all__ = ["MAX_SEAL_CHARS", "SEAL_FOR_SECONDS", "keyed_mark", "open_sealed_read", "same_chat", "seal_read"]
