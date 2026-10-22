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


def save_upload_digest(source_id: str, user_id: str, conversation_id: str, partner_name: str | None, digest: dict[str, Any]) -> None:
    owner_id = _require_user_id(user_id, "upload digest")
    values = {
        "user_id": owner_id,
        "conversation_id": conversation_id,
        "partner_name": partner_name,
        "digest_json": maybe_encrypt_json(owner_id, digest),
    }
    with ENGINE.begin() as connection:
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


def delete_upload_digest(source_id: str, user_id: str) -> None:
    owner_id = _require_user_id(user_id, "upload digest")
    with ENGINE.begin() as connection:
        connection.execute(delete(upload_digests).where(upload_digests.c.source_id == source_id, upload_digests.c.user_id == owner_id))


__all__ = ["delete_upload_digest", "list_upload_digests", "save_upload_digest"]
