from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from agent.memory_engine.memories.vibe import VIBE_AREAS, vibe_progress
from security.auth import CurrentUser, require_user
from storage import get_vibe_card, update_vibe_card

router = APIRouter()


@router.get("/api/me/vibe")
async def get_vibe(user: CurrentUser = Depends(require_user)) -> dict[str, object]:
    """What the companion understands about who the user would get along with."""
    if not user:
        raise HTTPException(status_code=401, detail="Sign in to continue.")
    return _vibe_payload(get_vibe_card(user.id))


@router.delete("/api/me/vibe/{area_id}")
async def delete_vibe_area(area_id: str, user: CurrentUser = Depends(require_user)) -> dict[str, object]:
    """The user says a line is wrong; it goes, and the companion learns that area again."""
    if not user:
        raise HTTPException(status_code=401, detail="Sign in to continue.")
    if area_id not in {item_id for item_id, _, _ in VIBE_AREAS}:
        raise HTTPException(status_code=404, detail="Unknown vibe area.")
    return _vibe_payload(update_vibe_card(user.id, {}, remove=(area_id,)))


def _vibe_payload(card: dict[str, object]) -> dict[str, object]:
    areas = card["areas"]
    progress = vibe_progress(areas)
    reached_at = card.get("milestone_reached_at")
    return {
        "milestone": progress.milestone,
        "next_milestone": progress.next_milestone,
        "milestone_reached_at": reached_at.isoformat() if reached_at else None,
        "known": len(progress.known),
        "total": len(VIBE_AREAS),
        "areas": [
            {"id": area_id, "stage": stage, "text": areas.get(area_id)}
            for area_id, stage, _ in VIBE_AREAS
        ],
    }
