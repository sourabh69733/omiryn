"""The chat between two introduced people, and the two ways out: block, and report.

Only the two people in the pair reach these. A message is plain text between them: Omi never reads
it, the operator never sees it. Realtime events carry ids only; the app fetches the text.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from io import BytesIO

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from PIL import Image
from pydantic import BaseModel, Field

from agent.context_engine.policy.replies import is_one_emoji

from agent.matching.pair_chat import chat_state, close_pair, other_user
from realtime import realtime_hub
from realtime.contracts import user_event
from security.auth import CurrentUser, require_user
from storage import (
    MATCH_MESSAGE_CHARS,
    MATCH_REPORT_REASONS,
    add_match_message,
    get_match_media,
    get_match_pair,
    list_match_messages,
    mark_match_chat_read,
    match_chat_summaries,
    reserve_user_app_event,
    set_match_reaction,
)

from ..helpers import _user_id
from ..photo_processing import sanitize_profile_photo
from .matches import match_card

router = APIRouter()

# Enough for a fast conversation; only stops a script.
MESSAGES_PER_MINUTE = 30
IMAGES_PER_MINUTE = 6
# What a browser may send; a still picture is re-encoded smaller, a GIF is kept as it is.
UPLOAD_MAX_BYTES = 8 * 1024 * 1024
GIF_MAX_BYTES = 4 * 1024 * 1024
GIF_MAX_FRAMES = 300
CAPTION_CHARS = 500


class ChatMessage(BaseModel):
    text: str = Field(min_length=1, max_length=MATCH_MESSAGE_CHARS)
    client_id: str | None = Field(default=None, max_length=64)


class ChatRead(BaseModel):
    upto: int | None = Field(default=None, ge=0)


class ChatTyping(BaseModel):
    active: bool = True


class ChatReaction(BaseModel):
    emoji: str | None = Field(default=None, max_length=16)


class MatchReport(BaseModel):
    reason: str
    note: str | None = Field(default=None, max_length=1000)
    block: bool = True


def _pair_for(pair_id: str, user_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """The pair and what this person may do in its chat; 404 unless they may read it."""
    pair = get_match_pair(pair_id)
    state = chat_state(pair, user_id) if pair else None
    if pair is None or state is None or not state["readable"]:
        raise HTTPException(status_code=404, detail="No such chat.")
    return pair, state


def _view(message: dict[str, Any], user_id: str) -> dict[str, Any]:
    mine = message["sender_id"] == user_id
    reactions = message.get("reactions") or {}
    return {
        "id": message["id"], "mine": mine, "text": message["text"], "created_at": message["created_at"], "client_id": message["client_id"] if mine else None,
        # The picture's id and size; the bytes come from the media call. Never who, beyond mine or theirs.
        "image": message.get("image"),
        "reactions": {"mine": reactions.get(user_id), "theirs": next((emoji for who, emoji in reactions.items() if who != user_id), None)},
    }


def _slow_down(user_id: str, event_name: str, limit: int, pair_id: str, what: str) -> None:
    allowed = reserve_user_app_event(
        user_id, event_name, {"action": event_name.split(".", 1)[-1], "pair_id": pair_id},
        burst_since=datetime.now(timezone.utc) - timedelta(seconds=60), burst_limit=limit,
    )
    if not allowed["allowed"]:
        raise HTTPException(status_code=429, detail=f"Too many {what} in a short time. Please wait a minute.", headers={"Retry-After": "60"})


def _clean_picture(content: bytes) -> dict[str, Any]:
    """A picture safe to keep and show: a still one re-encoded as a JPEG without its metadata, a GIF
    kept moving after its size and frames are checked. 415 for anything else."""
    try:
        with Image.open(BytesIO(content)) as candidate:
            image_format, frames = candidate.format, getattr(candidate, "n_frames", 1)
            width, height = candidate.size
    except Exception:
        raise HTTPException(status_code=415, detail="Send a JPG, PNG, WebP or GIF picture.") from None
    if image_format == "GIF" and frames > 1:
        if len(content) > GIF_MAX_BYTES or frames > GIF_MAX_FRAMES or width * height > 4_000_000:
            raise HTTPException(status_code=413, detail="That GIF is too big. Try one under 4 MB.")
        return {"data": content, "content_type": "image/gif", "width": width, "height": height}
    data = sanitize_profile_photo(content)
    with Image.open(BytesIO(data)) as cleaned:
        width, height = cleaned.size
    return {"data": data, "content_type": "image/jpeg", "width": width, "height": height}


def _chat(pair: dict[str, Any], user_id: str, state: dict[str, Any]) -> dict[str, Any]:
    summary = match_chat_summaries([pair["id"]], user_id).get(pair["id"]) or {}
    return {"open": state["open"], "messages": summary.get("messages", 0), "unread": summary.get("unread", 0), "last_at": summary.get("last_at"), "last_text": summary.get("last_text"), "last_mine": summary.get("last_mine")}


async def _notify(event_type: str, pair: dict[str, Any], payload: dict[str, Any], *, only: str | None = None) -> None:
    for user_id in (only,) if only else (pair["user_a"], pair["user_b"]):
        await realtime_hub.publish(user_event(event_type, user_id, payload={"pair_id": pair["id"], **payload}))


@router.get("/api/me/matches/{pair_id}/messages")
async def match_messages(
    pair_id: str,
    before: int | None = Query(default=None, ge=1),
    after: int | None = Query(default=None, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    user: CurrentUser = Depends(require_user),
) -> dict[str, object]:
    user_id = _user_id(user)
    pair, state = _pair_for(pair_id, user_id)
    # One more than asked tells whether older (or newer) messages remain.
    rows = list_match_messages(pair_id, before=before, after=after, limit=limit + 1)
    has_more = len(rows) > limit
    if has_more:
        rows = rows[:limit] if after is not None else rows[1:]
    return {"messages": [_view(row, user_id) for row in rows], "has_more": has_more, "chat": _chat(pair, user_id, state)}


@router.post("/api/me/matches/{pair_id}/messages", status_code=201)
async def send_match_message(pair_id: str, payload: ChatMessage, user: CurrentUser = Depends(require_user)) -> dict[str, object]:
    user_id = _user_id(user)
    pair, state = _pair_for(pair_id, user_id)
    if not state["open"]:
        raise HTTPException(status_code=409, detail="This chat is closed.")
    if not payload.text.strip():
        raise HTTPException(status_code=400, detail="Write something first.")
    _slow_down(user_id, "quota.match_message", MESSAGES_PER_MINUTE, pair_id, "messages")
    message = add_match_message(pair_id, user_id, payload.text, client_id=payload.client_id)
    if message is None:
        raise HTTPException(status_code=404, detail="No such chat.")
    # Writing is reading: the sender has seen everything up to their own message.
    mark_match_chat_read(pair_id, user_id, message["id"])
    await _notify("match.message", pair, {"message_id": message["id"]})
    return {"message": _view(message, user_id)}


@router.post("/api/me/matches/{pair_id}/images", status_code=201)
async def send_match_image(
    pair_id: str,
    request: Request,
    caption: str = Query(default="", max_length=CAPTION_CHARS),
    client_id: str | None = Query(default=None, max_length=64),
    user: CurrentUser = Depends(require_user),
) -> dict[str, object]:
    """A picture or a GIF as the request body (its bytes, not a form); the words with it go in `caption`."""
    user_id = _user_id(user)
    pair, state = _pair_for(pair_id, user_id)
    if not state["open"]:
        raise HTTPException(status_code=409, detail="This chat is closed.")
    if int(request.headers.get("content-length") or 0) > UPLOAD_MAX_BYTES:
        raise HTTPException(status_code=413, detail="That picture is too big. Try one under 8 MB.")
    content = await request.body()
    if not content:
        raise HTTPException(status_code=400, detail="No picture was sent.")
    if len(content) > UPLOAD_MAX_BYTES:
        raise HTTPException(status_code=413, detail="That picture is too big. Try one under 8 MB.")
    _slow_down(user_id, "quota.match_image", IMAGES_PER_MINUTE, pair_id, "pictures")
    message = add_match_message(pair_id, user_id, caption, client_id=client_id, media=_clean_picture(content))
    if message is None:
        raise HTTPException(status_code=404, detail="No such chat.")
    mark_match_chat_read(pair_id, user_id, message["id"])
    await _notify("match.message", pair, {"message_id": message["id"]})
    return {"message": _view(message, user_id)}


@router.get("/api/me/matches/{pair_id}/media/{media_id}")
async def match_media(pair_id: str, media_id: str, user: CurrentUser = Depends(require_user)) -> Response:
    """The bytes of one picture, for the two people in the pair only."""
    _pair_for(pair_id, _user_id(user))
    media = get_match_media(pair_id, media_id)
    if media is None:
        raise HTTPException(status_code=404, detail="No such picture.")
    return Response(content=media["data"], media_type=media["content_type"], headers={"Cache-Control": "private, max-age=86400", "X-Content-Type-Options": "nosniff"})


@router.post("/api/me/matches/{pair_id}/typing")
async def match_typing(pair_id: str, payload: ChatTyping | None = None, user: CurrentUser = Depends(require_user)) -> dict[str, object]:
    """"I am writing": told to the other person only, kept nowhere. The app sends it every few seconds while typing."""
    user_id = _user_id(user)
    pair, state = _pair_for(pair_id, user_id)
    if state["open"]:
        await _notify("match.typing", pair, {"active": payload.active if payload else True}, only=other_user(pair, user_id))
    return {"ok": True}


@router.post("/api/me/matches/{pair_id}/messages/{message_id}/reaction")
async def react_to_match_message(pair_id: str, message_id: int, payload: ChatReaction, user: CurrentUser = Depends(require_user)) -> dict[str, object]:
    """`{"emoji": "😂"}` puts or changes this person's one emoji on a message; `null` takes it off."""
    user_id = _user_id(user)
    pair, state = _pair_for(pair_id, user_id)
    if not state["open"]:
        raise HTTPException(status_code=409, detail="This chat is closed.")
    emoji = (payload.emoji or "").strip() or None
    if emoji and not is_one_emoji(emoji):
        raise HTTPException(status_code=400, detail="A reaction is one emoji.")
    if not set_match_reaction(pair_id, message_id, user_id, emoji):
        raise HTTPException(status_code=404, detail="No such message.")
    await _notify("match.reaction", pair, {"message_id": message_id})
    rows = list_match_messages(pair_id, before=message_id + 1, limit=1)
    return {"message": _view(rows[0], user_id) if rows else None}


