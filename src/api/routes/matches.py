"""The user's match cards: who Omi offered, why, and where it stands; and the two buttons.

A card shows only what the user may know: the other person's first name, the reasons and the
difference written from both cards, the starter line, the plan and the status. Never the other
person's notes, never a score.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from agent.matching.asking import ANSWERS, record_answer
from agent.matching.hosting import pair_facts
from agent.matching.pair_chat import chat_state, other_user
from security.auth import CurrentUser, require_user
from storage import blocked_match_pairs, get_match_pair, match_chat_summaries, match_pairs_for_user, match_users_blocked_by

from ..helpers import _user_id

router = APIRouter()

# Statuses a user can see; a pair they have not heard about yet is not a card.
_VISIBLE = frozenset({"asked", "introduced", "met", "still_talking", "declined", "no_show", "expired"})


class MatchAnswer(BaseModel):
    answer: str


def match_card(
    pair: dict[str, Any],
    user_id: str,
    *,
    chats: dict[str, dict[str, Any]] | None = None,
    blocked: set[str] | None = None,
    blocks: set[frozenset[str]] | None = None,
) -> dict[str, Any] | None:
    """One card. `chats`, `blocked` (people the user blocked) and `blocks` (blocked pairs touching
    the user, either way) are passed in when many cards are built at once; looked up here otherwise."""
    plan = pair.get("plan") or {}
    told = ((plan.get("told") or {}).get(user_id) or {}).get("sent")
    if pair["status"] not in _VISIBLE or not told:
        return None
    check = pair.get("check") or {}
    answers = plan.get("answers") or {}
    mine = (answers.get(user_id) or {}).get("answer")
    status = pair["status"]
    if status == "asked":
        status = "waiting" if mine == "accept" else "asked"
    if blocked is None:
        blocked = match_users_blocked_by(user_id)
    state = chat_state(pair, user_id, blocks=blocks)
    chat = None
    if state["readable"]:
        if chats is None:
            chats = match_chat_summaries([pair["id"]], user_id)
        summary = chats.get(pair["id"]) or {}
        chat = {"open": state["open"], "messages": summary.get("messages", 0), "unread": summary.get("unread", 0), "last_at": summary.get("last_at")}
    if other_user(pair, user_id) in blocked:
        # Only the person who blocked sees this; the other person's card says declined.
        status = "blocked"
    return {
        "pair_id": pair["id"],
        "status": status,
        "name": pair_facts(pair, user_id)["name"],
        "reasons": [{"area": r.get("area"), "text": r["text"]} for r in check.get("reasons") or []],
        "difference": {"area": check["difference"].get("area"), "text": check["difference"]["text"]} if check.get("difference") else None,
        "icebreaker": check.get("icebreaker"),
        "plan": {"place": plan.get("place"), "when": plan.get("when")} if plan.get("place") or plan.get("when") else None,
        "asked_at": plan.get("asked_at"),
        "answer_by": plan.get("answer_by"),
        "introduced_at": pair.get("introduced_at"),
        "chat": chat,
    }


@router.get("/api/me/matches")
async def my_matches(user: CurrentUser = Depends(require_user)) -> dict[str, object]:
    user_id = _user_id(user)
    pairs = match_pairs_for_user(user_id)
    chats = match_chat_summaries([pair["id"] for pair in pairs], user_id)
    blocked = match_users_blocked_by(user_id)
    blocks = blocked_match_pairs([user_id])
    cards = [card for pair in pairs if (card := match_card(pair, user_id, chats=chats, blocked=blocked, blocks=blocks))]
    return {"matches": cards}


@router.post("/api/me/matches/{pair_id}/answer")
async def answer_match(pair_id: str, payload: MatchAnswer, user: CurrentUser = Depends(require_user)) -> dict[str, object]:
    if payload.answer not in ANSWERS:
        raise HTTPException(status_code=400, detail=f"answer must be one of {', '.join(ANSWERS)}")
    user_id = _user_id(user)
    result = record_answer(pair_id, user_id, payload.answer)
    if not result.get("ok"):
        if result.get("error") == "unknown_pair":
            raise HTTPException(status_code=404, detail="No such match.")
        raise HTTPException(status_code=409, detail="This match is no longer open.")
    pair = get_match_pair(pair_id)
    return {"match": match_card(pair, user_id) if pair else None, "status": result["status"]}


__all__ = ["match_card", "router"]
