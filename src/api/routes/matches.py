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
from security.auth import CurrentUser, require_user
from storage import get_match_pair, match_pairs_for_user

from ..helpers import _user_id

router = APIRouter()

# Statuses a user can see; a pair they have not heard about yet is not a card.
_VISIBLE = frozenset({"asked", "introduced", "met", "still_talking", "declined", "no_show", "expired"})


class MatchAnswer(BaseModel):
    answer: str


def match_card(pair: dict[str, Any], user_id: str) -> dict[str, Any] | None:
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
    }


@router.get("/api/me/matches")
async def my_matches(user: CurrentUser = Depends(require_user)) -> dict[str, object]:
    user_id = _user_id(user)
    cards = [card for pair in match_pairs_for_user(user_id) if (card := match_card(pair, user_id))]
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
