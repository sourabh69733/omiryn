"""The read of an uploaded chat: what it says about the two people in it.

The read is made when the chat is uploaded (see the WhatsApp upload route), so it is usually
waiting. `GET /api/me/context-sources/{source_id}/chat-read` returns it, or {"state": "making"}
while it is being made, or why this chat has none, or {"state": "none"} for an older upload.
`POST` makes it when there is none (one model call for the written half) or again with
`?again=true`. Only the person who uploaded the chat can ask; the read is deleted with the upload.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from agent.cognition.background.uploads.chat_read import make_stored_read, read_status
from security.auth import CurrentUser, require_user
from storage.context_sources import get_context_source_metadata

from ..usage_limits import CHAT_READ_LIMIT, enforce_user_action_limit

router = APIRouter()


def _own_upload(source_id: str, user: CurrentUser) -> None:
    if get_context_source_metadata(source_id, user.id) is None:
        raise HTTPException(status_code=404, detail="Upload not found.")


@router.get("/api/me/context-sources/{source_id}/chat-read")
def get_chat_read(source_id: str, user: CurrentUser = Depends(require_user)) -> dict[str, object]:
    _own_upload(source_id, user)
    return read_status(source_id, user.id) or {"state": "none"}


@router.post("/api/me/context-sources/{source_id}/chat-read")
async def make_chat_read(source_id: str, again: bool = False, user: CurrentUser = Depends(require_user)) -> dict[str, object]:
    _own_upload(source_id, user)
    status = read_status(source_id, user.id)
    if status is not None and (not again or status["state"] == "making"):
        return status
    # Made on request (an older upload, a new version, "read it again") counts towards the month's
    # reads; the one made at upload does not.
    enforce_user_action_limit(user.id, CHAT_READ_LIMIT)
    return await make_stored_read(user.id, source_id)


__all__ = ["router"]
