"""Stores the user's friend vibe card and the milestone it has reached."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from sqlalchemy import func, select

from agent.memory_engine.memories.vibe import line_evidence, line_text, merge_vibe, proof_after_rejection, vibe_progress
from agent.shared.clock import utc_now

from .database import ENGINE
from .schema import agent_vibe_cards
from .utils import _protect_text, _require_user_id, _unprotect_text

# Stored next to the area lines: lines the user marked wrong, with when and the proof behind them.
REJECTED_KEY = "_rejected"


def get_vibe_card(user_id: str) -> dict[str, Any]:
    """{"areas": {area_id: {"text", "evidence"}}, "rejected": {area_id: {"text", "evidence", "at"}},
    "milestone": id, "milestone_reached_at": datetime | None}."""
    owner_id = _require_user_id(user_id, "agent vibe card")
    with ENGINE.begin() as connection:
        row = connection.execute(
            select(agent_vibe_cards).where(agent_vibe_cards.c.user_id == owner_id)
        ).mappings().first()
    if not row:
        return {"areas": {}, "rejected": {}, "milestone": "starting", "milestone_reached_at": None}
    stored = _stored(owner_id, row["card"])
    return {
        "areas": merge_vibe(stored, {}),
        "rejected": _rejected(stored),
        "milestone": row["milestone"],
        "milestone_reached_at": row["milestone_reached_at"],
    }


def update_vibe_card(
    user_id: str,
    updates: dict[str, dict[str, Any]],
    *,
    reject: tuple[str, ...] = (),
    drop: tuple[str, ...] = (),
    replace_evidence: bool = False,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Merge area lines; the milestone moves (up or down) only when the count crosses one.

    reject: areas the user marked wrong. The line goes, and that area takes a new line only with
    proof sent afterwards; a saved new line clears the mark. "applied" lists the areas written.
    drop: areas removed without marking them wrong (their proof is gone).
    replace_evidence: the updates' proof replaces the old proof (see merge_vibe).
    """
    owner_id = _require_user_id(user_id, "agent vibe card")
    current = get_vibe_card(owner_id)
    rejected = dict(current["rejected"])
    rejected_at = utc_now().isoformat()
    for area_id in reject:
        line = current["areas"].get(area_id)
        rejected[area_id] = {"text": line_text(line), "evidence": line_evidence(line), "at": rejected_at}
    updates = proof_after_rejection(updates, rejected)
    for area_id in updates:
        rejected.pop(area_id, None)
    areas = merge_vibe(
        {key: value for key, value in current["areas"].items() if key not in reject and key not in drop},
        updates,
        replace_evidence=replace_evidence,
    )
    milestone = vibe_progress(areas).milestone
    reached_at = (
        current["milestone_reached_at"]
        if milestone == current["milestone"] and current["milestone_reached_at"]
        else now or utc_now()
    )
    values = {
        "card": _protect_text(
            owner_id, json.dumps({**areas, **({REJECTED_KEY: rejected} if rejected else {})}, ensure_ascii=False)
        ),
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
    return {
        "areas": areas,
        "rejected": rejected,
        "applied": tuple(updates),
        "milestone": milestone,
        "milestone_reached_at": reached_at,
    }


def drop_vibe_proof_from_conversation(user_id: str, conversation_id: str) -> dict[str, Any] | None:
    """A deleted chat takes its proof with it; a line left without proof goes too."""
    owner_id = _require_user_id(user_id, "agent vibe card")
    current = get_vibe_card(owner_id)
    touched = {
        area_id: {
            "text": line_text(line),
            "evidence": [item for item in line_evidence(line) if item["conversation_id"] != conversation_id],
        }
        for area_id, line in current["areas"].items()
        if any(item["conversation_id"] == conversation_id for item in line_evidence(line))
    }
    if not touched:
        return None
    keep = {area_id: line for area_id, line in touched.items() if line["evidence"]}
    return update_vibe_card(
        owner_id,
        keep,
        drop=tuple(area_id for area_id, line in touched.items() if not line["evidence"]),
        replace_evidence=True,
    )


def _stored(owner_id: str, stored: str) -> dict[str, Any]:
    try:
        value = json.loads(_unprotect_text(owner_id, stored) or "{}")
    except (TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _rejected(stored: dict[str, Any]) -> dict[str, dict[str, Any]]:
    value = stored.get(REJECTED_KEY)
    return {
        area_id: record
        for area_id, record in (value.items() if isinstance(value, dict) else ())
        if isinstance(record, dict) and isinstance(record.get("at"), str)
    }


__all__ = ["drop_vibe_proof_from_conversation", "get_vibe_card", "update_vibe_card"]
