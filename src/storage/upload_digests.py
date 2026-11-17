"""What Omi made of each uploaded chat: summary, topics (threads), the other person, plans.

One row per upload, the digest encrypted as one JSON blob. A user has only a few uploads, so
replies read them all and match in memory.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import delete, select

from security.encryption import decrypt_json, maybe_encrypt_json

from .database import ENGINE
from .schema import upload_digests
from .utils import _require_user_id

# Where the read of a chat (agent.cognition.background.uploads.chat_read) sits inside a digest.
CHAT_READ_KEY = "chat_read"


def save_upload_digest(source_id: str, user_id: str, conversation_id: str, partner_name: str | None, digest: dict[str, Any]) -> None:
    owner_id = _require_user_id(user_id, "upload digest")
    with ENGINE.begin() as connection:
        # A chat read made before the digest was ready stays: it is stored in the same row.
        earlier = connection.execute(select(upload_digests.c.digest_json).where(upload_digests.c.source_id == source_id, upload_digests.c.user_id == owner_id)).scalar_one_or_none()
        kept = (decrypt_json(owner_id, earlier) or {}).get(CHAT_READ_KEY) if earlier is not None else None
        if kept is not None and CHAT_READ_KEY not in digest:
            digest = {**digest, CHAT_READ_KEY: kept}
        values = {
            "user_id": owner_id,
            "conversation_id": conversation_id,
            "partner_name": partner_name,
            "digest_json": maybe_encrypt_json(owner_id, digest),
        }
        connection.execute(delete(upload_digests).where(upload_digests.c.source_id == source_id, upload_digests.c.user_id == owner_id))
        connection.execute(upload_digests.insert().values(source_id=source_id, **values))


def list_upload_digests(user_id: str) -> list[dict[str, Any]]:
    """Every digest of this user: {source_id, conversation_id, partner_name, digest}."""
    owner_id = _require_user_id(user_id, "upload digest")
    with ENGINE.begin() as connection:
        rows = connection.execute(
            select(upload_digests).where(upload_digests.c.user_id == owner_id).order_by(upload_digests.c.updated_at.desc())
        ).mappings().all()
    return [
        {
            "source_id": row["source_id"],
            "conversation_id": row["conversation_id"],
            "partner_name": row["partner_name"],
            "digest": decrypt_json(owner_id, row["digest_json"]) or {},
        }
        for row in rows
    ]


def get_upload_digest(source_id: str, user_id: str) -> dict[str, Any] | None:
    """One upload's digest, or None when Omi has not stored anything for it yet."""
    owner_id = _require_user_id(user_id, "upload digest")
    with ENGINE.begin() as connection:
        row = connection.execute(select(upload_digests).where(upload_digests.c.source_id == source_id, upload_digests.c.user_id == owner_id)).mappings().first()
    return (decrypt_json(owner_id, row["digest_json"]) or {}) if row else None


def set_upload_digest_part(source_id: str, user_id: str, conversation_id: str, partner_name: str | None, key: str, value: Any) -> None:
    """Store one part of a digest (the chat read) without touching the rest; makes the row when
    the upload has no digest yet."""
    owner_id = _require_user_id(user_id, "upload digest")
    with ENGINE.begin() as connection:
        row = connection.execute(select(upload_digests).where(upload_digests.c.source_id == source_id, upload_digests.c.user_id == owner_id)).mappings().first()
        if row:
            digest = {**(decrypt_json(owner_id, row["digest_json"]) or {}), key: value}
            connection.execute(upload_digests.update().where(upload_digests.c.source_id == source_id, upload_digests.c.user_id == owner_id).values(digest_json=maybe_encrypt_json(owner_id, digest)))  # the row's partner name stays as the reader wrote it
        else:
            connection.execute(upload_digests.insert().values(source_id=source_id, user_id=owner_id, conversation_id=conversation_id, partner_name=partner_name, digest_json=maybe_encrypt_json(owner_id, {key: value})))


def delete_upload_digest(source_id: str, user_id: str) -> None:
    owner_id = _require_user_id(user_id, "upload digest")
    with ENGINE.begin() as connection:
        connection.execute(delete(upload_digests).where(upload_digests.c.source_id == source_id, upload_digests.c.user_id == owner_id))


__all__ = ["CHAT_READ_KEY", "delete_upload_digest", "get_upload_digest", "list_upload_digests", "save_upload_digest", "set_upload_digest_part"]
