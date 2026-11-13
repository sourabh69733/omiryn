"""The chat between two introduced people, and the two ways out: block, and report.

Only the two people in the pair reach these. A message is plain text between them: Omi never reads
it, the operator never sees it. Realtime events carry ids only; the app fetches the text.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from agent.matching.pair_chat import chat_state, close_pair, other_user
from realtime import realtime_hub
from realtime.contracts import user_event
from security.auth import CurrentUser, require_user
from storage import (
    MATCH_MESSAGE_CHARS,
    MATCH_REPORT_REASONS,
    add_match_message,
    get_match_pair,
    list_match_messages,
    mark_match_chat_read,
    match_chat_summaries,
    reserve_user_app_event,
)

from ..helpers import _user_id
from .matches import match_card

router = APIRouter()

# Enough for a fast conversation; only stops a script.
MESSAGES_PER_MINUTE = 30


class ChatMessage(BaseModel):
    text: str = Field(min_length=1, max_length=MATCH_MESSAGE_CHARS)
    client_id: str | None = Field(default=None, max_length=64)


class ChatRead(BaseModel):
    upto: int | None = Field(default=None, ge=0)


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
    return {"id": message["id"], "mine": mine, "text": message["text"], "created_at": message["created_at"], "client_id": message["client_id"] if mine else None}


def _chat(pair: dict[str, Any], user_id: str, state: dict[str, Any]) -> dict[str, Any]:
    summary = match_chat_summaries([pair["id"]], user_id).get(pair["id"]) or {}
    return {"open": state["open"], "messages": summary.get("messages", 0), "unread": summary.get("unread", 0), "last_at": summary.get("last_at")}


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
    allowed = reserve_user_app_event(
        user_id,
        "quota.match_message",
        {"action": "match_message", "pair_id": pair_id},
        burst_since=datetime.now(timezone.utc) - timedelta(seconds=60),
        burst_limit=MESSAGES_PER_MINUTE,
    )
    if not allowed["allowed"]:
        raise HTTPException(status_code=429, detail="Too many messages in a short time. Please wait a minute.", headers={"Retry-After": "60"})
    message = add_match_message(pair_id, user_id, payload.text, client_id=payload.client_id)
    if message is None:
        raise HTTPException(status_code=404, detail="No such chat.")
    # Writing is reading: the sender has seen everything up to their own message.
    mark_match_chat_read(pair_id, user_id, message["id"])
    await _notify("match.message", pair, {"message_id": message["id"]})
    return {"message": _view(message, user_id)}


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
