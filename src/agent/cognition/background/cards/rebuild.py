"""Rewrites the user card from scratch, from every active memory, about once a day.

Each background run patches the card from one batch of messages, so a wrong or stale line can stay
for good (a test claim taken as a move, a finished study topic still "current"). The rebuild starts
from the memories alone, which carry their dates and proof: a line no memory supports goes, a newer
memory wins over an older one, and something over is written as over. It runs when the user comes
back and the card was not rebuilt in the last day; one model call.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from typing import Any

from agent.jobs.queue import schedule_job
from agent.memory_engine.memories.focus import focus_state, without_focus_lines
from agent.memory_engine.memories.user_card import validate_user_card
from agent.providers import rebuild_user_card_text
from agent.shared.clock import utc_now
from agent.shared.timeline import parse_time, user_zone
from storage import get_user_card, get_user_timezone, list_agent_memories
from storage.user_cards import card_rebuilt_at, set_user_card

from agent.cognition.background.cards.prompt import CARD_REBUILD_SYSTEM_PROMPT

logger = logging.getLogger(__name__)

CARD_REBUILD_JOB = "card_rebuild"
REBUILD_EVERY = timedelta(days=1)
MAX_MEMORIES = 80
# Jobs are keyed by chat; the card belongs to the user, so it uses this fixed key.
_JOB_KEY = "user-card"




def card_rebuild_due(user_id: str, now: datetime | None = None) -> bool:
    last = card_rebuilt_at(user_id)
    return last is None or (now or utc_now()) - last >= REBUILD_EVERY


def schedule_card_rebuild(user_id: str) -> bool:
    """Queue a rebuild when it is due and there is something to build from."""
    if not card_rebuild_due(user_id) or not any(memory["status"] == "active" for memory in list_agent_memories(user_id)):
        return False
    schedule_job(CARD_REBUILD_JOB, user_id, _JOB_KEY, delay_seconds=0)
    return True


async def run_card_rebuild_job(job: dict[str, Any]) -> dict[str, Any]:
    return await rebuild_user_card(job["user_id"])


async def rebuild_user_card(user_id: str, now: datetime | None = None) -> dict[str, Any]:
    now = now or utc_now()
    memories = card_memories(user_id, now)
    if not memories:
        return {"status": "nothing_to_build"}
    current = get_user_card(user_id) or ""
    zone = user_zone(get_user_timezone(user_id))
    raw = await rebuild_user_card_text(
        json.dumps({"today": now.astimezone(zone).date().isoformat(), "memories": memories, "current_user_card": current}, ensure_ascii=False),
        conversation_id=None,
    )
    card = validate_user_card(_lines(raw.get("user_card") if isinstance(raw, dict) else None))
    if not card:
        return {"status": "no_card"}
    focus = [memory for memory in list_agent_memories(user_id) if memory.get("focus") and memory.get("status") == "active"]
    card = without_focus_lines(card, focus)
    set_user_card(user_id, card, rebuilt=True)
    logger.info("agent.card_rebuild user_id=%s lines=%s changed=%s", user_id, len(card.splitlines()), card != current)
    return {"status": "rebuilt", "changed": card != current}


def card_memories(user_id: str, now: datetime) -> list[dict[str, Any]]:
    """What the rebuild reads: active memories with their date and focus, newest first."""
    rows = []
    for memory in list_agent_memories(user_id):
        if memory["status"] != "active" or memory.get("sensitivity") == "highly_sensitive":
            continue
        state = focus_state(memory, now)
        if state == "archived":
            state = "over"
        said = parse_time(memory.get("occurred_at")) or min(
            (moment for moment in (parse_time(item.get("observed_at")) for item in memory.get("evidence") or []) if moment),
            default=parse_time(memory.get("created_at")),
        )
        rows.append(
            {
                "known": memory.get("statement") or str(memory.get("value")),
                "kind": memory.get("kind"),
                "date": said.date().isoformat() if said else None,
                **({"focus": state} if state else {}),
                "_rank": (said or now).timestamp(),
            }
        )
    rows.sort(key=lambda row: row["_rank"], reverse=True)
    return [{key: value for key, value in row.items() if key != "_rank"} for row in rows[:MAX_MEMORIES]]


def _lines(card: Any) -> Any:
    if isinstance(card, list):
        return "\n".join(str(line).strip() for line in card if str(line).strip()) or None
    return card


__all__ = [
    "CARD_REBUILD_JOB",
    "CARD_REBUILD_SYSTEM_PROMPT",
    "card_memories",
    "card_rebuild_due",
    "rebuild_user_card",
    "run_card_rebuild_job",
    "schedule_card_rebuild",
]
