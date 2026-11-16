"""The read of an uploaded chat: what it says about the two people in it.

`GET /api/me/context-sources/{source_id}/chat-read` returns the stored read, or {"state": "none"}.
`POST` makes it (one model call for the written half) and stores it with the upload's digest.
Only the person who uploaded the chat can ask; the read is deleted with the upload.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from agent.cognition.background.uploads.chat_read import READ_VERSION, build_chat_read
from agent.shared.timeline import user_zone
from security.auth import CurrentUser, require_user
from storage import get_user_profile, get_user_timezone
from storage.context_sources import get_context_source_metadata
from storage.conversations import import_conversation
from storage.upload_digests import CHAT_READ_KEY, get_upload_digest, set_upload_digest_part

from ..usage_limits import CHAT_READ_LIMIT, enforce_user_action_limit

router = APIRouter()


def _own_upload(source_id: str, user: CurrentUser) -> None:
    if get_context_source_metadata(source_id, user.id) is None:
        raise HTTPException(status_code=404, detail="Upload not found.")


def _stored(source_id: str, user_id: str) -> dict[str, object] | None:
    """The stored read, unless it was made by an older version of the read: that one is made again."""
    stored = (get_upload_digest(source_id, user_id) or {}).get(CHAT_READ_KEY)
    return stored if isinstance(stored, dict) and stored.get("version") == READ_VERSION else None


@router.get("/api/me/context-sources/{source_id}/chat-read")
def get_chat_read(source_id: str, user: CurrentUser = Depends(require_user)) -> dict[str, object]:
    _own_upload(source_id, user)
    stored = _stored(source_id, user.id)
    return stored if stored is not None else {"state": "none"}


@router.post("/api/me/context-sources/{source_id}/chat-read")
async def make_chat_read(source_id: str, again: bool = False, user: CurrentUser = Depends(require_user)) -> dict[str, object]:
    _own_upload(source_id, user)
    stored = _stored(source_id, user.id)
    if stored is not None and stored.get("state") == "ready" and not again:
        return stored
    conversation = import_conversation(user.id, source_id)
    if conversation is None:
        # A notes upload or a friend's style import: no chat of theirs to read.
        return {"state": "no_chat"}
    enforce_user_action_limit(user.id, CHAT_READ_LIMIT)
    me = str((get_user_profile(user.id) or {}).get("display_name") or "You").split()[0]
    read = await build_chat_read(
        list(conversation.get("messages") or []), me=me, zone=user_zone(get_user_timezone(user.id)), conversation_id=str(conversation["id"])
    )
    if read["state"] == "ready":
        set_upload_digest_part(source_id, user.id, str(conversation["id"]), read["them"], CHAT_READ_KEY, read)
    return read


__all__ = ["router"]
