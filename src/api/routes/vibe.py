from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from agent.memory_engine.memories.vibe import (
    PRIVATE_AREA_IDS,
    VIBE_AREAS,
    evidence_days,
    line_evidence,
    line_strength,
    line_text,
    vibe_progress,
)
from agent.providers import write_vibe_intro
from security.auth import CurrentUser, require_user
from storage import (
    get_conversation,
    get_vibe_card,
    list_conversation_ids,
    prune_vibe_proof_from_missing_chats,
    set_vibe_intro,
    update_vibe_card,
)

# Messages shown as proof for one line, newest first.
MAX_QUOTES = 5
QUOTE_CHARS = 200

# The intro needs this many non-private lines before Omi writes one.
INTRO_MIN_LINES = 2
INTRO_MAX_CHARS = 200
INTRO_MAX_CHIPS = 5
CHIP_MAX_CHARS = 30
# Bumped when the intro's voice or rules change, so saved intros are written again.
INTRO_STYLE = "2"

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/api/me/vibe")
async def get_vibe(user: CurrentUser = Depends(require_user)) -> dict[str, object]:
    """What the companion understands about who the user would get along with."""
    if not user:
        raise HTTPException(status_code=401, detail="Sign in to continue.")
    # Proof from chats deleted before deletes cleaned the vibe goes now (no model call).
    prune_vibe_proof_from_missing_chats(user.id, list_conversation_ids(user.id))
    return _vibe_payload(get_vibe_card(user.id), user.id)


@router.delete("/api/me/vibe/{area_id}")
async def delete_vibe_area(area_id: str, user: CurrentUser = Depends(require_user)) -> dict[str, object]:
    """The user says a line is wrong; it goes, and only proof sent after this can fill that area again."""
    if not user:
        raise HTTPException(status_code=401, detail="Sign in to continue.")
    if area_id not in {item_id for item_id, _, _ in VIBE_AREAS}:
        raise HTTPException(status_code=404, detail="Unknown vibe area.")
    return _vibe_payload(update_vibe_card(user.id, {}, reject=(area_id,)), user.id)


class IntroEdit(BaseModel):
    intro: str = Field(min_length=1, max_length=INTRO_MAX_CHARS)
    chips: list[str] = Field(default_factory=list, max_length=INTRO_MAX_CHIPS)


@router.get("/api/me/intro")
async def get_intro(user: CurrentUser = Depends(require_user)) -> dict[str, object]:
    """The "who you are" line on the user's profile, written from their non-private vibe lines.

    An intro the user wrote themselves is never replaced. Omi's own intro is rewritten only when
    the lines change; if writing fails, the last one is kept.
    """
    if not user:
        raise HTTPException(status_code=401, detail="Sign in to continue.")
    card = get_vibe_card(user.id)
    saved = card.get("intro") or {}
    if saved.get("edited") and saved.get("text"):
        return _intro_payload(saved)
    public = _public_lines(card)
    if len(public) < INTRO_MIN_LINES:
        return {"intro": None, "chips": [], "ready": False, "edited": False}
    source = json.dumps({"style": INTRO_STYLE, "lines": public}, ensure_ascii=False, sort_keys=True)
    if saved.get("source") == source and saved.get("text"):
        return _intro_payload(saved)
    conversation_ids = sorted(list_conversation_ids(user.id))
    user_wording = saved.get("user_wording")
    try:
        if not conversation_ids:
            raise ValueError("no chat to record usage against")
        raw = await write_vibe_intro(
            json.dumps(
                {
                    "first_name": (user.display_name or "").split(" ")[0],
                    "vibe_lines": public,
                    **({"user_wording": user_wording} if user_wording else {}),
                },
                ensure_ascii=False,
            ),
            conversation_id=conversation_ids[0],
            timeout_seconds=25,
        )
        intro = _clean(raw.get("intro"), INTRO_MAX_CHARS)
        chips = _clean_chips(raw.get("chips") if isinstance(raw.get("chips"), list) else [])
        if not intro:
            raise ValueError("empty intro")
    except Exception as error:  # the page still works; it just keeps the last intro
        logger.warning("agent.vibe.intro_failed user_id=%s error=%s", user.id, type(error).__name__)
        if saved.get("text"):
            return _intro_payload(saved)
        return {"intro": None, "chips": [], "ready": False, "edited": False}
    written = {"text": intro, "chips": chips, "source": source, **({"user_wording": user_wording} if user_wording else {})}
    set_vibe_intro(user.id, written)
    return _intro_payload(written)


