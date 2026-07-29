from __future__ import annotations

import json
from datetime import timezone
from typing import Any

from sqlalchemy import select

from security.encryption import (
    decrypt_json,
    decrypt_text,
    is_encrypted_blob,
    maybe_encrypt_json,
    maybe_encrypt_text,
)

from .database import ENGINE
from .schema import agent_conversations

def _protect_messages(user_id: str | None, messages: list[dict[str, Any]]) -> Any:
    return maybe_encrypt_json(user_id, messages)


def _unprotect_messages(user_id: str | None, value: Any) -> list[dict[str, Any]]:
    return decrypt_json(user_id, value)


def _protect_text(user_id: str | None, value: str) -> str:
    protected = maybe_encrypt_text(user_id, value)
    if is_encrypted_blob(protected):
        return json.dumps(protected, separators=(",", ":"))
    return str(protected)


def _unprotect_text(user_id: str | None, value: Any) -> str:
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.startswith("{"):
            try:
                parsed = json.loads(stripped)
            except json.JSONDecodeError:
                parsed = None
            if is_encrypted_blob(parsed):
                return decrypt_text(user_id, parsed)
    return decrypt_text(user_id, value)


def _owned_update_values(payload: dict[str, Any], owner_key: str) -> dict[str, Any]:
    values = {key: value for key, value in payload.items() if key != "id"}
    if values.get(owner_key) is None:
        values.pop(owner_key, None)
    return values


def _require_user_id(user_id: str | None, entity: str) -> str:
    if not user_id:
        raise ValueError(f"{entity} requires a user_id")
    return user_id


def _conversation_user_id(conversation_id: str | None) -> str | None:
    if not conversation_id:
        return None
    with ENGINE.begin() as connection:
        row = connection.execute(
            select(agent_conversations.c.user_id).where(
                agent_conversations.c.id == conversation_id
            )
        ).first()
    return row[0] if row else None


def _isoformat_utc(value: Any) -> str | None:
    if not value:
        return None
    if value.tzinfo is None:
        return f"{value.isoformat()}Z"
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
