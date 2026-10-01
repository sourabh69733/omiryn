from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from agent.memory_engine.memories.vibe import (
    VIBE_AREAS,
    line_evidence,
    line_strength,
    line_text,
    vibe_progress,
)
from security.auth import CurrentUser, require_user
from storage import get_conversation, get_vibe_card, update_vibe_card

# Quotes shown under "Why?" for one line.
MAX_QUOTES = 3
QUOTE_CHARS = 200

router = APIRouter()


@router.get("/api/me/vibe")
async def get_vibe(user: CurrentUser = Depends(require_user)) -> dict[str, object]:
    """What the companion understands about who the user would get along with."""
    if not user:
        raise HTTPException(status_code=401, detail="Sign in to continue.")
    return _vibe_payload(get_vibe_card(user.id), user.id)


@router.delete("/api/me/vibe/{area_id}")
async def delete_vibe_area(area_id: str, user: CurrentUser = Depends(require_user)) -> dict[str, object]:
    """The user says a line is wrong; it goes, and the companion learns that area again."""
    if not user:
        raise HTTPException(status_code=401, detail="Sign in to continue.")
    if area_id not in {item_id for item_id, _, _ in VIBE_AREAS}:
        raise HTTPException(status_code=404, detail="Unknown vibe area.")
    return _vibe_payload(update_vibe_card(user.id, {}, remove=(area_id,)), user.id)


def _vibe_payload(card: dict[str, object], user_id: str) -> dict[str, object]:
    areas = card["areas"]
    conversations: dict[str, list[dict[str, object]]] = {}
    progress = vibe_progress(areas)
    reached_at = card.get("milestone_reached_at")
    return {
        "milestone": progress.milestone,
        "next_milestone": progress.next_milestone,
        "milestone_reached_at": reached_at.isoformat() if reached_at else None,
        "known": len(progress.known),
        "total": len(VIBE_AREAS),
        "areas": [
            {
                "id": area_id,
                "stage": stage,
                "text": line_text(areas.get(area_id)) or None,
                "strength": line_strength(areas[area_id]) if area_id in areas else None,
                "evidence_count": len(line_evidence(areas.get(area_id))),
                "quotes": _quotes(line_evidence(areas.get(area_id)), user_id, conversations),
            }
            for area_id, stage, _ in VIBE_AREAS
        ],
    }


def _quotes(
    evidence: list[dict[str, object]],
    user_id: str,
    conversations: dict[str, list[dict[str, object]]],
) -> list[str]:
    """The user's own messages behind a line, newest first; deleted chats are skipped."""
    quotes: list[str] = []
    for item in reversed(evidence):
        conversation_id = str(item["conversation_id"])
        if conversation_id not in conversations:
            conversation = get_conversation(conversation_id, user_id)
            conversations[conversation_id] = list((conversation or {}).get("messages") or [])
        messages = conversations[conversation_id]
        index = int(item["message_index"])
        if 0 <= index < len(messages) and messages[index].get("role") == "user":
            text = " ".join(str(messages[index].get("content") or "").split())
            quotes.append(text if len(text) <= QUOTE_CHARS else text[: QUOTE_CHARS - 1] + "…")
        if len(quotes) >= MAX_QUOTES:
            break
    return quotes