@router.post("/api/me/matches/{pair_id}/read")
async def read_match_chat(pair_id: str, payload: ChatRead | None = None, user: CurrentUser = Depends(require_user)) -> dict[str, object]:
    user_id = _user_id(user)
    pair, state = _pair_for(pair_id, user_id)
    mark = mark_match_chat_read(pair_id, user_id, payload.upto if payload else None)
    # Their other devices clear the badge; the other person is not told what was read.
    await _notify("match.read", pair, {"last_read_id": mark}, only=user_id)
    return {"last_read_id": mark, "chat": _chat(pair, user_id, state)}


async def _close(pair_id: str, user_id: str, *, block: bool, reason: str | None = None, note: str | None = None) -> dict[str, object]:
    result = close_pair(pair_id, user_id, block=block, reason=reason, note=note)
    if not result.get("ok"):
        if result.get("error") == "unknown_pair":
            raise HTTPException(status_code=404, detail="No such match.")
        raise HTTPException(status_code=409, detail="This match is not open.")
    pair = get_match_pair(pair_id)
    if pair is not None:
        await _notify("match.updated", pair, {})
    return {"match": match_card(pair, user_id) if pair else None, "status": result["status"]}


@router.post("/api/me/matches/{pair_id}/block")
async def block_match(pair_id: str, user: CurrentUser = Depends(require_user)) -> dict[str, object]:
    return await _close(pair_id, _user_id(user), block=True)


@router.post("/api/me/matches/{pair_id}/report")
async def report_match(pair_id: str, payload: MatchReport, user: CurrentUser = Depends(require_user)) -> dict[str, object]:
    if payload.reason not in MATCH_REPORT_REASONS:
        raise HTTPException(status_code=400, detail=f"reason must be one of {', '.join(MATCH_REPORT_REASONS)}")
    return await _close(pair_id, _user_id(user), block=payload.block, reason=payload.reason, note=payload.note)


__all__ = ["router"]