@router.put("/api/me/intro")
async def edit_intro(payload: IntroEdit, user: CurrentUser = Depends(require_user)) -> dict[str, object]:
    """The user's own words for their intro and tags. Kept as written, and shared with the companion."""
    if not user:
        raise HTTPException(status_code=401, detail="Sign in to continue.")
    intro = _clean(payload.intro, INTRO_MAX_CHARS)
    if not intro:
        raise HTTPException(status_code=422, detail="Write a line about yourself.")
    edited = {"text": intro, "chips": _clean_chips(payload.chips), "edited": True}
    set_vibe_intro(user.id, edited)
    return _intro_payload(edited)


@router.delete("/api/me/intro")
async def reset_intro(user: CurrentUser = Depends(require_user)) -> dict[str, object]:
    """Let Omi write the intro again; the user's last wording guides it."""
    if not user:
        raise HTTPException(status_code=401, detail="Sign in to continue.")
    saved = get_vibe_card(user.id).get("intro") or {}
    wording = (
        {"intro": saved.get("text"), "chips": saved.get("chips") or []}
        if saved.get("edited")
        else saved.get("user_wording")
    )
    set_vibe_intro(user.id, {"user_wording": wording} if wording else {"reset": True})
    return await get_intro(user)


def _public_lines(card: dict[str, object]) -> dict[str, str]:
    areas = card["areas"]
    return {
        area_id: line_text(areas.get(area_id))
        for area_id, _, _ in VIBE_AREAS
        if area_id not in PRIVATE_AREA_IDS and line_text(areas.get(area_id))
    }


def _intro_payload(saved: dict[str, object]) -> dict[str, object]:
    return {"intro": saved["text"], "chips": saved.get("chips") or [], "ready": True, "edited": bool(saved.get("edited"))}


def _clean(value: object, limit: int) -> str:
    return " ".join(str(value or "").split())[:limit]


def _clean_chips(values: list[object]) -> list[str]:
    chips: list[str] = []
    for value in values:
        chip = _clean(value, CHIP_MAX_CHARS)
        if chip and chip.lower() not in {existing.lower() for existing in chips}:
            chips.append(chip)
    return chips[:INTRO_MAX_CHIPS]


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
                "private": area_id in PRIVATE_AREA_IDS,
                "text": line_text(areas.get(area_id)) or None,
                "strength": line_strength(areas[area_id]) if area_id in areas else None,
                "evidence_count": len(line_evidence(areas.get(area_id))),
                "evidence_days": evidence_days(areas.get(area_id)),
                "evidence": _evidence(line_evidence(areas.get(area_id)), user_id, conversations),
            }
            for area_id, stage, _ in VIBE_AREAS
        ],
    }


def _evidence(
    evidence: list[dict[str, object]],
    user_id: str,
    conversations: dict[str, list[dict[str, object]]],
) -> list[dict[str, object]]:
    """The user's own messages behind a line, newest first, with where to find them in chat.

    Messages from deleted chats are skipped.
    """
    items: list[dict[str, object]] = []
    for item in reversed(evidence):
        conversation_id = str(item["conversation_id"])
        if conversation_id not in conversations:
            conversation = get_conversation(conversation_id, user_id)
            conversations[conversation_id] = list((conversation or {}).get("messages") or [])
        messages = conversations[conversation_id]
        index = int(item["message_index"])
        if not (0 <= index < len(messages)) or messages[index].get("role") != "user":
            continue
        text = " ".join(str(messages[index].get("content") or "").split())
        items.append(
            {
                "quote": text if len(text) <= QUOTE_CHARS else text[: QUOTE_CHARS - 1] + "…",
                "conversation_id": conversation_id,
                "message_index": index,
                "sent_at": messages[index].get("created_at"),
            }
        )
        if len(items) >= MAX_QUOTES:
            break
    return items
