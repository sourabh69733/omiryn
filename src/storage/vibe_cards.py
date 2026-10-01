"""Stores the user's friend vibe card and the milestone it has reached."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from sqlalchemy import func, select

from agent.memory_engine.memories.vibe import merge_vibe, vibe_progress
from agent.shared.clock import utc_now

from .database import ENGINE
from .schema import agent_vibe_cards
from .utils import _protect_text, _require_user_id, _unprotect_text


def get_vibe_card(user_id: str) -> dict[str, Any]:
    """{"areas": {area_id: {"text", "evidence"}}, "milestone": id, "milestone_reached_at": datetime | None}."""
    owner_id = _require_user_id(user_id, "agent vibe card")
    with ENGINE.begin() as connection:
        row = connection.execute(
            select(agent_vibe_cards).where(agent_vibe_cards.c.user_id == owner_id)
        ).mappings().first()
    if not row:
        return {"areas": {}, "milestone": "starting", "milestone_reached_at": None}
    return {
        "areas": _areas(owner_id, row["card"]),
        "milestone": row["milestone"],
        "milestone_reached_at": row["milestone_reached_at"],
    }


def update_vibe_card(
    user_id: str,
    updates: dict[str, dict[str, Any]],
    *,
    remove: tuple[str, ...] = (),
    now: datetime | None = None,
) -> dict[str, Any]:
    """Merge area lines; the milestone moves (up or down) only when the count crosses one."""
    owner_id = _require_user_id(user_id, "agent vibe card")
    current = get_vibe_card(owner_id)
    areas = merge_vibe(
        {key: value for key, value in current["areas"].items() if key not in remove}, updates
    )
    milestone = vibe_progress(areas).milestone
    reached_at = (
        current["milestone_reached_at"]
        if milestone == current["milestone"] and current["milestone_reached_at"]
        else now or utc_now()
    )
    values = {
        "card": _protect_text(owner_id, json.dumps(areas, ensure_ascii=False)),
        "milestone": milestone,
        "milestone_reached_at": reached_at,
    }
    with ENGINE.begin() as connection:
        updated = connection.execute(
            agent_vibe_cards.update()
            .where(agent_vibe_cards.c.user_id == owner_id)
            .values(**values, updated_at=func.now())
        )
        if not updated.rowcount:
            connection.execute(agent_vibe_cards.insert().values(user_id=owner_id, **values))
    return {"areas": areas, "milestone": milestone, "milestone_reached_at": reached_at}


def _areas(owner_id: str, stored: str) -> dict[str, dict[str, Any]]:
    try:
        value = json.loads(_unprotect_text(owner_id, stored) or "{}")
    except (TypeError, ValueError):
        return {}
    return merge_vibe(value if isinstance(value, dict) else {}, {})


__all__ = ["get_vibe_card", "update_vibe_card"]
